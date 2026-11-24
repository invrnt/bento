package dev.bento.feature.files

import dev.bento.api.ApiException
import dev.bento.api.generated.BentoEndpoints
import dev.bento.api.generated.BentoInterfacesHttpRoutesAndroidImportRequest
import dev.bento.api.generated.ImportItemRequest
import dev.bento.data.Invalidations
import dev.bento.data.Topic
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull

/** A content URI handed to Bento (SAF, photo picker, share sheet, document tree, `ACTION_VIEW`). */
data class PickedContent(val uri: String, val displayName: String? = null, val mimeType: String? = null, val sizeBytes: Long? = null)

/** Where a batch lands: a Drive folder (null = Archivos root) and, for media, an album. */
data class UploadTarget(val folderId: String?, val albumId: String? = null)

/**
 * Opens content URIs as one-time descriptor handles for `POST /api/android/imports` (the engine's
 * `ContentImportRegistry`); throws when the URI is revoked or unreadable.
 */
interface ContentHandles {
    data class Registered(val handle: Long, val displayName: String, val mimeType: String, val sizeBytes: Long?)

    fun register(uri: String): Registered
}

/** Starts/stops the user-initiated transfer that uploads in background (`core/background` TransferScheduler). */
interface TransferControl {
    fun start(estimatedBytes: Long)

    fun stop()
}

enum class UploadStatus { Queued, Copying, Done, Duplicate, Failed }

data class UploadRow(
    val key: Long,
    val name: String,
    val sizeBytes: Long?,
    val status: UploadStatus = UploadStatus.Queued,
    val error: String? = null,
    val assetId: String? = null
)

/** The floating progress card ("Subiendo 3 archivos · 12 MB de 40 MB"), expandable to per-file rows. */
data class UploadsState(val rows: List<UploadRow> = emptyList(), val paused: Boolean = false) {
    val active: Boolean get() = rows.any { it.status == UploadStatus.Queued || it.status == UploadStatus.Copying }
    val visible: Boolean get() = rows.isNotEmpty()
    val pendingCount: Int get() = rows.count { it.status == UploadStatus.Queued || it.status == UploadStatus.Copying }
    val failedCount: Int get() = rows.count { it.status == UploadStatus.Failed }
    val totalBytes: Long get() = rows.filter { it.status != UploadStatus.Failed }.sumOf { it.sizeBytes ?: 0L }
    val doneBytes: Long get() = rows.filter { it.status == UploadStatus.Done || it.status == UploadStatus.Duplicate }.sumOf {
        it.sizeBytes
            ?: 0L
    }
    val progress: Float? get() = if (totalBytes > 0) (doneBytes.toFloat() / totalBytes).coerceIn(0f, 1f) else null
}

/**
 * Hands picked content to the engine: each URI is opened now (while the grant is alive) and registered as a one-time fd
 * handle, then imported with `POST /api/android/imports` (bytes never travel through HTTP), encrypted and uploaded in
 * background by the transfer job. Unreadable/revoked URIs and failed items are reported to [failures] with their
 * (sanitized) file name, never dropped silently. A [journal] records batches in flight so a process death is reported.
 */
