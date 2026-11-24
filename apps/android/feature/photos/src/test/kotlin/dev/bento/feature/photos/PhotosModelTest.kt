package dev.bento.feature.photos

import dev.bento.data.MonthIndexEntry
import dev.bento.data.TimelineLayout
import java.util.Locale
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

class SelectionStateTest {
    private val cells = ListMediaCells(cellsOf(MediaSamples.library))
    private fun mediaIndex(id: String) = (0 until cells.count).first { (cells.peek(it) as? GridCell.Media)?.asset?.id == id }

    @Test
    fun `long-press then drag selects the range and shrinks back when the finger returns`() {
        val selection = SelectionState()
        assertTrue(selection.beginDrag(mediaIndex("p1"), cells))
        assertEquals(setOf("p1"), selection.selected.keys)
        selection.dragTo(mediaIndex("p5"), cells)
        assertEquals((1..5).map { "p$it" }.toSet(), selection.selected.keys)
        // crossing a day header keeps selecting photos only
        selection.dragTo(mediaIndex("p12"), cells)
        assertEquals(12, selection.count)
        selection.dragTo(mediaIndex("p3"), cells)
        assertEquals(setOf("p1", "p2", "p3"), selection.selected.keys)
        selection.endDrag()
        assertFalse(selection.dragging)
    }

    @Test
    fun `a drag that starts on a selected photo deselects the range and keeps the rest`() {
        val selection = SelectionState()
        selection.set(MediaSamples.library.take(8), true)
        selection.beginDrag(mediaIndex("p2"), cells)
        selection.dragTo(mediaIndex("p4"), cells)
        assertEquals(setOf("p1", "p5", "p6", "p7", "p8"), selection.selected.keys)
    }

    @Test
    fun `dragging upwards works and headers never start a drag`() {
        val selection = SelectionState()
        assertFalse("a month header is not selectable", selection.beginDrag(0, cells))
        selection.beginDrag(mediaIndex("p9"), cells)
        selection.dragTo(mediaIndex("p7"), cells)
        assertEquals(setOf("p7", "p8", "p9"), selection.selected.keys)
    }

    @Test
    fun `toggle, refresh and clear`() {
        val selection = SelectionState()
        val asset = MediaSamples.library.first()
        selection.toggle(asset)
        assertTrue(selection.active)
        selection.refresh(asset.copy(favorite = true))
        assertTrue(selection.selected.getValue(asset.id).favorite)
        selection.toggle(asset)
        assertFalse(selection.active)
        selection.set(MediaSamples.library, true)
        selection.clear()
        assertEquals(0, selection.count)
    }
}

class GridModelTest {
    @Test
    fun `static cells interleave month and day headers newest first`() {
        val cells = cellsOf(MediaSamples.library)
        assertEquals(GridCell.Month("2024-03"), cells[0])
        assertEquals(GridCell.Day("2024-03-14"), cells[1])
        assertEquals(2, cells.count { it is GridCell.Month })
        assertEquals(5, cells.count { it is GridCell.Day })
        assertEquals(MediaSamples.library.size, cells.count { it is GridCell.Media })
        val month = cellsOf(MediaSamples.library, dayHeaders = false)
        assertTrue("the month view has no day headers", month.none { it is GridCell.Day })
    }

    @Test
    fun `position map is exact around a loaded block between placeholders`() {
        // 100 placeholders, then [Month, Day, p0, p1, Day, p2], then 50 placeholders.
        val loaded = listOf(
            GridCell.Month("2024-03"),
            GridCell.Day("2024-03-14"),
            GridCell.Media(MediaSamples.asset("x0", "2024-03-14"), "2024-03-14"),
            GridCell.Media(MediaSamples.asset("x1", "2024-03-14"), "2024-03-14"),
            GridCell.Day("2024-03-12"),
            GridCell.Media(MediaSamples.asset("x2", "2024-03-12"), "2024-03-12")
        )
        val map = PositionMap(100, loaded, 50)
        assertEquals(153, map.totalPhotos)
        assertEquals(156, map.gridCount)
        assertEquals(42, map.photoAt(42))
        assertEquals(42, map.indexOf(42))
        assertEquals("header maps to the next photo", 100, map.photoAt(100))
        assertEquals(102, map.indexOf(100))
        assertEquals(103, map.indexOf(101))
        assertEquals(105, map.indexOf(102))
        assertEquals(103, map.photoAt(106))
        assertEquals(106, map.indexOf(103))
        assertTrue(map.isLoaded(101))
        assertFalse(map.isLoaded(99))
        assertFalse(map.isLoaded(103))
    }

    @Test
    fun `densities give 2-3-5-8 columns on a phone and more on wide windows`() {
        assertEquals(listOf(2, 3, 5, 8), GridDensity.entries.map { it.columns(411f) })
        assertEquals(7, GridDensity.Comfortable.columns(840f))
        assertEquals(GridDensity.Large, GridDensity.Comfortable.larger())
        assertEquals(GridDensity.Large, GridDensity.Large.larger())
        assertEquals(GridDensity.Month, GridDensity.Month.smaller())
        assertFalse(GridDensity.Month.dayHeaders)
    }

