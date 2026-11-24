package dev.bento.feature.search

import dev.bento.data.DriveRepository
import dev.bento.data.Invalidations
import dev.bento.data.UiCache
import dev.bento.feature.files.Destination
import dev.bento.feature.files.FilesRepository
import dev.bento.feature.files.InMemoryFilesPreferences
import dev.bento.testing.FakeApiTransport
import dev.bento.testing.MainDispatcherRule
import java.nio.file.Files
import java.time.LocalDate
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class SearchViewModelTest {
    @get:Rule
    val main = MainDispatcherRule()

    private val tmp = Files.createTempDirectory("search").toFile()
    private val recents = RecentSearches()
    private val preferences = InMemoryFilesPreferences(recent = listOf(Destination("f_work", "Trabajo"), Destination(null, "Archivos")))

    private val api = FakeApiTransport().apply {
        on("GET /api/photos/timeline/index") {
            """{"months":[{"month":"2026-11","count":3,"first_cursor":"c0"},{"month":"2024-02","count":3,"first_cursor":"c"}]}"""
        }
        on("GET /api/photos/albums") { """{"items":[],"next_cursor":null}""" }
        on("GET /api/search") { call ->
            when (call.query["q"]) {
                "nada" -> SearchFixtures.page()

                else -> SearchFixtures.page(
                    SearchFixtures.hit("d1", "document", "Factura.pdf", "Coincidio por OCR"),
                    SearchFixtures.hit("d2", "document", "Factura.xlsx", "Coincidio por nombre de archivo", state = "ocr_pending"),
                    next = "c2"
                )
            }
        }
    }

    private fun TestScope.vm(): SearchViewModel {
        val endpoints = api.endpoints()
        val cache = UiCache(tmp, "1")
        val files =
            FilesRepository(endpoints, null, DriveRepository(endpoints, Invalidations(), cache, backgroundScope), Invalidations(), cache)
        return SearchViewModel(endpoints, recents, files, preferences).also {
            it.today = { LocalDate.of(2026, 11, 24) }
        }
    }

    private fun TestScope.settle(ms: Long = 1_000) {
        testScheduler.advanceTimeBy(ms)
        testScheduler.runCurrent()
    }

    @Test
    fun debouncesTypingAndGroups() = runTest(main.dispatcher) {
        val vm = vm()
        vm.start("", null)
        settle()
        assertEquals(listOf(2024), vm.state.value.suggestions.years)
        assertEquals(listOf("Trabajo"), vm.state.value.suggestions.folders.map { it.name })
        vm.setQuery("f")
        settle(50)
        vm.setQuery("fa")
        settle(50)
        vm.setQuery("factura")
        settle(100)
        assertEquals(0, api.count("GET /api/search"))
        settle(60)
        assertEquals(1, api.count("GET /api/search"))
        assertEquals("factura", api.calls.last().query["q"])
        assertEquals(2, vm.state.value.results.size)
        assertTrue(vm.state.value.indexing)
    }

    @Test
    fun filtersMapToQueryParameters() = runTest(main.dispatcher) {
        val vm = vm()
        vm.start("factura", null)
        settle()
        vm.setKind(SearchKind.Pdf)
        settle()
        vm.thisMonth()
        settle()
        vm.setFolder(Destination("f_work", "Trabajo"))
        settle()
        val query = api.calls.last { it.path == "/api/search" }.query
        assertEquals("document", query["type"])
        assertEquals("2026-11-01", query["date_from"])
        assertEquals("2026-11-30", query["date_to"])
        assertEquals("f_work", query["folder_id"])
        // PDF narrows the `document` hits to .pdf names.
        assertEquals(listOf("d1"), vm.state.value.results.map { it.id })
        vm.clearFilters()
        settle()
        assertTrue(api.calls.last { it.path == "/api/search" }.query.keys.none { it in setOf("type", "date_from", "folder_id") })
    }

    @Test
    fun scopedNoResultsCanSearchEverywhere() = runTest(main.dispatcher) {
        val vm = vm()
        vm.start("nada", Destination("f_work", "Trabajo"))
        settle()
        assertTrue(vm.state.value.noResults)
        assertEquals("f_work", api.calls.last { it.path == "/api/search" }.query["folder_id"])
        vm.searchEverywhere()
        settle()
        assertEquals(null, vm.state.value.scope)
        assertEquals(null, api.calls.last { it.path == "/api/search" }.query["folder_id"])
    }

    @Test
    fun recentsAndOpening() = runTest(main.dispatcher) {
        api.on("GET /api/assets/d1") {
            """{"id":"d1","filename":"Factura.pdf","mime_type":"application/pdf","size_bytes":1,"folder_id":null,""" +
                """"favorite":false,"kind":"pdf","mode":"vault","processing_state":"indexed","sha256":"x",""" +
                """"created_at":"2026-11-01T00:00:00+00:00","updated_at":"2026-11-01T00:00:00+00:00"}"""
        }
        val vm = vm()
        val effects = mutableListOf<SearchEffect>()
        backgroundScope.launch { vm.effect.collect { effects += it } }
        vm.start("", null)
        vm.setQuery("factura")
        vm.submit()
        settle()
        assertEquals(listOf("factura"), recents.items.value)
        vm.open(vm.state.value.results.first())
        vm.open(SearchFixtures.d(SearchFixtures.hit("f1", "folder", "Facturas", "r", assetId = null)))
        vm.open(SearchFixtures.d(SearchFixtures.hit("p1", "photo", "a.jpg", "r")))
        settle()
        assertEquals(
            listOf(SearchEffect.OpenFolder("f1"), SearchEffect.OpenViewer("p1"), SearchEffect.OpenDocument("d1")).toSet(),
            effects.toSet()
        )
        vm.pickRecent("factura")
        settle()
        assertEquals("factura", vm.state.value.query)
    }

    @Test
    fun loadMoreAppendsWithoutDuplicates() = runTest(main.dispatcher) {
        val vm = vm()
        vm.start("factura", null)
        settle()
        vm.loadMore()
        settle()
        assertEquals("c2", api.calls.last().query["cursor"])
        assertEquals(2, vm.state.value.results.size)
    }

    @Test
    fun failureShowsRetry() = runTest(main.dispatcher) {
        api.fail("GET /api/search", 503, "unavailable")
        val vm = vm()
        vm.start("factura", null)
        settle()
        assertTrue(vm.state.value.failed)
    }
}
