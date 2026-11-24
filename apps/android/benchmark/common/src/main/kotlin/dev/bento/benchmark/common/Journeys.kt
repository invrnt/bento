package dev.bento.benchmark.common

import android.content.ContentValues
import android.content.Intent
import android.net.Uri
import android.provider.MediaStore
import androidx.benchmark.macro.MacrobenchmarkScope
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.BySelector
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import java.util.regex.Pattern

/**
 * The journeys shared by the Baseline Profile generator and the benchmarks (product/android.md §13), on the Spanish UI
 * of a seeded library ([LibrarySeeder]). Every step waits for the screen it needs and fails with the UI tree when
 * that screen never appears, so a broken journey cannot silently profile or measure the wrong thing.
 */
object Journeys {
    val tile: Pattern = Pattern.compile("photos:tile:.*")
    const val GRID = "photos:grid"
    const val FAST_SCROLLER = "photos:fast-scroller"
    const val VIEWER = "viewer:pager"
    const val SEARCH_PILL = "Buscar en Bento"
    const val SHARE_SAVE = "Guardar en Bento"

    /** Cold/warm start lands on Fotos (cached gate); wait for the grid and its first tiles. */
    fun MacrobenchmarkScope.awaitFotos(timeoutMs: Long = 60_000) {
        waitFor(By.res(GRID), timeoutMs)
        waitFor(By.res(tile), 30_000)
    }

    /** Fling the timeline down and back up (the generator and FrameTimingMetric both use this). */
    fun MacrobenchmarkScope.flingFotos(down: Int = 8, up: Int = 4) {
        val grid = waitFor(By.res(GRID))
        grid.setGestureMargin(device.displayWidth / 5)
        repeat(down) {
            grid.fling(Direction.DOWN, 6_000)
            device.waitForIdle(100)
        }
        repeat(up) {
            grid.fling(Direction.UP, 6_000)
            device.waitForIdle(100)
        }
    }

    /** Drag the fast scroller thumb through the whole library and back, like looking for a month. */
    fun MacrobenchmarkScope.dragFastScroller() {
        // The thumb appears once the grid scrolls.
        waitFor(By.res(GRID)).scroll(Direction.DOWN, 0.5f)
        val thumb = device.wait(Until.findObject(By.res(FAST_SCROLLER)), 5_000) ?: return
        val start = thumb.visibleCenter
        device.swipe(start.x, start.y, start.x, device.displayHeight - 200, 240)
        device.waitForIdle(300)
        val again = device.findObject(By.res(FAST_SCROLLER)) ?: return
        device.swipe(again.visibleCenter.x, again.visibleCenter.y, again.visibleCenter.x, 300, 240)
        device.waitForIdle(300)
    }

    /** Back to the top of the timeline so the next journey starts from the same place. */
    fun MacrobenchmarkScope.scrollFotosToTop() {
        val grid = waitFor(By.res(GRID))
        repeat(20) { if (!grid.scroll(Direction.UP, 5f)) return }
    }

    /** Tap a tile, wait for the viewer; optionally swipe [swipes] photos, then back to the grid. */
    fun MacrobenchmarkScope.openViewer(index: Int = 3, swipes: Int = 0, close: Boolean = true) {
        waitFor(By.res(tile), 10_000)
        val tiles = device.findObjects(By.res(tile))
        (tiles.getOrNull(index) ?: tiles.first()).click()
        val pager = waitFor(By.res(VIEWER), 10_000)
        device.waitForIdle()
        repeat(swipes) {
            pager.setGestureMargin(device.displayWidth / 8)
            pager.swipe(Direction.LEFT, 0.8f)
            device.waitForIdle()
        }
        if (close) {
            device.pressBack()
            waitFor(By.res(GRID), 10_000)
            device.waitForIdle()
        }
    }

    /** Archivos tab → the seeded folder → its files. */
    fun MacrobenchmarkScope.openArchivosTab() {
        tapNavigation("Archivos")
        waitFor(By.text(LibrarySeeder.FOLDER), 30_000)
    }

    fun MacrobenchmarkScope.openSeededFolder() {
        waitFor(By.text(LibrarySeeder.FOLDER), 30_000).click()
        waitFor(By.text(Pattern.compile("${LibrarySeeder.FILE_PREFIX}\\d+\\.txt")), 30_000)
    }

