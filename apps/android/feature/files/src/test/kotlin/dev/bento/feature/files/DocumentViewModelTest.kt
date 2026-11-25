package dev.bento.feature.files

import android.graphics.Bitmap
import android.graphics.RectF
import dev.bento.api.BentoHttp
import dev.bento.api.EndpointProvider
import dev.bento.data.DriveRepository
import dev.bento.data.Invalidations
import dev.bento.data.UiCache
import dev.bento.engine.EngineState
import dev.bento.engine.WorkerMode
import dev.bento.testing.FakeApiTransport
import dev.bento.testing.MainDispatcherRule
import java.io.File
import java.nio.file.Files
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/** A PDF without Android's renderer: blank pages, matches on pages 2 and 4. */
class FakePdf(override val pageCount: Int = 5, override val searchable: Boolean = true) : PdfSource {
    var closed = false

    override fun aspect(page: Int) = 0.707f

    override suspend fun render(page: Int, widthPx: Int): Bitmap = Bitmap.createBitmap(
        widthPx.coerceAtMost(200),
        283,
        Bitmap.Config.ARGB_8888
    )

    override suspend fun search(query: String): List<PdfMatch> =
        if (query.isBlank()) {
            emptyList()
        } else {
            listOf(
                PdfMatch(1, listOf(RectF(0.1f, 0.2f, 0.5f, 0.24f))),
                PdfMatch(3, listOf(RectF(0.2f, 0.6f, 0.4f, 0.64f)))
            )
        }

    override fun close() {
        closed = true
    }
}

@RunWith(RobolectricTestRunner::class)
class DocumentViewModelTest {
    @get:Rule
    val main = MainDispatcherRule()

    private val server = MockWebServer()
    private val tmp = Files.createTempDirectory("docs").toFile()
    private val preferences = InMemoryFilesPreferences()
    private var online = true
    private val pdf = FakePdf()
    private var opened: File? = null

    @Before
    fun setUp() = server.start()

    @After
    fun tearDown() = server.close()

    private fun TestScope.vm(api: FakeApiTransport): DocumentViewModel {
        val ready = EngineState.Ready(server.port, "t", "k", WorkerMode.FULL)
        val http = BentoHttp(OkHttpClient(), EndpointProvider { ready })
        val endpoints = api.endpoints()
        val cache = UiCache(tmp, "1")
        val repo =
            FilesRepository(endpoints, null, DriveRepository(endpoints, Invalidations(), cache, backgroundScope), Invalidations(), cache)
        return DocumentViewModel(repo, ContentFiles(http, File(tmp, "share")), preferences, { online }) { file, onClose ->
            opened = file
            pdf.also { onClose(file) }
        }
    }

    private fun api(name: String, mime: String, size: Long) = FakeApiTransport().apply {
        on("GET /api/assets/a1") { FilesFixtures.asset("a1", name, mime, size) }
    }

    @Test
    fun textOpensAndMonospaceToggles() = runTest(main.dispatcher) {
        server.enqueue(MockResponse.Builder().body("# Hola\nlínea 2").build())
        val vm = vm(api("notas.md", "text/markdown", 15))
        vm.open("a1")
        awaitUntil { vm.state.value.body is DocumentBody.Text }
        assertEquals(DocumentBody.Text("# Hola\nlínea 2"), vm.state.value.body)
        vm.toggleMonospace()
        assertTrue(vm.state.value.monospace)
    }

    @Test
    fun largeTextIsNotLoaded() = runTest(main.dispatcher) {
        val vm = vm(api("log.txt", "text/plain", ContentFiles.TEXT_LIMIT + 1))
        vm.open("a1")
        settle()
        assertEquals(DocumentBody.TooLarge, vm.state.value.body)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun offlineUnpinnedShowsTheOfflineMessage() = runTest(main.dispatcher) {
        online = false
        val vm = vm(api("a.pdf", "application/pdf", 10))
        vm.open("a1")
        settle()
        assertEquals(DocumentBody.Offline, vm.state.value.body)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun pdfOpensWithSearchSteps() = runTest(main.dispatcher) {
        server.enqueue(MockResponse.Builder().body("%PDF-1.7 fake").build())
        preferences.setPinned("a1", true)
        online = false
        val vm = vm(api("a.pdf", "application/pdf", 13))
        vm.open("a1")
        awaitUntil { vm.state.value.body is DocumentBody.Pdf }
        assertTrue(vm.state.value.body is DocumentBody.Pdf)
        // The temporary plaintext copy lives under cacheDir/share and is removed when the reader closes.
        assertTrue(opened!!.path.contains("share"))
        vm.openSearch(true)
        vm.search("factura")
        settle()
        assertEquals(2, vm.state.value.search.matches.size)
        assertEquals(1, vm.state.value.page)
        vm.step(1)
        assertEquals(3, vm.state.value.page)
        vm.step(1)
        assertEquals(1, vm.state.value.page)
        vm.openSearch(false)
        assertEquals(PdfSearch(), vm.state.value.search)
    }
}
