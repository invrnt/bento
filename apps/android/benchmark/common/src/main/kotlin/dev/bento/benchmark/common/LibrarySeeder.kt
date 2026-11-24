package dev.bento.benchmark.common

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
 * Seeds the app's library (real engine, fake cloud). Photos: [photos] distinct small JPEGs whose EXIF
 * `DateTimeOriginal` spreads them every 3 hours back from 2026-11-20 (~3.4 years of month headers for 10,000).
 * Archivos: the folder [FOLDER] with [FILES] text files named `factura-NNNN.txt` (Buscar types "factura").
 * Idempotent: it counts what exists first and only uploads what is missing.
 */
object LibrarySeeder {
    const val FOLDER = "Benchmark"
    const val FILE_PREFIX = "factura-"
    const val FILES = 300

    private val exifDate = DateTimeFormatter.ofPattern("yyyy:MM:dd HH:mm:ss")
    private val start = LocalDateTime.of(2026, 11, 20, 18, 0)

    /** Photos from the `bento.seed` instrumentation argument (default 10,000, the §13 benchmark library). */
    val photos: Int get() = BentoDevice.argument("bento.seed", "10000").toInt()

    fun photoCount(endpoint: BentoDevice.Endpoint): Int =
        BentoDevice.call(endpoint, "GET", "/api/photos/timeline/index")["months"]!!.jsonArray.sumOf { it.jsonObject["count"]!!.jsonPrimitive.int }

    /** Everything the journeys need; returns the photo count. */
    fun ensureLibrary(endpoint: BentoDevice.Endpoint, photoTarget: Int = photos): Int {
        val started = System.currentTimeMillis()
        val count = ensurePhotos(endpoint, photoTarget)
        ensureFiles(endpoint)
        android.util.Log.i(TAG, "library: $count photos, $FILES files (${(System.currentTimeMillis() - started) / 1000} s)")
        return count
    }

    fun ensurePhotos(endpoint: BentoDevice.Endpoint, target: Int, threads: Int = 6): Int {
        val existing = photoCount(endpoint)
        if (existing >= target) return existing
        val dir = File(InstrumentationRegistry.getInstrumentation().context.cacheDir, "seed").apply { mkdirs() }
        val next = AtomicInteger(existing)
        val failed = AtomicInteger(0)
        val pool = Executors.newFixedThreadPool(threads)
        repeat(threads) {
            pool.execute {
                while (true) {
                    val i = next.getAndIncrement()
                    if (i >= target) break
                    // Concurrent uploads occasionally get a 500 (SQLite contention): retry with backoff, and never let
                    // a pool thread die (an uncaught exception kills the instrumentation process).
                    val ok = (1..4).any { attempt ->
                        runCatching { BentoDevice.upload(endpoint, "seed_%05d.jpg".format(i), "image/jpeg", jpeg(i, dir)) }
                            .onFailure { Thread.sleep(250L * attempt) }
                            .isSuccess
                    }
                    if (!ok) failed.incrementAndGet()
                }
            }
        }
        pool.shutdown()
        check(pool.awaitTermination(2, TimeUnit.HOURS)) { "seeding timed out" }
        val count = photoCount(endpoint)
        android.util.Log.i(TAG, "seeded to $count photos, ${failed.get()} uploads failed after retries")
        check(failed.get() <= target / 100) { "${failed.get()} uploads failed" }
        // Let thumbnail jobs catch up so scrolling measures real tiles, not placeholders.
        Thread.sleep(5_000)
        return count
    }

    fun ensureFiles(endpoint: BentoDevice.Endpoint) {
        val root = BentoDevice.call(endpoint, "GET", "/api/drive/items?limit=200")["items"]!!.jsonArray.map { it.jsonObject }
        val folderId = root.firstOrNull { it["type"]?.jsonPrimitive?.content == "folder" && it["name"]?.jsonPrimitive?.content == FOLDER }
            ?.get("id")?.jsonPrimitive?.content
            ?: BentoDevice.call(endpoint, "POST", "/api/drive/folders", "{\"name\":\"$FOLDER\"}")["id"]!!.jsonPrimitive.content
        val existing = countItems(endpoint, folderId)
        for (i in existing until FILES) {
            val name = "$FILE_PREFIX%04d.txt".format(i)
            val text = "Factura $i\nCliente Bento\nTotal ${(i * 37) % 1000},00\n"
            BentoDevice.upload(endpoint, name, "text/plain", text.toByteArray(), mode = "drive", folderId = folderId)
        }
    }

    private fun countItems(endpoint: BentoDevice.Endpoint, folderId: String): Int {
        var count = 0
        var cursor: String? = null
        do {
            val page = BentoDevice.call(endpoint, "GET", "/api/drive/items?folder_id=$folderId&limit=200" + (cursor?.let { "&cursor=$it" } ?: ""))
            count += page["items"]!!.jsonArray.size
            cursor = page["next_cursor"]?.takeIf { it is kotlinx.serialization.json.JsonPrimitive && it.isString }?.jsonPrimitive?.content
        } while (cursor != null)
        return count
    }

    /** A 96 × 96 JPEG unique to [i] (different bytes → different sha256) with its EXIF capture time. */
    fun jpeg(i: Int, dir: File, takenAt: LocalDateTime = start.minusHours(3L * i)): ByteArray {
        val bitmap = Bitmap.createBitmap(96, 96, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        val hue = (i * 37) % 360
        canvas.drawColor(android.graphics.Color.HSVToColor(floatArrayOf(hue.toFloat(), 0.35f, 0.75f)))
        val paint = Paint().apply { color = android.graphics.Color.HSVToColor(floatArrayOf(((hue + 140) % 360).toFloat(), 0.5f, 0.55f)) }
        canvas.drawRect((i % 7) * 10f, (i % 5) * 12f, 40f + (i % 11) * 4f, 50f + (i % 13) * 3f, paint)
        val file = File(dir, "seed-$i-${android.os.Process.myTid()}.jpg")
        file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, 80, it) }
        bitmap.recycle()
        ExifInterface(file).apply {
            val taken = takenAt.format(exifDate)
            setAttribute(ExifInterface.TAG_DATETIME_ORIGINAL, taken)
            setAttribute(ExifInterface.TAG_DATETIME, taken)
            setAttribute(ExifInterface.TAG_MAKE, "Bento")
            setAttribute(ExifInterface.TAG_MODEL, "Seeder $i")
            saveAttributes()
        }
        return file.readBytes().also { file.delete() }
    }

    /** Uploads [bytes] once (journey 7: a video streams with seeking) and returns its id. */
    fun ensureVideo(endpoint: BentoDevice.Endpoint, bytes: ByteArray): String =
        BentoDevice.upload(endpoint, "Video de prueba.mp4", "video/mp4", bytes)["id"]!!.jsonPrimitive.content

    private const val TAG = "BentoBenchmark"
}
