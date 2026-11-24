package dev.bento.engine.bridge

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import java.util.concurrent.atomic.AtomicLong
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class ContentDescription(
    @SerialName("display_name") val displayName: String,
    @SerialName("mime_type") val mimeType: String,
    @SerialName("size_bytes") val sizeBytes: Long? = null
)

/** Opens a content URI as a detached descriptor (Android: ContentResolver); faked on the JVM. */
interface DescriptorOpener {
    fun open(uri: String): Int

    fun describe(uri: String): ContentDescription

    fun close(fd: Int)
}

/**
 * [ContentImports]: Kotlin registers a content URI (share sheet, SAF) and passes the returned handle to
 * `POST /api/android/imports`; Python adopts each handle exactly once and closes the descriptor.
 * Unclaimed handles are closed after [ttlMs].
 */
class ContentImportRegistry(
    private val opener: DescriptorOpener,
    private val clock: () -> Long = System::currentTimeMillis,
    private val ttlMs: Long = TTL_MS
) : ContentImports {
    private data class Entry(val fd: Int, val description: ContentDescription, val registeredAt: Long)

    private val nextHandle = AtomicLong(1)
    private val entries = HashMap<Long, Entry>()

    /** Opens [uri] now (while the caller holds the URI grant) and returns a one-time handle. */
    fun register(uri: String): Long {
        val description = opener.describe(uri)
        val fd = opener.open(uri)
        val handle = nextHandle.getAndIncrement()
        synchronized(entries) {
            expire()
            entries[handle] = Entry(fd, description, clock())
        }
        return handle
    }

    override fun describe(handle: Long): String {
        val entry = synchronized(entries) {
            expire()
            entries[handle]
        } ?: throw BridgeException(BridgeException.NOT_FOUND, "unknown import handle")
        return BridgeJson.encodeToString(ContentDescription.serializer(), entry.description)
    }

    override fun adopt(handle: Long): Int {
        val entry = synchronized(entries) {
            expire()
            entries.remove(handle)
        } ?: throw BridgeException(BridgeException.NOT_FOUND, "unknown or already adopted import handle")
        return entry.fd
    }

    /** Close every pending descriptor (engine stop). */
    fun clear() {
        val pending = synchronized(entries) { entries.values.toList().also { entries.clear() } }
        pending.forEach { runCatching { opener.close(it.fd) } }
    }

    fun pendingCount(): Int = synchronized(entries) { entries.size }

    private fun expire() {
        val now = clock()
        val stale = entries.filterValues { now - it.registeredAt > ttlMs }
        stale.forEach { (handle, entry) ->
            entries.remove(handle)
            runCatching { opener.close(entry.fd) }
        }
    }

    companion object {
        const val TTL_MS = 10 * 60_000L
    }
}

class ContentResolverDescriptorOpener(private val resolver: ContentResolver) : DescriptorOpener {
    override fun open(uri: String): Int = bridgeCall {
        val pfd = resolver.openFileDescriptor(Uri.parse(uri), "r") ?: throw BridgeException(BridgeException.NOT_FOUND, "content not found")
        pfd.detachFd()
    }

    override fun describe(uri: String): ContentDescription = bridgeCall {
        val parsed = Uri.parse(uri)
        var name: String? = null
        var size: Long? = null
        resolver.query(parsed, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME).takeIf { it >= 0 && !cursor.isNull(it) }?.let {
                    name =
                        cursor.getString(it)
                }
                cursor.getColumnIndex(OpenableColumns.SIZE).takeIf { it >= 0 && !cursor.isNull(it) }?.let { size = cursor.getLong(it) }
            }
        }
        ContentDescription(
            displayName = name ?: parsed.lastPathSegment ?: "archivo",
            mimeType = resolver.getType(parsed) ?: "application/octet-stream",
            sizeBytes = size
        )
    }

    override fun close(fd: Int) {
        android.os.ParcelFileDescriptor.adoptFd(fd).close()
    }
}
