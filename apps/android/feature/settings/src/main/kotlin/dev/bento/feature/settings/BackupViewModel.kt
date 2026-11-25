package dev.bento.feature.settings

import android.content.Context
import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import dev.bento.background.TransferScheduler
import dev.bento.data.Invalidations
import dev.bento.engine.BentoEngine
import dev.bento.feature.recovery.Outcome
import dev.bento.feature.recovery.attempt
import javax.inject.Inject
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Android reads behind the backup screens (permissions, MediaStore, transfers); faked in JVM tests. */
interface PhoneMedia {
    fun access(): MediaAccess

    fun location(): Boolean

    fun visibleCount(): Int

    fun newestIn(bucketId: String): Uri?

    fun urisFor(mediaIds: List<String>): Map<String, Uri>

    fun deleted(mediaIds: List<String>): List<String>

    /** Starts the user-initiated transfer (initial backup, `Respaldar ahora`); only while the app is visible. */
    fun startTransfer()

    /** Tells the engine the media access changed (it rescans or stops reading). */
    fun accessChanged()
}

class AndroidPhoneMedia @Inject constructor(
    @ApplicationContext private val context: Context,
    private val engine: BentoEngine
) : PhoneMedia {
    override fun access() = MediaPermissions.current(context)

    override fun location() = MediaPermissions.location(context)

    override fun visibleCount() = CameraRoll.visibleCount(context)

    override fun newestIn(bucketId: String) = CameraRoll.newestIn(context, bucketId)

    override fun urisFor(mediaIds: List<String>) = CameraRoll.urisFor(context, mediaIds)

    override fun deleted(mediaIds: List<String>) = CameraRoll.deleted(context, mediaIds)

    override fun startTransfer() = TransferScheduler.start(context)

    override fun accessChanged() = engine.onEvent("access_changed", "{}")
}

/** One camera-roll folder: the backend's bucket, its source (when added) and the newest item as thumbnail. */
data class BucketRow(
    val bucketId: String,
    val name: String,
    val count: Int,
    val suggested: Boolean,
    val sourceId: String? = null,
    val enabled: Boolean = false,
    val pending: Int = 0,
    val thumbnail: Uri? = null
)

/** Free-up-space flow: preview → system delete request → confirmation reported to the backend. */
sealed interface FreeUpState {
    data object Loading : FreeUpState

    data class Preview(val preview: FreeUpPreview) : FreeUpState

    data object Deleting : FreeUpState

    data class Done(val count: Int, val bytes: Long) : FreeUpState

    /** The system request was cancelled: nothing was deleted. */
    data object Cancelled : FreeUpState

    data object Failed : FreeUpState
}

data class BackupUiState(
    val loading: Boolean = true,
    val loadFailed: Boolean = false,
    val access: MediaAccess = MediaAccess.Denied,
    val location: Boolean = false,
    val visibleCount: Int = 0,
    val buckets: List<BucketRow> = emptyList(),
    val settings: PhoneSettings? = null,
    val status: BackupStatus? = null,
    val policy: BackupPolicy? = null,
    /** The system will not ask again (denied twice / "Don't allow"): the action opens the app's settings. */
    val permanentlyDenied: Boolean = false,
    /** Asked and denied in this session: never asked twice in a session (§6). */
    val deniedThisSession: Boolean = false,
    val showRationale: Boolean = false,
    val showLocationNotice: Boolean = false,
    val stalled: Boolean = false,
    val runningNow: Boolean = false,
    val saving: Boolean = false,
    val freeUp: FreeUpState? = null,
    val failed: Boolean = false
) {
    /** Backup is on when a camera-roll folder is enabled. */
    val configuredOn: Boolean get() = buckets.any { it.enabled }

    /** Enabled folders that can no longer be read (permission revoked later). */
    val revoked: Boolean get() = configuredOn && access == MediaAccess.Denied

    val header: BackupHeader get() = BackupHeader.of(configuredOn, access, status, policy)
}

sealed interface BackupEffect {
    data class RequestMedia(val permissions: List<String>) : BackupEffect

    data object RequestLocation : BackupEffect

    data object OpenAppSettings : BackupEffect

    /** Android 11+: the system delete request for [uris]; Android 10: per-item consent senders. */
    data class DeleteRequest(val uris: List<Uri>) : BackupEffect

    /** Onboarding: the backup step is finished (on, or deliberately left off). */
    data object Finished : BackupEffect
}

/**
 * Phone backup setup and Ajustes › Respaldo (product/android.md §4.1 step 4, §5, §6). Permission results come back
 * through [onMediaResult]/[onLocationResult]; the composable owns the launchers.
 */