    /** Up one level in Archivos (system back), then Fotos tab. */
    fun MacrobenchmarkScope.backToFotos() {
        repeat(3) {
            if (device.hasObject(By.res(GRID))) return
            if (device.hasObject(By.text("Fotos"))) tapNavigation("Fotos") else device.pressBack()
            device.wait(Until.hasObject(By.res(GRID)), 5_000)
        }
        waitFor(By.res(GRID), 10_000)
    }

    /** Buscar: open from the top bar, type "factura" key by key, wait for the first results. */
    fun MacrobenchmarkScope.openSearch() {
        waitFor(By.text(SEARCH_PILL), 10_000).click()
        waitFor(By.clazz("android.widget.EditText"), 10_000)
    }

    fun MacrobenchmarkScope.typeSearch(query: String = "factura") {
        val field = waitFor(By.clazz("android.widget.EditText"), 10_000)
        for (end in 1..query.length) field.text = query.substring(0, end)
        waitFor(By.text(Pattern.compile("${LibrarySeeder.FILE_PREFIX}\\d+\\.txt")), 30_000)
    }

    fun MacrobenchmarkScope.closeSearch() {
        repeat(3) {
            if (device.hasObject(By.res(GRID))) return
            device.pressBack()
            device.wait(Until.hasObject(By.res(GRID)), 3_000)
        }
    }

    /** A JPEG this test APK owns in MediaStore, so it can grant the app read access when sharing it. */
    fun sharedImage(): Uri {
        val context = InstrumentationRegistry.getInstrumentation().context
        val resolver = context.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, "Compartida benchmark.jpg")
            put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg")
            put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/BentoBenchmark")
        }
        val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values) ?: error("MediaStore insert failed")
        resolver.openOutputStream(uri)!!.use { it.write(LibrarySeeder.jpeg(77_777, context.cacheDir)) }
        return uri
    }

    /** Another app shares an image: Bento's sheet opens over it; returns once "Guardar en Bento" can be tapped. */
    fun MacrobenchmarkScope.openShareSheet(uri: Uri) {
        val context = InstrumentationRegistry.getInstrumentation().context
        val intent = Intent(Intent.ACTION_SEND)
            .setClassName(BentoDevice.PACKAGE, "${BentoDevice.PACKAGE}.ShareActivity")
            .setType("image/jpeg")
            .putExtra(Intent.EXTRA_STREAM, uri)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
        waitFor(By.text(SHARE_SAVE).clickable(true).enabled(true), 30_000)
    }

    /** Tap "Guardar en Bento" and wait until the sheet is gone. */
    fun MacrobenchmarkScope.saveShare() {
        waitFor(By.text(SHARE_SAVE).clickable(true).enabled(true), 10_000).click()
        check(device.wait(Until.gone(By.text(SHARE_SAVE)), 10_000)) { "share sheet still visible" }
    }

    /** Navigation bar items expose their label as a child text node; the lowest match on screen is the bar's. */
    fun MacrobenchmarkScope.tapNavigation(label: String) {
        waitFor(By.text(label), 10_000)
        device.findObjects(By.text(label)).maxBy { it.visibleBounds.bottom }.click()
    }

    fun MacrobenchmarkScope.waitFor(selector: BySelector, timeoutMs: Long = 20_000): UiObject2 {
        dismissSystemDialogs()
        return device.wait(Until.findObject(selector), timeoutMs)
            ?: dismissSystemDialogs().let { device.wait(Until.findObject(selector), 5_000) }
            ?: failWithScreen("no $selector on screen")
    }

    /** A loaded emulator shows "X isn't responding" for other apps; keep waiting so our UI stays reachable. */
    private fun MacrobenchmarkScope.dismissSystemDialogs() {
        repeat(3) { device.findObject(By.text("Wait"))?.click() ?: return }
    }

    /** Saves a screenshot and the UI tree under /sdcard/Android/media/<test package>, then fails. */
    private fun failWithScreen(message: String): Nothing {
        val context = InstrumentationRegistry.getInstrumentation().context
        val dir = "/sdcard/Android/media/${context.packageName}"
        val name = message.replace(Regex("[^A-Za-z0-9]+"), "-").take(80)
        BentoDevice.shell("mkdir -p $dir")
        BentoDevice.shell("screencap -p $dir/$name.png")
        BentoDevice.shell("uiautomator dump $dir/$name.xml")
        error(message)
    }
}