class UploadCoordinator(
    private val api: BentoEndpoints,
    private val handles: ContentHandles,
    private val transfers: TransferControl,
    private val failures: ImportFailureLog,
    private val invalidations: Invalidations,
    private val scope: CoroutineScope,
    private val pollMs: Long = POLL_MS
) {
    private val _state = MutableStateFlow(UploadsState())
    val state: StateFlow<UploadsState> = _state.asStateFlow()
    private val keys = AtomicLong(1)
    private val mutex = Mutex()
    private var clearJob: Job? = null

    init {
        failures.recoverInterrupted()
    }

    /**
     * Registers every item synchronously (fast: it only opens descriptors) and returns the rows; the import continues in
     * [scope]. Callers like the share sheet can finish right after this returns.
     */
    fun submit(items: List<PickedContent>, target: UploadTarget): List<UploadRow> {
        clearJob?.cancel()
        val registered = items.map { item ->
            val key = keys.getAndIncrement()
            val fallbackName = DisplayNames.file(item.displayName ?: item.uri.substringAfterLast('/'))
            try {
                val handle = handles.register(item.uri)
                val name = DisplayNames.file(item.displayName ?: handle.displayName)
                Triple(UploadRow(key, name, item.sizeBytes ?: handle.sizeBytes), handle, item.mimeType ?: handle.mimeType)
            } catch (error: RuntimeException) {
                failures.record(fallbackName, ImportFailureLog.REASON_UNREADABLE)
                Triple(UploadRow(key, fallbackName, item.sizeBytes, UploadStatus.Failed, ImportFailureLog.REASON_UNREADABLE), null, null)
            }
        }
        val rows = registered.map { it.first }
        _state.update { it.copy(rows = it.rows + rows) }
        val ready = registered.filter { it.second != null }
        if (ready.isNotEmpty()) {
            transfers.start(ready.sumOf { it.first.sizeBytes ?: 0L })
            scope.launch { mutex.withLock { runBatches(ready.map { Triple(it.first, it.second!!, it.third!!) }, target) } }
        } else {
            scheduleClear()
        }
        return rows
    }

    fun pause() {
        transfers.stop()
        _state.update { it.copy(paused = true) }
    }

    fun resume() {
        transfers.start(_state.value.totalBytes - _state.value.doneBytes)
        _state.update { it.copy(paused = false) }
    }

    /** Hides finished rows (the card collapses into the avatar ring). */
    fun clearFinished() = _state.update { state ->
        state.copy(
            rows = state.rows.filter {
                it.status == UploadStatus.Queued ||
                    it.status == UploadStatus.Copying
            }
        )
    }

    private suspend fun runBatches(items: List<Triple<UploadRow, ContentHandles.Registered, String>>, target: UploadTarget) {
        for (chunk in items.chunked(MAX_BATCH)) {
            val journalId = failures.journalStart(chunk.map { it.first.name })
            mark(chunk.map { it.first.key }, UploadStatus.Copying)
            val request = BentoInterfacesHttpRoutesAndroidImportRequest(
                albumId = target.albumId,
                folderId = target.folderId,
                items = chunk.map { (row, handle, mime) ->
                    ImportItemRequest(displayName = row.name, fdHandle = handle.handle, mimeType = mime, sizeBytes = row.sizeBytes)
                }
            )
            val importId = try {
                (api.startImport(request) as? JsonObject)?.string("import_id")
            } catch (error: ApiException) {
                null
            }
            if (importId == null) {
                chunk.forEach { (row) -> fail(row, ImportFailureLog.REASON_FAILED) }
            } else {
                follow(importId, chunk.map { it.first })
            }
            failures.journalFinish(journalId)
            invalidations.invalidate(Topic.DRIVE, Topic.TIMELINE, Topic.SEARCH, Topic.ALBUMS, Topic.ACTIVITY)
        }
        scheduleClear()
    }

    private suspend fun follow(importId: String, rows: List<UploadRow>) {
        var misses = 0
        while (true) {
            val body = try {
                api.getImport(importId) as? JsonObject
            } catch (error: ApiException) {
                null
            }
            if (body == null) {
                if (++misses > MAX_MISSES) {
                    rows.forEach { fail(it, ImportFailureLog.REASON_FAILED) }
                    return
                }
            } else {
                misses = 0
                (body["items"] as? JsonArray).orEmpty().filterIsInstance<JsonObject>().forEach { item ->
                    val index = (item["client_index"] as? JsonPrimitive)?.intOrNull ?: return@forEach
                    val row = rows.getOrNull(index) ?: return@forEach
                    apply(row, item.string("status"), item.string("error"), item.string("asset_id"))
                }
                if ((body["done"] as? JsonPrimitive)?.contentOrNull == "true") return
            }
            delay(pollMs)
        }
    }

    private fun apply(row: UploadRow, status: String?, error: String?, assetId: String?) {
        val next = when (status) {
            "done" -> UploadStatus.Done
            "duplicate" -> UploadStatus.Duplicate
            "failed" -> UploadStatus.Failed
            "importing" -> UploadStatus.Copying
            else -> return
        }
        val current = _state.value.rows.firstOrNull { it.key == row.key } ?: return
        if (current.status == next) return
        if (next == UploadStatus.Failed) {
            fail(row, error ?: ImportFailureLog.REASON_FAILED)
            return
        }
        _state.update { state ->
            state.copy(
                rows = state.rows.map {
                    if (it.key ==
                        row.key
                    ) {
                        it.copy(status = next, assetId = assetId)
                    } else {
                        it
                    }
                }
            )
        }
    }

    private fun fail(row: UploadRow, reason: String) {
        failures.record(row.name, reason)
        _state.update { state ->
            state.copy(rows = state.rows.map { if (it.key == row.key) it.copy(status = UploadStatus.Failed, error = reason) else it })
        }
    }

    private fun mark(keys: List<Long>, status: UploadStatus) = _state.update { state ->
        state.copy(rows = state.rows.map { if (it.key in keys && it.status == UploadStatus.Queued) it.copy(status = status) else it })
    }

    private fun scheduleClear() {
        if (_state.value.active) return
        clearJob?.cancel()
        clearJob = scope.launch {
            delay(if (_state.value.failedCount > 0) FAILED_LINGER_MS else DONE_LINGER_MS)
            if (!_state.value.active) _state.update { UploadsState(paused = it.paused) }
        }
    }

    private fun JsonObject.string(key: String): String? = (this[key] as? JsonPrimitive)?.contentOrNull

    companion object {
        const val MAX_BATCH = 500
        const val POLL_MS = 400L
        private const val MAX_MISSES = 25
        const val DONE_LINGER_MS = 4_000L
        const val FAILED_LINGER_MS = 12_000L
    }
}
