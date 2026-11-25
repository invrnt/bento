package dev.bento.feature.viewer

import androidx.exifinterface.media.ExifInterface
import dev.bento.api.AssetPaths
import dev.bento.api.BentoHttp
import dev.bento.api.generated.AssetResponse
import java.io.InputStream
import java.util.Locale
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Reads camera, exposure and GPS from the original's EXIF header. ExifInterface stops at the image data, and closing
 * the response cancels the rest of the download, so only the first kilobytes of `/content` are read (and decrypted).
 */
@Singleton
class ExifReader @Inject constructor(private val http: BentoHttp) {
    suspend fun read(asset: AssetResponse, locale: Locale): ExifSummary? {
        if (asset.mimeType !in SUPPORTED) return null
        return runCatching {
            http.execute("GET", AssetPaths.content(asset.id)) { response -> response.body.byteStream().use { parse(it, locale) } }
        }.getOrNull()
    }

    companion object {
        private val SUPPORTED = setOf("image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif", "image/x-adobe-dng")

        fun parse(stream: InputStream, locale: Locale): ExifSummary {
            val exif = ExifInterface(stream)
            val latLong = exif.latLong
            return ExifSummary(
                camera = ExifSummary.cameraLine(exif.getAttribute(ExifInterface.TAG_MAKE), exif.getAttribute(ExifInterface.TAG_MODEL)),
                lens = exif.getAttribute(ExifInterface.TAG_LENS_MODEL)?.trim()?.ifEmpty { null },
                exposure = ExifSummary.exposureLine(
                    exposureSeconds = exif.getAttributeDouble(ExifInterface.TAG_EXPOSURE_TIME, -1.0).takeIf { it > 0 },
                    fNumber = exif.getAttributeDouble(ExifInterface.TAG_F_NUMBER, -1.0).takeIf { it > 0 },
                    iso = exif.getAttributeInt(ExifInterface.TAG_PHOTOGRAPHIC_SENSITIVITY, -1).takeIf { it > 0 },
                    focalMm = exif.getAttributeDouble(ExifInterface.TAG_FOCAL_LENGTH, -1.0).takeIf { it > 0 },
                    locale = locale
                ),
                latitude = latLong?.getOrNull(0),
                longitude = latLong?.getOrNull(1),
                takenAt = exif.getAttribute(ExifInterface.TAG_DATETIME_ORIGINAL)
            )
        }
    }
}