    @Test
    fun `pinch steps once per threshold and resets`() {
        val stepper = PinchStepper()
        assertEquals(0, stepper.feed(1.1f))
        assertEquals(1, stepper.feed(1.2f))
        assertEquals(0, stepper.feed(0.9f))
        assertEquals(-1, stepper.feed(0.8f))
        stepper.reset()
        assertEquals(0, stepper.feed(0.95f))
    }

    @Test
    fun `fast scroller maps fractions to positions and finds year starts`() {
        assertEquals(0, FastScrollMath.positionFor(0f, 10_000))
        assertEquals(9_999, FastScrollMath.positionFor(1f, 10_000))
        assertEquals(5_000, FastScrollMath.positionFor(0.50005f, 10_000))
        assertEquals(0.5f, FastScrollMath.fractionFor(5, 11), 0.0001f)
        val layout = TimelineLayout(
            listOf(
                MonthIndexEntry("2025-01", 10, "a"),
                MonthIndexEntry("2024-12", 5, "b"),
                MonthIndexEntry("2024-03", 5, "c"),
                MonthIndexEntry("2023-07", 0, "d"),
                MonthIndexEntry("2023-06", 3, "e")
            )
        )
        assertEquals(listOf("2025" to 0, "2024" to 10, "2023" to 20), FastScrollMath.yearStarts(layout))
    }

    @Test
    fun `one card at a time, most important first, backup card snoozed for 7 days`() {
        val now = 10L * 24 * 60 * 60 * 1000
        assertEquals(PhotosCard.SignInNeeded, PhotosCards.pick(false, false, 3, false, null, now))
        assertEquals(PhotosCard.KitPending, PhotosCards.pick(true, false, 3, false, null, now))
        assertEquals(PhotosCard.PartialAccess(3), PhotosCards.pick(true, true, 3, false, null, now))
        assertEquals(PhotosCard.BackupOff, PhotosCards.pick(true, true, null, false, null, now))
        assertNull("dismissed yesterday", PhotosCards.pick(true, true, null, false, now - 86_400_000L, now))
        assertEquals(PhotosCard.BackupOff, PhotosCards.pick(true, true, null, false, 0L, now))
        assertNull("unknown state shows nothing", PhotosCards.pick(null, null, null, null, null, now))
    }

    @Test
    fun `export names are safe`() {
        assertEquals("passwd", MediaExporter.safeName("../../etc/passwd"))
        assertEquals("foto.jpg", MediaExporter.safeName(".\u0000foto.jpg"))
        assertEquals("bento", MediaExporter.safeName("   "))
        assertEquals(120, MediaExporter.safeName("a".repeat(500)).length)
    }

    @Test
    fun `upload badges follow remote_state`() {
        assertEquals(UploadBadge.Pending, uploadBadge(MediaSamples.asset("a", "2024-01-01", remoteState = "local_only")))
        assertEquals(UploadBadge.Pending, uploadBadge(MediaSamples.asset("a", "2024-01-01", remoteState = "uploading")))
        assertEquals(UploadBadge.Failed, uploadBadge(MediaSamples.asset("a", "2024-01-01", remoteState = "failed")))
        assertEquals(UploadBadge.None, uploadBadge(MediaSamples.asset("a", "2024-01-01", remoteState = null)))
    }
}

@RunWith(RobolectricTestRunner::class)
class MediaFormatTest {
    private val es = Locale.forLanguageTag("es")

    @Test
    fun `durations, months and days in Spanish and English`() {
        assertEquals("0:42", MediaFormat.duration(42_000))
        assertEquals("12:05", MediaFormat.duration(725_000))
        assertEquals("1:02:03", MediaFormat.duration(3_723_000))
        assertEquals("Marzo de 2024", MediaFormat.monthTitle("2024-03", es))
        assertEquals("March 2024", MediaFormat.monthTitle("2024-03", Locale.ENGLISH))
        assertTrue(MediaFormat.dayTitle("2024-03-12", es, java.time.LocalDate.of(2024, 6, 1)).startsWith("Mar"))
        assertTrue(MediaFormat.dayTitle("2023-03-12", es, java.time.LocalDate.of(2024, 6, 1)).contains("2023"))
        assertEquals("12 de marzo de 2024", MediaFormat.longDate("2024-03-12", es))
    }

    @Test
    fun `timeline day comes from taken_at, else created_at`() {
        val asset = MediaSamples.asset("a", "2024-03-12")
        assertEquals("2024-03-12", MediaFormat.dayOf(asset))
        assertEquals("2024-01-02", MediaFormat.dayOf(asset.copy(takenAt = null, createdAt = "2024-01-02T03:00:00Z")))
        assertTrue(MediaFormat.isVideo(MediaSamples.asset("v", "2024-03-12", kind = "video")))
    }
}
