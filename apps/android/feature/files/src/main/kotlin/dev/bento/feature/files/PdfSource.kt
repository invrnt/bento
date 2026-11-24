package dev.bento.feature.files

import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.RectF
import android.graphics.pdf.PdfRenderer
import android.os.Build
import android.os.ParcelFileDescriptor
import androidx.annotation.ChecksSdkIntAtLeast
import androidx.annotation.RequiresApi
import androidx.core.graphics.createBitmap
import java.io.Closeable
import java.io.File
import java.util.concurrent.Executors
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/** A match of the in-document search: page index and its bounds as fractions of the page (0..1). */
data class PdfMatch(val page: Int, val bounds: List<RectF>)

/** What the reader needs from a PDF (Android's [PdfRenderer] on the device, a fake in tests). */
interface PdfSource : Closeable {
    val pageCount: Int

    /** Page aspect (width / height). */
    fun aspect(page: Int): Float

    suspend fun render(page: Int, widthPx: Int): Bitmap

    /** True when the document has a text layer the phone can search (PdfRenderer text APIs). */
    val searchable: Boolean

    suspend fun search(query: String): List<PdfMatch>
}

/**
 * [PdfRenderer] over a temporary plaintext copy (deleted on [close]). Rendering is serialized on one thread (the
 * renderer is not thread-safe). Text search uses `Page.searchText` (Android 15) when available.
 */
class AndroidPdfSource(private val file: File, private val onClose: (File) -> Unit) : PdfSource {
    private val descriptor = ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
    private val renderer = PdfRenderer(descriptor)
    private val executor = Executors.newSingleThreadExecutor { Thread(it, "bento-pdf") }
    private val dispatcher = executor.asCoroutineDispatcher()
    private val lock = Mutex()
    private val aspects = HashMap<Int, Float>()

    override val pageCount: Int = renderer.pageCount

    override val searchable: Boolean = textApis()

    override fun aspect(page: Int): Float = synchronized(aspects) {
        aspects.getOrPut(page) { renderer.openPage(page).use { it.width.toFloat() / it.height.coerceAtLeast(1) } }
    }

    override suspend fun render(page: Int, widthPx: Int): Bitmap = withContext(dispatcher) {
        lock.withLock {
            renderer.openPage(page).use { pdfPage ->
                val width = widthPx.coerceIn(MIN_WIDTH, MAX_WIDTH)
                val height = (width * pdfPage.height.toFloat() / pdfPage.width.coerceAtLeast(1)).toInt().coerceAtLeast(1)
                createBitmap(width, height).also { bitmap ->
                    bitmap.eraseColor(Color.WHITE)
                    pdfPage.render(bitmap, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                }
            }
        }
    }

    override suspend fun search(query: String): List<PdfMatch> {
        if (!searchable || query.isBlank()) return emptyList()
        return withContext(dispatcher) { lock.withLock { searchAll(query) } }
    }

    @RequiresApi(Build.VERSION_CODES.VANILLA_ICE_CREAM)
    private fun searchAllWithText(query: String): List<PdfMatch> = (0 until pageCount).mapNotNull { index ->
        renderer.openPage(index).use { page ->
            val width = page.width.toFloat().coerceAtLeast(1f)
            val height = page.height.toFloat().coerceAtLeast(1f)
            val bounds = page.searchText(query).flatMap { match -> match.bounds }.map { rect ->
                RectF(rect.left / width, rect.top / height, rect.right / width, rect.bottom / height)
            }
            bounds.takeIf { it.isNotEmpty() }?.let { PdfMatch(index, it) }
        }
    }

    private fun searchAll(query: String): List<PdfMatch> =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.VANILLA_ICE_CREAM) {
            searchAllWithText(query)
        } else {
            emptyList()
        }

    override fun close() {
        runCatching { renderer.close() }
        runCatching { descriptor.close() }
        executor.shutdown()
        onClose(file)
    }

    private companion object {
        const val MIN_WIDTH = 64
        const val MAX_WIDTH = 2_400

        /** `Page.searchText` ships with Android 15. */
        @ChecksSdkIntAtLeast(api = Build.VERSION_CODES.VANILLA_ICE_CREAM)
        fun textApis(): Boolean = Build.VERSION.SDK_INT >= Build.VERSION_CODES.VANILLA_ICE_CREAM
    }
}
