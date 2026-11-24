package dev.bento.feature.files

import androidx.test.core.app.ApplicationProvider
import java.time.LocalDateTime
import java.util.Locale
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(qualifiers = "es")
class FilesLogicTest {
    @Test
    fun displayNamesDropPathsControlCharsAndReservedStems() {
        assertEquals("passwd", DisplayNames.file("../../etc/passwd"))
        assertEquals("evil.txt", DisplayNames.file("..\\..\\Windows\\evil.txt"))
        assertEquals("factura.pdf", DisplayNames.file("fac\u0000tu‮ra​.pdf"))
        assertEquals("archivo", DisplayNames.file("..."))
        assertEquals("archivo", DisplayNames.file("   "))
        assertEquals("archivo", DisplayNames.file(null))
        assertEquals("_CON.txt", DisplayNames.file("CON.txt"))
        assertEquals("oculto", DisplayNames.file(".oculto."))
        val long = DisplayNames.file("a".repeat(400) + ".pdf")
        assertEquals(DisplayNames.MAX_LENGTH, long.length)
        assertTrue(long.endsWith(".pdf"))
        // NFC: a decomposed "é" becomes one code point.
        assertEquals("Café.txt", DisplayNames.file("Café.txt"))
    }

    @Test
    fun folderSegmentsNeverAddLevels() {
        assertEquals("a_b", DisplayNames.folder("a/b"))
        assertEquals("_x", DisplayNames.folder("../x"))
        assertEquals("carpeta", DisplayNames.folder(".."))
        assertEquals("Trabajo", DisplayNames.folder("  Trabajo \u0007"))
    }

    @Test
    fun scanAndNoteNames() {
        assertEquals("Escaneo 2026-11-24 10.41.pdf", DisplayNames.scan("Escaneo", LocalDateTime.of(2026, 11, 24, 10, 41)))
        assertEquals("Lista de compras.txt", DisplayNames.note("  Lista de compras\nleche\npan", "Nota"))
        assertEquals("example.com path.txt", DisplayNames.note("https://example.com/path", "Nota"))
        assertEquals("Nota.txt", DisplayNames.note("\n\n  ", "Nota"))
        assertTrue(DisplayNames.note("x".repeat(500), "Nota").length <= 64)
    }

    @Test
    fun sortKeepsFoldersFirstForEveryField() {
        val items = FilesFixtures.sample
        for (field in SortField.entries) {
            for (descending in listOf(false, true)) {
                val sorted = FolderSort(field, descending).apply(items, Locale("es"))
                val firstFile = sorted.indexOfFirst { it.folder == null }
                assertTrue(sorted.drop(firstFile).all { it.folder == null })
            }
        }
        val byName = FolderSort().apply(items, Locale("es")).map { it.name }
        assertEquals(listOf("Trabajo", "Viajes 2024", "Copia del proyecto.zip", "Declaración de renta 2025.pdf"), byName.take(4))
        val bySize = FolderSort(SortField.Size, descending = true).apply(items).filter { it.folder == null }.map { it.id }
        assertEquals("a_zip", bySize.first())
        assertEquals("a_notes", bySize.last())
        val byModified = FolderSort(SortField.Modified).apply(items).filter { it.folder != null }.map { it.id }
        assertEquals(listOf("f_trips", "f_work"), byModified)
    }

    @Test
    fun kindsAndOpeners() {
        assertEquals(OpenKind.Pdf, FileKinds.openKind("application/octet-stream", "x.PDF"))
        assertEquals(OpenKind.Text, FileKinds.openKind(null, "build.gradle.kts"))
        assertEquals(OpenKind.Audio, FileKinds.openKind("audio/mp4", "a.m4a"))
        assertEquals(OpenKind.Other, FileKinds.openKind("application/zip", "a.zip"))
        assertEquals(dev.bento.designsystem.component.FileKind.Sheet, FileKinds.fileKind(null, "a.xlsx"))
        assertEquals(dev.bento.designsystem.component.FileKind.Archive, FileKinds.fileKind("application/zip", "a.zip"))
    }

