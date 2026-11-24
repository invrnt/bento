package dev.bento.spike

import android.graphics.Bitmap
import android.graphics.ImageDecoder
import java.io.File
import kotlin.math.max
import kotlin.math.roundToInt

/** Minimal `MediaTools` host bridge (architecture/android-runtime.md §5): one coarse call per file. */
object MediaTools {
    @Volatile @JvmStatic var calls: Int = 0

    /** Decodes `source` with ImageDecoder (EXIF orientation applied), scales to `maxSide`, writes a JPEG. Returns "w,h". */
    @JvmStatic
    fun thumbnail(source: String, output: String, maxSide: Int, quality: Int): String {
        calls += 1
        val decoder = ImageDecoder.createSource(File(source))
        val bitmap = ImageDecoder.decodeBitmap(decoder) { d, info, _ ->
            val w = info.size.width
            val h = info.size.height
            val scale = maxSide.toDouble() / max(w, h)
            if (scale < 1.0) d.setTargetSize((w * scale).roundToInt().coerceAtLeast(1), (h * scale).roundToInt().coerceAtLeast(1))
            d.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
        }
        File(output).parentFile?.mkdirs()
        File(output).outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, quality, it) }
        val result = "${bitmap.width},${bitmap.height}"
        bitmap.recycle()
        return result
    }
}
