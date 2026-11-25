package dev.bento.engine.bridge

/**
 * Host bridges called from the Python adapters (`adapters/android/`) through Chaquopy.
 * Signatures are binding: architecture/android-runtime.md §5.1. Arguments are primitives/strings,
 * structured results are JSON strings with snake_case keys, failures throw [BridgeException].
 * `source` arguments are an absolute path or `fd:<n>` (a descriptor owned by the caller).
 */
open class BridgeException(val code: String, message: String, cause: Throwable? = null) : RuntimeException(message, cause) {
    companion object {
        const val UNSUPPORTED = "unsupported"
        const val NOT_FOUND = "not_found"
        const val PERMISSION_DENIED = "permission_denied"
        const val IO = "io"
        const val CANCELLED = "cancelled"
        const val KEY_LOST = "key_lost"
    }
}

/**
 * `wrapping.bin` exists but can no longer be unwrapped: the AndroidKeystore key is gone or was replaced (OEM keystore
 * reset, data restored without keys) or the file is corrupt. Permanent: the engine stops retrying and the app offers
 * "reset this phone" (SEC-11).
 */
class DeviceKeyLostException(message: String, cause: Throwable? = null) : BridgeException(KEY_LOST, message, cause)

/** Device wrapping key for `WrappedFileKeyStore`; passed to `configure` in memory (not a Python bridge). */
interface KeyWrapping {
    /** The unwrapped 32-byte `BENTO_DEVICE_WRAPPING_KEY`; the caller zeroes it after use. Throws [DeviceKeyLostException]. */
    fun deviceWrappingKey(): ByteArray

    /** Forget the wrapped key and its Keystore key (reset after [DeviceKeyLostException]); the next call creates new ones. */
    fun reset() = Unit
}

/** Bridge key `media_tools`. */
interface MediaTools {
    /** → `{width,height}`; [format] is `jpeg` or `webp`. */
    fun thumbnail(source: String, output: String, maxSide: Int, quality: Int, format: String): String

    /** → `{width,height,duration_ms}`. */
    fun videoFrame(source: String, output: String, maxSide: Int, quality: Int, atMs: Long): String

    /** → `{width,height,page_count}`. */
    fun pdfPage(source: String, output: String, page: Int, maxSide: Int): String

    /**
     * → `{width,height,duration_ms,taken_at,orientation,
     *    exif:{make,model,lens,f_number,exposure_time,iso,focal_length,gps:{lat,lon}?}}`.
     */
    fun metadata(source: String, mime: String): String
}

/** Bridge key `ocr`. */
interface Ocr {
    fun available(): Boolean

    /** → `{text, language, lines:[{text, box:[x,y,w,h], confidence}]}`. */
    fun recognize(source: String, maxSide: Int): String
}

/** Bridge key `media_store`. */
interface MediaStoreSource {
    /** → `{full, partial, location}`. */
    fun access(): String

    /** → `[{bucket_id, name, relative_path, count, video_count}]`. */
    fun buckets(): String

    /** → `{items:[MediaItem], next_after: Long?}`. */
    fun scan(bucketId: String, afterMediaId: Long, limit: Int): String

    /** → `{items:[MediaItem], max_generation}`. */
    fun changes(sinceGeneration: Long, limit: Int): String

    /** [mediaIds] is a JSON list; → JSON list of the ids still present. */
    fun exists(mediaIds: String): String

    /** Detached descriptor; Python owns and closes it. */
    fun openFd(uri: String, requireOriginal: Boolean): Int
}

/** Bridge key `conditions`. */
interface DeviceConditions {
    /** → `DeviceConditions` JSON (api/android-endpoints.md §2). */
    fun snapshot(): String
}

/** Bridge key `notifier`. */
interface Notifier {
    /** Semantic events of api/android-endpoints.md §7; no user strings cross the bridge. */
    fun emit(event: String, payloadJson: String)
}

/** Bridge key `content_imports`. */
interface ContentImports {
    /** → `{display_name, mime_type, size_bytes?}`. */
    fun describe(handle: Long): String

    /** One-time detached descriptor; Python owns and closes it. */
    fun adopt(handle: Long): Int
}

/** The bridge instances passed in `configure(config)["bridges"]`, keyed as in §5.1. */
data class BridgeSet(
    val mediaTools: MediaTools,
    val ocr: Ocr,
    val mediaStore: MediaStoreSource,
    val conditions: DeviceConditions,
    val notifier: Notifier,
    val contentImports: ContentImports
) {
    fun asMap(): Map<String, Any> = linkedMapOf(
        "media_tools" to mediaTools,
        "ocr" to ocr,
        "media_store" to mediaStore,
        "conditions" to conditions,
        "notifier" to notifier,
        "content_imports" to contentImports
    )
}
