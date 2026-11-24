package dev.bento.feature.photos.benchmark

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import androidx.exifinterface.media.ExifInterface
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * Seeds the app's library (real engine, fake cloud) with [target] distinct small JPEGs whose EXIF `DateTimeOriginal`
 * spreads them every 3 hours back from 2026-11-20, so ~10,000 photos cover ~3.4 years of month headers like a real
 * camera roll. Idempotent: it counts the timeline first (month index) and only uploads what is missing.
 */
object LibrarySeeder {
    private val exifDate = DateTimeFormatter.ofPattern("yyyy:MM:dd HH:mm:ss")
    private val start = LocalDateTime.of(2026, 11, 20, 18, 0)

    fun photoCount(endpoint: BentoDevice.Endpoint): Int =
        BentoDevice.call(endpoint, "GET", "/api/photos/timeline/index")["months"]!!.jsonArray.sumOf { it.jsonObject["count"]!!.jsonPrimitive.int }

    fun ensure(endpoint: BentoDevice.Endpoint, target: Int, threads: Int = 6): Int {
        val existing = photoCount(endpoint)
        if (existing >= target) return existing
        val dir = File(InstrumentationRegistry.getInstrumentation().context.cacheDir, "seed").apply { mkdirs() }
        val next = AtomicInteger(existing)
        val pool = Executors.newFixedThreadPool(threads)
        repeat(threads) {
            pool.execute {
                while (true) {
                    val i = next.getAndIncrement()
                    if (i >= target) break
                    BentoDevice.upload(endpoint, "seed_%05d.jpg".format(i), "image/jpeg", jpeg(i, dir))
                }
            }
        }
        pool.shutdown()
        check(pool.awaitTermination(2, TimeUnit.HOURS)) { "seeding timed out" }
        return photoCount(endpoint)
    }

    /** A 96 × 96 JPEG unique to [i] (different bytes → different sha256) with its EXIF capture time. */
    fun jpeg(i: Int, dir: File, takenAt: LocalDateTime = start.minusHours(3L * i)): ByteArray {
        val bitmap = Bitmap.createBitmap(96, 96, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        val hue = (i * 37) % 360
        canvas.drawColor(android.graphics.Color.HSVToColor(floatArrayOf(hue.toFloat(), 0.35f, 0.75f)))
        val paint = Paint().apply { color = android.graphics.Color.HSVToColor(floatArrayOf(((hue + 140) % 360).toFloat(), 0.5f, 0.55f)) }
        canvas.drawRect((i % 7) * 10f, (i % 5) * 12f, 40f + (i % 11) * 4f, 50f + (i % 13) * 3f, paint)
        val file = File(dir, "seed-$i-${Thread.currentThread().id}.jpg")
        file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, 80, it) }
        bitmap.recycle()
        ExifInterface(file).apply {
            val taken = takenAt.format(exifDate)
            setAttribute(ExifInterface.TAG_DATETIME_ORIGINAL, taken)
            // The backend reads only IFD0 today (DateTimeOriginal is in the Exif sub-IFD): IFD0 DateTime is its fallback.
            setAttribute(ExifInterface.TAG_DATETIME, taken)
            setAttribute(ExifInterface.TAG_MAKE, "Bento")
            setAttribute(ExifInterface.TAG_MODEL, "Seeder $i")
            saveAttributes()
        }
        return file.readBytes().also { file.delete() }
    }

    /** Uploads the bundled 6 s H.264 clip once (journey 7: a video streams with seeking) and returns its id. */
    fun ensureVideo(endpoint: BentoDevice.Endpoint): String {
        val context = InstrumentationRegistry.getInstrumentation().context
        val bytes = context.assets.open("sample-video.mp4").use { it.readBytes() }
        return BentoDevice.upload(endpoint, "Video de prueba.mp4", "video/mp4", bytes)["id"]!!.jsonPrimitive.content
    }
}
