package dev.bento.feature.search

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createComposeRule
import dev.bento.api.BentoJson
import dev.bento.api.generated.AlbumResponse
import dev.bento.feature.files.Destination
import dev.bento.feature.files.SheetFrame
import dev.bento.testing.BentoScreenshots
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = BentoScreenshots.QUALIFIERS)
class SearchScreenshotTest {
    @get:Rule
    val compose = createComposeRule()

    private fun shot(name: String, content: @Composable () -> Unit) = BentoScreenshots.capture(compose, "screenshots", name, content)

    private val album = BentoJson.decodeFromString(
        AlbumResponse.serializer(),
        """{"id":"al1","title":"Viaje a Cartagena","asset_ids":[],""" +
            """"created_at":"2026-01-01T00:00:00+00:00","updated_at":"2026-01-01T00:00:00+00:00"}"""
    )
    private val suggestions =
        SearchSuggestions(
            years = listOf(2024, 2023),
            folders = listOf(Destination("f", "Trabajo"), Destination("g", "Facturas")),
            albums = listOf(album)
        )

    @Composable
    private fun Search(state: SearchState) = SearchContent(state, SearchActions(), autoFocus = false)

    @Test fun idle() = shot("idle") {
        Search(SearchState(recents = listOf("factura de luz", "pasaporte", "contrato arriendo"), suggestions = suggestions))
    }

    @Test fun idleFirstTime() = shot("idle-empty-history") { Search(SearchState(suggestions = SearchSuggestions())) }

    @Test fun results() = shot("results") {
        Search(SearchState(query = "factura", results = SearchFixtures.results, indexing = true, nextCursor = "c"))
    }

    @Test fun filtered() = shot("results-filtered") {
        Search(
            SearchState(
                query = "factura",
                results = SearchFixtures.results.drop(4),
                filters = SearchFilters(kind = SearchKind.Documents, date = DateFilter.Year(2024))
            )
        )
    }

    @Test fun loading() = shot("searching") { Search(SearchState(query = "factura", loading = true)) }

    @Test fun noResults() = shot("no-results") { Search(SearchState(query = "factura")) }

    @Test fun noResultsScoped() = shot("no-results-scoped") {
        val scope = Destination("f", "Trabajo")
        Search(SearchState(query = "factura", scope = scope, filters = SearchFilters(folder = scope)))
    }

    @Test fun failed() = shot("failed") { Search(SearchState(query = "factura", failed = true)) }

    @Test fun kindSheet() = shot("sheet-kind") {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) { SheetFrame { KindSheetBody(SearchKind.Pdf) {} } }
    }

    @Test fun originSheet() = shot("sheet-origin") {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) { SheetFrame { OriginSheetBody(OriginFilter.Telegram) {} } }
    }

    @Test fun originFiltered() = shot("results-origin") {
        Search(
            SearchState(
                query = "luz",
                results = SearchFixtures.results.drop(2).take(1),
                filters = SearchFilters(origin = OriginFilter.ThisPhone)
            )
        )
    }

    @Test fun dateSheet() = shot("sheet-date") {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) {
            SheetFrame {
                DateSheetBody(
                    SearchState(suggestions = suggestions, filters = SearchFilters(date = DateFilter.Year(2024))),
                    SearchActions(),
                    showPicker = false
                )
            }
        }
    }
}
