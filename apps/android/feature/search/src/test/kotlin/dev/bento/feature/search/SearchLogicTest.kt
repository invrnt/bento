package dev.bento.feature.search

import dev.bento.feature.search.SearchFixtures.d
import dev.bento.feature.search.SearchFixtures.hit
import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SearchLogicTest {
    @Test
    fun reasonsFromTheBackendExplanation() {
        assertEquals(listOf(MatchReason.ImageText, MatchReason.DocumentType), MatchReasons.parse("Coincidio por OCR y tipo de documento"))
        assertEquals(
            listOf(MatchReason.Name, MatchReason.Folder),
            MatchReasons.parse("Coincidió por nombre de archivo y nombre de carpeta")
        )
        assertEquals(listOf(MatchReason.Generic), MatchReasons.parse("Coincidio con la busqueda"))
        // Search by meaning is never shown on Android.
        assertEquals(listOf(MatchReason.Generic), MatchReasons.parse("Coincidio por busqueda semantica"))
    }

    @Test
    fun highlightsIgnoreCaseAndAccents() {
        assertEquals(listOf(0..6), highlights("Factura de luz.pdf", "factura"))
        assertEquals(listOf(0..3, 12..15), highlights("Café con el cafecito", "cafe"))
        assertEquals(listOf(4..10), highlights("Mis Canción.mp3", "cancion"))
        assertEquals(emptyList<IntRange>(), highlights("Factura", "x"))
        assertEquals(listOf(0..6, 11..13), highlights("Factura de luz", "luz factura"))
    }

    @Test
    fun groupsAndPages() {
        val groups = SearchFixtures.results.groupBy { groupOf(it) }.mapValues { (_, v) -> v.map { it.id } }
        assertEquals(listOf("p1", "p2"), groups[ResultGroup.Photos])
        assertEquals(listOf("f1"), groups[ResultGroup.Folders])
        assertEquals(listOf("o1"), groups[ResultGroup.Files])
        assertEquals(listOf("d1", "d2"), groups[ResultGroup.Documents])
        assertEquals(2, pageOf(SearchFixtures.results.first { it.id == "d1" }))
        assertEquals(null, pageOf(SearchFixtures.results.first { it.id == "o1" }))
    }

    @Test
    fun kindsNarrowDocumentsByExtension() {
        val pdf = d(hit("x", "document", "Contrato.PDF", "r"))
        val sheet = d(hit("y", "document", "Gastos.xlsx", "r"))
        assertTrue(SearchKind.Pdf.accepts(pdf))
        assertFalse(SearchKind.Pdf.accepts(sheet))
        assertTrue(SearchKind.Sheets.accepts(sheet))
        assertTrue(SearchKind.Documents.accepts(pdf))
    }

    @Test
    fun dateFilters() {
        val today = LocalDate.of(2026, 11, 24)
        assertEquals(LocalDate.of(2026, 11, 1) to LocalDate.of(2026, 11, 30), DateFilter.ThisMonth(today).let { it.from to it.to })
        assertEquals(LocalDate.of(2025, 1, 1) to LocalDate.of(2025, 12, 31), DateFilter.LastYear(today).let { it.from to it.to })
        assertEquals(
            listOf(2024, 2023, 2021),
            detectedYears(listOf("2026-11", "2025-03", "2024-01", "2024-02", "2023-12", "2021-05", "2019-01"), today)
        )
    }

    @Test
    fun recentsAreLocalDedupedAndBounded() {
        val recents = RecentSearches()
        recents.add("factura")
        recents.add(" Factura ")
        recents.add("x")
        repeat(20) { recents.add("q$it") }
        assertEquals(RecentSearches.MAX, recents.items.value.size)
        assertEquals("q19", recents.items.value.first())
        recents.remove("q19")
        assertEquals("q18", recents.items.value.first())
        recents.clear()
        assertTrue(recents.items.value.isEmpty())
    }
}
