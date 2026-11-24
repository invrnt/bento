package dev.bento.feature.photos.benchmark

import android.util.Log
import androidx.benchmark.macro.ExperimentalMetricApi
import androidx.benchmark.macro.FrameTimingMetric
import androidx.benchmark.macro.StartupMode
import androidx.benchmark.macro.TraceSectionMetric
import androidx.benchmark.macro.junit4.MacrobenchmarkRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.Until
import java.util.regex.Pattern
import org.junit.BeforeClass
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Fotos performance (product/android.md §13) on a library of >= [SEED] photos: fling scrolling and the fast scroller
 * (FrameTimingMetric; the app also logs JankStats per screen under `BentoJank`), and viewer open
 * (`bento.viewer.open`: tap → first frame showing the photo). Emulator + debuggable build: indicative numbers only.
 */
@RunWith(AndroidJUnit4::class)
class PhotosBenchmarks {
    @get:Rule
    val rule = MacrobenchmarkRule()

    companion object {
        const val SEED = 10_000

        @JvmStatic
        @BeforeClass
        fun seed() {
            BentoDevice.shell("cmd locale set-app-locales ${BentoDevice.PACKAGE} --locales es-ES")
            val endpoint = BentoDevice.ready()
            val started = System.currentTimeMillis()
            val count = LibrarySeeder.ensure(endpoint, SEED)
            Log.i("BentoBenchmark", "library has $count photos (seeding took ${(System.currentTimeMillis() - started) / 1000} s)")
            // Let thumbnail jobs catch up so scrolling measures real tiles, not placeholders.
            Thread.sleep(5_000)
        }
    }

    private fun androidx.benchmark.macro.MacrobenchmarkScope.openFotos() {
        startActivityAndWait()
        device.wait(Until.hasObject(By.res("photos:grid")), 60_000)
        device.wait(Until.hasObject(By.res(Pattern.compile("photos:tile:.*"))), 30_000)
        device.waitForIdle()
    }

    @Test
    fun timelineFling() = rule.measureRepeated(
        packageName = BentoDevice.PACKAGE,
        metrics = listOf(FrameTimingMetric()),
        iterations = 5,
        startupMode = StartupMode.WARM,
        setupBlock = { openFotos() }
    ) {
        val grid = device.findObject(By.res("photos:grid"))
        grid.setGestureMargin(device.displayWidth / 5)
        repeat(8) {
            grid.fling(Direction.DOWN, 6_000)
            device.waitForIdle(100)
        }
        repeat(4) {
            grid.fling(Direction.UP, 6_000)
            device.waitForIdle(100)
        }
    }

    @Test
    fun fastScrollerDrag() = rule.measureRepeated(
        packageName = BentoDevice.PACKAGE,
        metrics = listOf(FrameTimingMetric()),
        iterations = 5,
        startupMode = StartupMode.WARM,
        setupBlock = {
            openFotos()
            device.findObject(By.res("photos:grid")).scroll(Direction.DOWN, 0.5f)
        }
    ) {
        val thumb = device.wait(Until.findObject(By.res("photos:fast-scroller")), 5_000) ?: return@measureRepeated
        val start = thumb.visibleCenter
        // Drag the thumb through the whole library (10,000 photos, ~3 years) and back, like a person looking for a month.
        device.swipe(start.x, start.y, start.x, device.displayHeight - 200, 240)
        device.waitForIdle(300)
        val again = device.findObject(By.res("photos:fast-scroller")) ?: return@measureRepeated
        device.swipe(again.visibleCenter.x, again.visibleCenter.y, again.visibleCenter.x, 300, 240)
    }

    @OptIn(ExperimentalMetricApi::class)
    @Test
    fun viewerOpen() = rule.measureRepeated(
        packageName = BentoDevice.PACKAGE,
        metrics = listOf(TraceSectionMetric("bento.viewer.open", TraceSectionMetric.Mode.Average), FrameTimingMetric()),
        iterations = 10,
        startupMode = StartupMode.WARM,
        setupBlock = { openFotos() }
    ) {
        device.wait(Until.hasObject(By.res(Pattern.compile("photos:tile:.*"))), 10_000)
        val tiles = device.findObjects(By.res(Pattern.compile("photos:tile:.*")))
        val tile = tiles.getOrNull(3) ?: tiles.firstOrNull() ?: return@measureRepeated
        tile.click()
        device.wait(Until.hasObject(By.res("viewer:pager")), 5_000)
        device.waitForIdle()
        device.pressBack()
        device.wait(Until.hasObject(By.res("photos:grid")), 5_000)
        device.waitForIdle()
    }
}