    @Test
    fun sizesUseLocaleDigits() {
        val resources = ApplicationProvider.getApplicationContext<android.content.Context>().resources
        assertEquals("1,5 MB", Sizes.format(resources, 1_572_864, Locale("es")))
        assertEquals("812 B", Sizes.format(resources, 812, Locale("es")))
        assertEquals("774 MB", Sizes.format(resources, 812_000_000, Locale("es")))
        assertEquals("0 B", Sizes.format(resources, -4, Locale("es")))
    }

    @Test
    fun badgesAreHonest() {
        val sample = FilesFixtures.sample.associateBy { it.id }
        assertEquals(listOf(ItemBadge.LocalOnly), badgesOf(sample.getValue("a_notes"), emptySet()))
        assertEquals(listOf(ItemBadge.Offline), badgesOf(sample.getValue("a_tax"), setOf("a_tax")))
        assertEquals(listOf(ItemBadge.Failed), badgesOf(sample.getValue("a_zip"), emptySet()))
        assertEquals(emptyList<ItemBadge>(), badgesOf(sample.getValue("f_work"), setOf("f_work")))
    }

    @Test
    fun treeFlattensExpandedFolders() {
        val a = FilesFixtures.d(FilesFixtures.folder("a", "A"))
        val b = FilesFixtures.d(FilesFixtures.folder("b", "B", "a"))
        val c = FilesFixtures.d(FilesFixtures.folder("c", "C"))
        val tree = mapOf(null to listOf(a, c), "a" to listOf(b))
        assertEquals(listOf("a" to 0, "c" to 0), flattenTree(tree, emptySet()).map { it.first.id to it.second })
        assertEquals(listOf("a" to 0, "b" to 1, "c" to 0), flattenTree(tree, setOf("a")).map { it.first.id to it.second })
    }

    @Test
    fun shareMimeOfMixedFiles() {
        assertEquals("image/jpeg", commonMime(listOf("image/jpeg", "image/jpeg")))
        assertEquals("image/*", commonMime(listOf("image/jpeg", "image/png")))
        assertEquals("*/*", commonMime(listOf("image/jpeg", "application/pdf")))
    }

    @Test
    fun clockFormatsDurations() {
        assertEquals("0:05", clock(5_400))
        assertEquals("12:00", clock(720_000))
        assertEquals("1:02:03", clock(3_723_000))
    }

    @Test
    fun preferencesRememberSortPerFolderAndRecents() {
        val prefs = InMemoryFilesPreferences()
        prefs.setSort("f1", FolderSort(SortField.Size, true))
        assertEquals(FolderSort(SortField.Size, true), prefs.sort("f1"))
        assertEquals(FolderSort(), prefs.sort("f2"))
        assertEquals(FolderSort(), prefs.sort(null))
        repeat(10) { prefs.rememberDestination(Destination("f$it", "F$it")) }
        prefs.rememberDestination(Destination("f3", "F3"))
        assertEquals(FilesPreferences.MAX_RECENT, prefs.recentDestinations.value.size)
        assertEquals("f3", prefs.recentDestinations.value.first().id)
        assertEquals(1, prefs.recentDestinations.value.count { it.id == "f3" })
    }

    @Test
    fun sharedPreferencesSurviveRestart() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val first = SharedFilesPreferences.create(context)
        first.setSort("f1", FolderSort(SortField.Type))
        first.setLayout(FilesLayout.Grid)
        first.setPinned("a1", true)
        first.skipDisclosure(Disclosure.OpenWith)
        first.rememberDestination(Destination("f1", "Trabajo"))
        val second = SharedFilesPreferences.create(context)
        assertEquals(FolderSort(SortField.Type), second.sort("f1"))
        assertEquals(FilesLayout.Grid, second.layout.value)
        assertEquals(setOf("a1"), second.pinned.value)
        assertTrue(second.skipsDisclosure(Disclosure.OpenWith))
        assertEquals(listOf(Destination("f1", "Trabajo")), second.recentDestinations.value)
    }
}
