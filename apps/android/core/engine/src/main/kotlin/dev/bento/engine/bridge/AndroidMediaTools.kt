package dev.bento.engine.bridge

import android.content.res.AssetFileDescriptor
import android.graphics.Bitmap
import android.graphics.ImageDecoder
import android.graphics.pdf.PdfRenderer
import android.media.MediaMetadataRetriever
import android.os.ParcelFileDescriptor
import androidx.exifinterface.media.ExifInterface
import java.io.File
import java.util.concurrent.atomic.AtomicInteger
import kotlin.math.max
import kotlin.math.roundToInt
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class ImageSize(val width: Int, val height: Int)

@Serializable
data class VideoFrameResult(val width: Int, val height: Int, @SerialName("duration_ms") val durationMs: Long?)

@Serializable
data class PdfPageResult(val width: Int, val height: Int, @SerialName("page_count") val pageCount: Int)

@Serializable
data class GpsPoint(val lat: Double, val lon: Double)

@Serializable
data class ExifSummary(
    val make: String? = null,
    val model: String? = null,
    val lens: String? = null,
    @SerialName("f_number") val fNumber: Double? = null,
    @SerialName("exposure_time") val exposureTime: Double? = null,
    val iso: Int? = null,
    @SerialName("focal_length") val focalLength: Double? = null,
    val gps: GpsPoint? = null
)

@Serializable
data class MediaMetadata(
    val width: Int?,
    val height: Int?,
    @SerialName("duration_ms") val durationMs: Long?,
    @SerialName("taken_at") val takenAt: String?,
    val orientation: Int?,
    val exif: ExifSummary
)

/** Pure geometry and EXIF helpers (JVM tested). */
object MediaMath {
    /** Size that fits [maxSide] keeping the aspect ratio; never upscales. */
    fun fit(width: Int, height: Int, maxSide: Int): ImageSize {
        require(width > 0 && height > 0 && maxSide > 0) { "positive sizes required" }
        val scale = maxSide.toDouble() / max(width, height)
        if (scale >= 1.0) return ImageSize(width, height)
        return ImageSize((width * scale).roundToInt().coerceAtLeast(1), (height * scale).roundToInt().coerceAtLeast(1))
    }

    /** `jpeg` or `webp` (normalized); anything else is `unsupported`. */
    fun outputFormat(format: String): String = when (format.lowercase()) {
        "jpeg", "jpg" -> "jpeg"
        "webp" -> "webp"
        else -> throw BridgeException(BridgeException.UNSUPPORTED, "format must be jpeg or webp")
    }

    /** EXIF `DateTimeOriginal` (`yyyy:MM:dd HH:mm:ss`, optional offset) → ISO-8601 local or offset time. */
    fun exifDateToIso(value: String?, offset: String?): String? {
        if (value.isNullOrBlank()) return null
        val match = Regex("^(\\d{4}):(\\d{2}):(\\d{2}) (\\d{2}):(\\d{2}):(\\d{2})").find(value.trim()) ?: return null
        val (y, mo, d, h, mi, s) = match.destructured
        if (y == "0000") return null
        val suffix = offset?.trim()?.takeIf { Regex("^[+-]\\d{2}:\\d{2}$").matches(it) }.orEmpty()
        return "$y-$mo-${d}T$h:$mi:$s$suffix"
    }

    /** Swap width/height for EXIF orientations 5-8 (rotated 90/270). */
    fun displaySize(width: Int, height: Int, orientation: Int?): ImageSize =
        if (orientation in 5..8) ImageSize(height, width) else ImageSize(width, height)
}

/**
 * [MediaTools] over the platform decoders: `ImageDecoder` (HEIC/AVIF/DNG/animated, EXIF orientation applied),
 * `MediaMetadataRetriever` for video posters and duration, `PdfRenderer` for PDF pages, `ExifInterface`.
 * One coarse call per file; outputs are written atomically.
 */
class AndroidMediaTools : MediaTools {
    /** Calls served (instrumented tests check the backend really uses the bridge). */
    val calls = AtomicInteger()

    override fun thumbnail(source: String, output: String, maxSide: Int, quality: Int, format: String): String = bridgeCall {
        calls.incrementAndGet()
        val compress = when {
            MediaMath.outputFormat(format) != "webp" -> Bitmap.CompressFormat.JPEG

            android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.R -> Bitmap.CompressFormat.WEBP_LOSSY

            else ->
                @Suppress("DEPRECATION")
                Bitmap.CompressFormat.WEBP
        }
        val bitmap = decodeImage(BridgeSource.parse(source), maxSide)
        try {
            writeBitmap(bitmap, compress, quality, File(output))
            BridgeJson.encodeToString(ImageSize.serializer(), ImageSize(bitmap.width, bitmap.height))
        } finally {
            bitmap.recycle()
        }
    }