@HiltViewModel
class BackupViewModel internal constructor(
    private val backup: BackupRepository,
    private val phoneSettings: PhoneSettingsRepository,
    private val media: PhoneMedia,
    private val local: LocalSettings,
    private val clock: Clock,
    /** MediaStore and permission reads; tests pass their virtual-time dispatcher. */
    private val io: CoroutineDispatcher,
    /** Server events (jobs/sync stream) keep the status header live while the screen is open; null in tests. */
    invalidations: Invalidations? = null
) : ViewModel() {
    @Inject
    constructor(
        backup: BackupRepository,
        phoneSettings: PhoneSettingsRepository,
        media: PhoneMedia,
        local: LocalSettings,
        clock: Clock,
        invalidations: Invalidations
    ) : this(backup, phoneSettings, media, local, clock, Dispatchers.IO, invalidations)

    private val _state = MutableStateFlow(BackupUiState())
    val state: StateFlow<BackupUiState> = _state.asStateFlow()
    private val _effects = Channel<BackupEffect>(Channel.BUFFERED)
    val effects: Flow<BackupEffect> = _effects.receiveAsFlow()

    /** Pending free-up ids for the request in flight. */
    private var deleting: List<FreeUpItem> = emptyList()

    init {
        refresh()
        invalidations?.let { events ->
            viewModelScope.launch {
                @OptIn(kotlinx.coroutines.FlowPreview::class)
                events.topics.debounce(LIVE_DEBOUNCE_MS).collect { refreshLive() }
            }
            viewModelScope.launch {
                while (true) {
                    kotlinx.coroutines.delay(LIVE_TICK_MS)
                    refreshLive()
                }
            }
        }
    }

    /** Status and policy only (cheap); folders reload on resume and after changes. */
    private suspend fun refreshLive() {
        if (_state.value.loading) return
        val status = (attempt { backup.status() } as? Outcome.Ok)?.value ?: return
        val policy = (attempt { backup.policy() } as? Outcome.Ok)?.value
        _state.update { it.copy(status = status, policy = policy ?: it.policy) }
    }

    /** On start and every resume: permissions may have changed in system settings meanwhile ("revoked later"). */
    fun refresh() {
        viewModelScope.launch {
            val previous = _state.value.access
            val access = withContext(io) { media.access() }
            val location = withContext(io) { media.location() }
            val visible = if (access == MediaAccess.Partial) withContext(io) { media.visibleCount() } else 0
            _state.update { it.copy(access = access, location = location, visibleCount = visible) }
            if (!_state.value.loading && previous != access) media.accessChanged()
            load()
        }
    }

    private suspend fun load() {
        val sources = attempt { backup.sources() }
        val buckets = attempt { backup.buckets() }
        val status = (attempt { backup.status() } as? Outcome.Ok)?.value
        val policy = (attempt { backup.policy() } as? Outcome.Ok)?.value
        val settings = (attempt { phoneSettings.load() } as? Outcome.Ok)?.value
        if (sources !is Outcome.Ok || buckets !is Outcome.Ok) {
            _state.update { it.copy(loading = false, loadFailed = it.buckets.isEmpty()) }
            return
        }
        val rows = withContext(io) { merge(buckets.value, sources.value) }
        val stored = local.prefs.first()
        val prefs = StallDetector.track(stored, status?.pending ?: 0, clock.now())
        if (prefs != stored) local.update { prefs }
        val on = rows.any { it.enabled }
        _state.update {
            it.copy(
                loading = false,
                loadFailed = false,
                buckets = rows,
                status = status,
                policy = policy,
                settings = settings ?: it.settings,
                stalled = StallDetector.stalled(status, policy, on, prefs, clock.now()),
                showLocationNotice = on && !it.location && it.access != MediaAccess.Denied && !prefs.locationNoticeShown
            )
        }
    }

    private fun merge(buckets: List<BucketSuggestion>, sources: List<BackupSourceDto>): List<BucketRow> {
        val bySource = sources.filter { it.kind == BackupRepository.MEDIA_STORE && it.bucketId != null }.associateBy { it.bucketId }
        return buckets.map { bucket ->
            val source = bySource[bucket.id]
            BucketRow(
                bucketId = bucket.id!!,
                name = bucket.title,
                count = bucket.count,
                suggested = bucket.suggested,
                sourceId = source?.id,
                enabled = source?.enabled == true,
                pending = source?.filesPending ?: 0,
                thumbnail = media.newestIn(bucket.id)
            )
        }.sortedWith(compareByDescending<BucketRow> { it.suggested }.thenByDescending { it.enabled }.thenByDescending { it.count })
    }

    // Turning backup on -----------------------------------------------------------------------------------------

    /** `Respaldar fotos` / the on switch: one-line rationale first, then the system permission (never at launch). */
    fun turnOn() {
        val s = _state.value
        when {
            s.access != MediaAccess.Denied -> enableDefaults()
            s.permanentlyDenied -> _effects.trySend(BackupEffect.OpenAppSettings)
            else -> _state.update { it.copy(showRationale = true) }
        }
    }

    fun rationaleAccepted() {
        _state.update { it.copy(showRationale = false) }
        _effects.trySend(BackupEffect.RequestMedia(MediaPermissions.media()))
    }

    fun rationaleDismissed() = _state.update { it.copy(showRationale = false) }

    /** [canAskAgain] = `shouldShowRequestPermissionRationale` after the result (false + denied = permanently denied). */
    fun onMediaResult(canAskAgain: Boolean) {
        val access = media.access()
        _state.update {
            it.copy(
                access = access,
                deniedThisSession = access == MediaAccess.Denied,
                permanentlyDenied = access == MediaAccess.Denied && !canAskAgain,
                visibleCount = if (access == MediaAccess.Partial) media.visibleCount() else 0
            )
        }
        media.accessChanged()
        if (access == MediaAccess.Denied) return
        if (!media.location()) _effects.trySend(BackupEffect.RequestLocation) else enableDefaults()
    }

    fun onLocationResult() {
        _state.update { it.copy(location = media.location()) }
        enableDefaults()
    }

    fun dismissLocationNotice() {
        _state.update { it.copy(showLocationNotice = false) }
        viewModelScope.launch { local.update { it.copy(locationNoticeShown = true) } }
    }

    /** `Cámara` and `Capturas de pantalla` (the backend's suggested buckets) on by default. */
    private fun enableDefaults() {
        viewModelScope.launch {
            _state.update { it.copy(saving = true, failed = false) }
            // The first load may have run before the engine answered (onboarding opens this right after sign-in).
            load()
            val rows = _state.value.buckets
            val targets = rows.filter { it.suggested }.ifEmpty { rows.take(1) }
            val ok = targets.filterNot { it.enabled }.all { row -> attempt { enableBucket(row) } is Outcome.Ok }
            _state.update { it.copy(saving = false, failed = !ok) }
            load()
            if (ok) {
                // The initial backup runs as a user-initiated transfer; right after enabling, the backlog may not be
                // counted yet (the scan is queued), so the folders' own counts decide.
                if (targets.sumOf { it.count } > 0 || (_state.value.status?.pending ?: 0) > 0) media.startTransfer()
                _effects.trySend(BackupEffect.Finished)
            }
        }
    }

    private suspend fun enableBucket(row: BucketRow) {
        if (row.sourceId != null) backup.setEnabled(row.sourceId, true) else backup.addBucket(row.bucketId, row.name)
    }

    /** The off switch: every camera-roll folder off (nothing already backed up is touched). */
    fun turnOff() = mutate {
        _state.value.buckets.filter { it.enabled && it.sourceId != null }.forEach { backup.setEnabled(it.sourceId!!, false) }
    }

    fun setBucket(row: BucketRow, enabled: Boolean) {
        if (enabled && _state.value.access == MediaAccess.Denied) return turnOn()
        _state.update { s -> s.copy(buckets = s.buckets.map { if (it.bucketId == row.bucketId) it.copy(enabled = enabled) else it }) }
        mutate { if (enabled) enableBucket(row) else row.sourceId?.let { backup.setEnabled(it, false) } }
    }

    // Policy ----------------------------------------------------------------------------------------------------

    fun setWifiOnly(value: Boolean) = setting(PhoneSettings.WIFI_ONLY, value) { it.copy(wifiOnly = value) }

    /** "Videos solo con Wi-Fi" is the inverse of `backup_videos_on_metered`. */
    fun setVideosWifiOnly(value: Boolean) = setting(PhoneSettings.VIDEOS_ON_METERED, !value) { it.copy(videosOnMetered = !value) }

    fun setOnlyCharging(value: Boolean) = setting(PhoneSettings.ONLY_CHARGING, value) { it.copy(onlyCharging = value) }

    private fun setting(key: String, value: Boolean, optimistic: (PhoneSettings) -> PhoneSettings) {
        val before = _state.value.settings
        _state.update { s -> s.copy(settings = s.settings?.let(optimistic)) }
        viewModelScope.launch {
            when (val result = attempt { phoneSettings.set(key, value) }) {
                is Outcome.Ok -> _state.update { it.copy(settings = result.value) }
                is Outcome.Err -> _state.update { it.copy(settings = before, failed = true) }
            }
            refreshStatus()
        }
    }

    fun setPaused(paused: Boolean) = mutate {
        backup.setPaused(paused)
        if (!paused && (_state.value.status?.pending ?: 0) > 0) media.startTransfer()
    }

    /** `Respaldar ahora`: lifts the Wi-Fi rule once (battery and heat rules still apply) as a user-initiated transfer. */
    fun runNow() {
        viewModelScope.launch {
            _state.update { it.copy(runningNow = true, failed = false) }
            val result = attempt { backup.runNow() }
            if (result is Outcome.Ok) media.startTransfer()
            _state.update { it.copy(runningNow = false, failed = result is Outcome.Err) }
            refreshStatus()
        }
    }

    fun dismissStall() {
        _state.update { it.copy(stalled = false) }
        viewModelScope.launch { local.update { it.copy(stallDismissedAt = clock.now()) } }
    }

    private suspend fun refreshStatus() {
        (attempt { backup.status() } as? Outcome.Ok)?.let { ok -> _state.update { it.copy(status = ok.value) } }
    }

    private fun mutate(block: suspend () -> Unit) {
        viewModelScope.launch {
            _state.update { it.copy(saving = true, failed = false) }
            val result = attempt { block() }
            _state.update { it.copy(saving = false, failed = result is Outcome.Err) }
            load()
        }
    }

    // Liberar espacio -------------------------------------------------------------------------------------------

    fun openFreeUp() {
        _state.update { it.copy(freeUp = FreeUpState.Loading) }
        viewModelScope.launch {
            _state.update {
                it.copy(
                    freeUp = when (val result = attempt { backup.freeUpPreview() }) {
                        is Outcome.Ok -> FreeUpState.Preview(result.value)
                        is Outcome.Err -> FreeUpState.Failed
                    }
                )
            }
        }
    }

    /** `Liberar X GB`: only verified items (the preview lists blob-confirmed, hash-matched originals). */
    fun confirmFreeUp() {
        val preview = (_state.value.freeUp as? FreeUpState.Preview)?.preview ?: return
        viewModelScope.launch {
            val uris = withContext(io) { media.urisFor(preview.items.map { it.mediaId }) }
            deleting = preview.items.filter { it.mediaId in uris }
            if (deleting.isEmpty()) {
                report()
                return@launch
            }
            _state.update { it.copy(freeUp = FreeUpState.Deleting) }
            _effects.trySend(BackupEffect.DeleteRequest(deleting.mapNotNull { uris[it.mediaId] }))
        }
    }

    /** After the system request (approved or not): report exactly what is gone. */
    fun onDeleteResult(approved: Boolean) {
        viewModelScope.launch {
            if (!approved && withContext(io) { media.deleted(deleting.map { it.mediaId }) }.isEmpty()) {
                _state.update { it.copy(freeUp = FreeUpState.Cancelled) }
                return@launch
            }
            report()
        }
    }

    private suspend fun report() {
        val gone = withContext(io) { media.deleted(deleting.map { it.mediaId }) }.toSet()
        val removed = deleting.filter { it.mediaId in gone }
        if (removed.isEmpty()) {
            _state.update { it.copy(freeUp = FreeUpState.Cancelled) }
            return
        }
        val result = attempt { backup.freeUpConfirm(removed.map { it.mediaId }) }
        _state.update {
            it.copy(
                freeUp = if (result is Outcome.Ok) {
                    FreeUpState.Done(
                        removed.size,
                        removed.sumOf { item ->
                            item.sizeBytes
                        }
                    )
                } else {
                    FreeUpState.Failed
                }
            )
        }
        deleting = emptyList()
        load()
    }

    fun closeFreeUp() = _state.update { it.copy(freeUp = null) }

    // Onboarding ------------------------------------------------------------------------------------------------

    /** `Ahora no`: backup stays off; Fotos keeps a dismissible card for 7 days. */
    fun notNow() {
        viewModelScope.launch {
            local.update { it.copy(backupPromptDismissedAt = clock.now()) }
            _effects.trySend(BackupEffect.Finished)
        }
    }

    /** Denied in onboarding: continue without backup (the photo picker still uploads). */
    fun continueWithoutBackup() {
        _effects.trySend(BackupEffect.Finished)
    }
}

private const val LIVE_DEBOUNCE_MS = 500L
private const val LIVE_TICK_MS = 10_000L

/** Injectable time source (tests pass a fixed clock). */
fun interface Clock {
    fun now(): Long
}
