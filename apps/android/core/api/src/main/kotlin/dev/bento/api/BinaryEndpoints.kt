package dev.bento.api

import dev.bento.api.generated.AssetResponse
import okhttp3.MediaType
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody
import okio.BufferedSink
import okio.source
import java.io.InputStream

/** Bytes to upload, streamed (never buffered whole in memory). */
class UploadSource(
    val fileName: String,
    val mimeType: String,
    /** -1 when unknown (chunked transfer). */
    val length: Long,
    val open: () -> InputStream,
)

/** Thumbnail sizes the backend stores (api/android-endpoints.md §5). */
enum class ThumbnailSize(val px: Int) {
    SMALL(256),
    MEDIUM(512),
    LARGE(1024),
    ;

    companion object {
        /** Nearest stored size not smaller than [px] (or the largest). */
        fun atLeast(px: Int): ThumbnailSize = entries.firstOrNull { it.px >= px } ?: LARGE
    }
}

/** Operations excluded from generation (multipart, binary bodies). */
class BinaryEndpoints(private val http: BentoHttp) {
    /** `POST /api/assets/upload` (multipart field `file`, optional `folder_id`, `mode`). */
    suspend fun uploadAsset(source: UploadSource, folderId: String? = null, mode: String? = null): AssetResponse {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", source.fileName, StreamingBody(source.mimeType.toMediaTypeOrNull(), source.length, source.open))
            .apply {
                folderId?.let { addFormDataPart("folder_id", it) }
                mode?.let { addFormDataPart("mode", it) }
            }
            .build()
        val text = http.execute("POST", "/api/assets/upload", body = body) { it.body.string() }
        return BentoJson.decodeFromString(AssetResponse.serializer(), text)
    }

    /** Raw bytes of a thumbnail (tests and widgets; the UI uses Coil). */
    suspend fun thumbnailBytes(assetId: String, size: ThumbnailSize = ThumbnailSize.SMALL): ByteArray =
        http.execute("GET", AssetPaths.thumbnail(assetId), listOf("size" to size.px.toString())) { it.body.bytes() }
}

/** Paths of the binary asset routes (one place; Coil and Media3 use these too). */
object AssetPaths {
    fun thumbnail(assetId: String) = "/api/assets/${segment(assetId)}/thumbnail"

    fun preview(assetId: String) = "/api/assets/${segment(assetId)}/preview"

    fun content(assetId: String) = "/api/assets/${segment(assetId)}/content"

    fun download(assetId: String) = "/api/assets/${segment(assetId)}/download"

    private fun segment(value: String): String {
        require(value.isNotEmpty() && value.none { it == '/' || it == '?' || it == '#' || it.isWhitespace() }) { "bad asset id" }
        return value
    }
}

private class StreamingBody(
    private val type: MediaType?,
    private val length: Long,
    private val open: () -> InputStream,
) : RequestBody() {
    override fun contentType(): MediaType? = type

    override fun contentLength(): Long = length

    override fun isOneShot(): Boolean = false

    override fun writeTo(sink: BufferedSink) {
        open().source().use { sink.writeAll(it) }
    }
}
