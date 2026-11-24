package dev.bento.feature.search

import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.files.Destination
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(qualifiers = "es-w411dp-h891dp")
class SearchUiTest {
    @get:Rule
    val compose = createComposeRule()

    private fun content(state: SearchState, actions: SearchActions = SearchActions()) =
        compose.setContent { BentoTheme { SearchContent(state, actions, autoFocus = false) } }

    @Test
    fun idleShowsRecentsAndSuggestions() {
        val log = mutableListOf<String>()
        content(
            SearchState(
                recents = listOf("factura luz"),
                suggestions = SearchSuggestions(years = listOf(2024), folders = listOf(Destination("f", "Trabajo")))
            ),
            SearchActions(
                onRecent = { log += "recent:$it" },
                onRemoveRecent = { log += "remove:$it" },
                onClearRecents = { log += "clear" },
                onKind = { log += "kind:$it" },
                onYear = { log += "year:$it" },
                onFolder = { log += "folder:${it?.id}" }
            )
        )
        compose.onNodeWithText("Búsquedas recientes").assertExists()
        compose.onNodeWithText("factura luz").performClick()
        compose.onNodeWithContentDescription("Quitar «factura luz» de las recientes").performClick()
        compose.onNodeWithText("Borrar historial").performClick()
        compose.onNodeWithText("Hojas de cálculo").performClick()
        compose.onNodeWithText("2024").performClick()
        compose.onNodeWithText("Trabajo").performClick()
        assertEquals(listOf("recent:factura luz", "remove:factura luz", "clear", "kind:Sheets", "year:2024", "folder:f"), log)
    }

    @Test
    fun resultsAreGroupedWithReasons() {
        val opened = mutableListOf<String>()
        content(SearchState(query = "factura", results = SearchFixtures.results), SearchActions(onOpen = { opened += it.id }))
        compose.onNodeWithText("Fotos y videos").assertExists()
        compose.onNodeWithText("Carpetas y álbumes").assertExists()
        compose.onNodeWithText("Texto en la imagen: «factura» · Fecha de la foto").assertExists()
        compose.onNodeWithText("Texto en la página 2: «factura» · Tipo de documento").assertExists()
        compose.onNodeWithText("Nombre · Nombre de la carpeta").assertExists()
        compose.onNodeWithText("Facturas").performClick()
        compose.onNodeWithContentDescription("Foto, IMG_2041.jpg").performClick()
        assertEquals(listOf("f1", "p1"), opened)
    }

    @Test
    fun noResultsOffersRemovingFiltersAndSearchingEverywhere() {
        val log = mutableListOf<String>()
        val scope = Destination("f", "Trabajo")
        content(
            SearchState(query = "factura", scope = scope, filters = SearchFilters(kind = SearchKind.Pdf, folder = scope)),
            SearchActions(onEverywhere = { log += "everywhere" }, onClearFilters = { log += "clear" })
        )
        compose.onNodeWithText("No encontramos «factura»").assertExists()
        compose.onNodeWithText("Buscar en todas las carpetas").performClick()
        compose.onAllNodes(hasText("Quitar filtros"))[0].performScrollTo().performClick()
        assertEquals(listOf("everywhere", "clear"), log)
    }

    @Test
    fun filterChipsOpenTheirSheets() {
        val sheets = mutableListOf<FilterSheet?>()
        content(SearchState(query = "x", results = SearchFixtures.results), SearchActions(onSheet = { sheets += it }))
        compose.onNodeWithText("Tipo").performClick()
        compose.onNodeWithText("Fecha").performClick()
        compose.onAllNodes(hasText("Carpeta"))[0].performClick()
        assertEquals(listOf(FilterSheet.Kind, FilterSheet.Date, FilterSheet.Folder), sheets)
    }

    @Test
    fun activeFilterChipNamesItsFilterIsADropdownAndCanBeRemoved() {
        val kinds = mutableListOf<SearchKind?>()
        content(
            SearchState(query = "x", filters = SearchFilters(kind = SearchKind.Photos), results = SearchFixtures.results),
            SearchActions(onKind = { kinds += it })
        )
        val chip = compose.onNodeWithContentDescription("Tipo: Fotos")
        chip.assert(SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.DropdownList))
        val remove = chip.fetchSemanticsNode().config[SemanticsActions.CustomActions].single { it.label == "Quitar el filtro «Tipo»" }
        compose.runOnIdle { remove.action() }
        assertEquals(listOf<SearchKind?>(null), kinds)
    }

    @Test
    fun originChipFollowsTheChipPatternAndItsSheetPicks() {
        val origins = mutableListOf<OriginFilter?>()
        val sheets = mutableListOf<FilterSheet?>()
        content(
            SearchState(query = "x", filters = SearchFilters(origin = OriginFilter.ThisPhone), results = SearchFixtures.results),
            SearchActions(onOrigin = { origins += it }, onSheet = { sheets += it })
        )
        val chip = compose.onNodeWithContentDescription("Origen: Este teléfono")
        chip.assert(SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.DropdownList))
        chip.performScrollTo().performClick()
        assertEquals(listOf<FilterSheet?>(FilterSheet.Origin), sheets)
        val remove = chip.fetchSemanticsNode().config[SemanticsActions.CustomActions].single { it.label == "Quitar el filtro «Origen»" }
        compose.runOnIdle { remove.action() }
        assertEquals(listOf<OriginFilter?>(null), origins)
    }

    @Test
    fun originSheetPicks() {
        val picked = mutableListOf<OriginFilter?>()
        compose.setContent { BentoTheme { OriginSheetBody(null) { picked += it } } }
        compose.onNodeWithText("Otros dispositivos").performClick()
        compose.onNodeWithText("Cualquiera").performClick()
        assertEquals(listOf(OriginFilter.OtherDevices, null), picked)
    }

    @Test
    fun reasonCodesAndTheSnippetAreShown() {
        content(SearchState(query = "luz", results = SearchFixtures.results))
        compose.onNodeWithText("Texto en la imagen: «luz» · Fecha de la foto").assertExists()
        compose.onNodeWithText("…Total factura: 99 € por la luz…").assertExists()
        val snippet = compose.onNodeWithTag(SNIPPET_TAG).fetchSemanticsNode().config[SemanticsProperties.Text].single()
        val bold = snippet.spanStyles.single()
        assertEquals("factura", snippet.text.substring(bold.start, bold.end))
    }

    @Test
    fun kindSheetPicks() {
        val picked = mutableListOf<SearchKind?>()
        compose.setContent { BentoTheme { KindSheetBody(null) { picked += it } } }
        compose.onNodeWithText("PDF").performClick()
        compose.onNodeWithText("Cualquiera").performClick()
        assertEquals(listOf(SearchKind.Pdf, null), picked)
    }

    @Test
    fun failedSearchRetries() {
        var retried = 0
        content(SearchState(query = "x", failed = true), SearchActions(onRetry = { retried++ }))
        compose.onNodeWithText("Reintentar").performClick()
        assertEquals(1, retried)
    }
}