    override fun videoFrame(source: String, output: String, maxSide: Int, quality: Int, atMs: Long): String = bridgeCall {
        calls.incrementAndGet()
        BridgeSource.parse(source).openPfd().use { pfd ->
            val retriever = MediaMetadataRetriever()
            try {
                retriever.setDataSource(pfd.fileDescriptor)
                val duration = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull()
                val width = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)?.toIntOrNull() ?: maxSide
                val height = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)?.toIntOrNull() ?: maxSide
                val target = MediaMath.fit(width, height, maxSide)
                val frame = retriever.getScaledFrameAtTime(
                    atMs.coerceAtLeast(0) * 1000,
                    MediaMetadataRetriever.OPTION_CLOSEST_SYNC,
                    target.width,
                    target.height
                ) ?: throw BridgeException(BridgeException.UNSUPPORTED, "no decodable video frame")
                try {
                    writeBitmap(frame, Bitmap.CompressFormat.JPEG, quality, File(output))
                    BridgeJson.encodeToString(VideoFrameResult.serializer(), VideoFrameResult(frame.width, frame.height, duration))
                } finally {
                    frame.recycle()
                }
            } finally {
                retriever.release()
            }
        }
    }

    override fun pdfPage(source: String, output: String, page: Int, maxSide: Int): String = bridgeCall {
        calls.incrementAndGet()
        BridgeSource.parse(source).openPfd().use { pfd ->
            PdfRenderer(pfd).use { renderer ->
                if (page !in 0 until renderer.pageCount) throw BridgeException(BridgeException.NOT_FOUND, "page out of range")
                renderer.openPage(page).use { pdfPage ->
                    val size = MediaMath.fit(pdfPage.width.coerceAtLeast(1) * 2, pdfPage.height.coerceAtLeast(1) * 2, maxSide)
                    val bitmap = Bitmap.createBitmap(size.width, size.height, Bitmap.Config.ARGB_8888)
                    try {
                        bitmap.eraseColor(android.graphics.Color.WHITE)
                        pdfPage.render(bitmap, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                        writeBitmap(bitmap, Bitmap.CompressFormat.JPEG, PDF_QUALITY, File(output))
                        BridgeJson.encodeToString(
                            PdfPageResult.serializer(),
                            PdfPageResult(bitmap.width, bitmap.height, renderer.pageCount)
                        )
                    } finally {
                        bitmap.recycle()
                    }
                }
            }
        }
    }

    override fun metadata(source: String, mime: String): String = bridgeCall {
        calls.incrementAndGet()
        val parsed = BridgeSource.parse(source)
        val result = if (mime.startsWith("video/")) videoMetadata(parsed) else imageMetadata(parsed)
        BridgeJson.encodeToString(MediaMetadata.serializer(), result)
    }

    private fun imageMetadata(source: BridgeSource): MediaMetadata = source.openPfd().use { pfd ->
        val exif = runCatching { ExifInterface(pfd.fileDescriptor) }.getOrNull()
        val orientation = exif?.getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_UNDEFINED)
            ?.takeIf { it != ExifInterface.ORIENTATION_UNDEFINED }
        var width = exif?.getAttributeInt(ExifInterface.TAG_IMAGE_WIDTH, 0)?.takeIf { it > 0 }
        var height = exif?.getAttributeInt(ExifInterface.TAG_IMAGE_LENGTH, 0)?.takeIf { it > 0 }
        if (width == null || height == null) {
            val size = runCatching { headerSize(source) }.getOrNull()
            width = size?.width
            height = size?.height
        }
        val display = if (width != null && height != null) MediaMath.displaySize(width, height, orientation) else null
        MediaMetadata(
            width = display?.width,
            height = display?.height,
            durationMs = null,
            takenAt = MediaMath.exifDateToIso(
                exif?.getAttribute(ExifInterface.TAG_DATETIME_ORIGINAL),
                exif?.getAttribute(ExifInterface.TAG_OFFSET_TIME_ORIGINAL)
            ),
            orientation = orientation,
            exif = exif?.let(::exifSummary) ?: ExifSummary()
        )
    }

    private fun exifSummary(exif: ExifInterface): ExifSummary {
        val latLong = exif.latLong
        return ExifSummary(
            make = exif.getAttribute(ExifInterface.TAG_MAKE)?.trim(),
            model = exif.getAttribute(ExifInterface.TAG_MODEL)?.trim(),
            lens = exif.getAttribute(ExifInterface.TAG_LENS_MODEL)?.trim(),
            fNumber = exif.getAttributeDouble(ExifInterface.TAG_F_NUMBER, Double.NaN).takeUnless { it.isNaN() },
            exposureTime = exif.getAttributeDouble(ExifInterface.TAG_EXPOSURE_TIME, Double.NaN).takeUnless { it.isNaN() },
            iso = exif.getAttributeInt(ExifInterface.TAG_PHOTOGRAPHIC_SENSITIVITY, 0).takeIf { it > 0 },
            focalLength = exif.getAttributeDouble(ExifInterface.TAG_FOCAL_LENGTH, Double.NaN).takeUnless { it.isNaN() },
            gps = latLong?.let { GpsPoint(it[0], it[1]) }
        )
    }

    private fun videoMetadata(source: BridgeSource): MediaMetadata = source.openPfd().use { pfd ->
        val retriever = MediaMetadataRetriever()
        try {
            retriever.setDataSource(pfd.fileDescriptor)
            val rotation = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_ROTATION)?.toIntOrNull() ?: 0
            val width = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)?.toIntOrNull()
            val height = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)?.toIntOrNull()
            val rotated = rotation == 90 || rotation == 270
            MediaMetadata(
                width = if (rotated) height else width,
                height = if (rotated) width else height,
                durationMs = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull(),
                takenAt = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DATE)?.let(::videoDateToIso),
                orientation = null,
                exif = ExifSummary()
            )
        } finally {
            retriever.release()
        }
    }

    private fun headerSize(source: BridgeSource): ImageSize {
        var size: ImageSize? = null
        try {
            ImageDecoder.decodeDrawable(imageSource(source)) { decoder, info, _ ->
                size = ImageSize(info.size.width, info.size.height)
                throw HeaderOnly()
            }
        } catch (_: HeaderOnly) {
        }
        return size ?: throw BridgeException(BridgeException.UNSUPPORTED, "cannot read image header")
    }

    private class HeaderOnly : RuntimeException()

    private fun decodeImage(source: BridgeSource, maxSide: Int): Bitmap = try {
        ImageDecoder.decodeBitmap(imageSource(source)) { decoder, info, _ ->
            val target = MediaMath.fit(info.size.width, info.size.height, maxSide)
            decoder.setTargetSize(target.width, target.height)
            decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
            decoder.isMutableRequired = false
        }
    } catch (decode: ImageDecoder.DecodeException) {
        throw BridgeException(BridgeException.UNSUPPORTED, "image format not decodable by the system", decode)
    }

    private fun imageSource(source: BridgeSource): ImageDecoder.Source = when (source) {
        is BridgeSource.Path -> ImageDecoder.createSource(source.file)

        is BridgeSource.Descriptor -> ImageDecoder.createSource {
            AssetFileDescriptor(ParcelFileDescriptor.fromFd(source.fd), 0, AssetFileDescriptor.UNKNOWN_LENGTH)
        }
    }

    private fun writeBitmap(bitmap: Bitmap, format: Bitmap.CompressFormat, quality: Int, output: File) {
        output.parentFile?.mkdirs()
        val tmp = File(output.parentFile, ".${output.name}.tmp")
        tmp.outputStream().use { stream ->
            if (!bitmap.compress(format, quality.coerceIn(1, 100), stream)) {
                throw BridgeException(BridgeException.IO, "encode failed")
            }
        }
        if (!tmp.renameTo(output)) throw BridgeException(BridgeException.IO, "cannot write output")
    }

    private fun videoDateToIso(value: String): String? {
        // MediaMetadataRetriever: `yyyyMMddTHHmmss.SSSZ`.
        val match = Regex("^(\\d{4})(\\d{2})(\\d{2})T(\\d{2})(\\d{2})(\\d{2})").find(value) ?: return null
        val (y, mo, d, h, mi, s) = match.destructured
        if (y == "1904" || y == "0000") return null
        return "$y-$mo-${d}T$h:$mi:${s}Z"
    }

    private companion object {
        const val PDF_QUALITY = 85
    }
}
