package dev.bento.benchmark

import androidx.benchmark.macro.CompilationMode
import androidx.benchmark.macro.ExperimentalMetricApi
import androidx.benchmark.macro.FrameTimingMetric
import androidx.benchmark.macro.MemoryUsageMetric
import androidx.benchmark.macro.StartupMode
import androidx.benchmark.macro.TraceSectionMetric
import androidx.benchmark.macro.junit4.MacrobenchmarkRule
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import dev.bento.benchmark.common.BentoDevice
import dev.bento.benchmark.common.Journeys
import dev.bento.benchmark.common.Journeys.awaitFotos
import dev.bento.benchmark.common.Journeys.dragFastScroller
import dev.bento.benchmark.common.Journeys.flingFotos
import dev.bento.benchmark.common.Journeys.openViewer
import org.junit.BeforeClass
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized

/**
 * §13 Fotos budgets on the seeded 10,000-photo library: fling and fast scroller frame timing (≤ 1 % janky frames;
 * the app also logs JankStats under `BentoJank`), viewer open (`bento.viewer.open` ≤ 100 ms) and viewer swipes, and
 * memory while flinging (RSS from `MemoryUsageMetric`; PSS in [MemoryBenchmark]).
 */
@OptIn(ExperimentalMetricApi::class)
@RunWith(Parameterized::class)
class FotosBenchmarks(@Suppress("unused") private val name: String, private val compilation: CompilationMode) {
    @get:Rule
    val rule = MacrobenchmarkRule()

    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "{0}")
        fun modes() = Compilation.modes()

        @JvmStatic
        @BeforeClass
        fun seed() = Compilation.seed()
    }

    @Test
    fun timelineFling() = rule.measureRepeated(
        packageName = BentoDevice.PACKAGE,
        metrics = listOf(FrameTimingMetric(), MemoryUsageMetric(MemoryUsageMetric.Mode.Max)),
        compilationMode = compilation,
        iterations = 5,
        startupMode = StartupMode.COLD,
        setupBlock = {
            startActivityAndWait()
            awaitFotos()
            device.waitForIdle()
        }
    ) {
        flingFotos()
    }

    @Test
    fun fastScroller() = rule.measureRepeated(
        packageName = BentoDevice.PACKAGE,
        metrics = listOf(FrameTimingMetric()),
        compilationMode = compilation,
        iterations = 5,
        startupMode = StartupMode.COLD,
        setupBlock = {
            startActivityAndWait()
            awaitFotos()
            device.waitForIdle()
        }
    ) {
        dragFastScroller()
    }

    @Test
    fun viewerOpen() = rule.measureRepeated(
        packageName = BentoDevice.PACKAGE,
        metrics = listOf(TraceSectionMetric("bento.viewer.open", TraceSectionMetric.Mode.First), FrameTimingMetric()),
        compilationMode = compilation,
        iterations = 10,
        startupMode = StartupMode.COLD,
        setupBlock = {
            startActivityAndWait()
            awaitFotos()
            device.waitForIdle()
        }
    ) {
        openViewer(index = 3)
    }

    @Test
    fun viewerSwipe() = rule.measureRepeated(
        packageName = BentoDevice.PACKAGE,
        metrics = listOf(FrameTimingMetric()),
        compilationMode = compilation,
        iterations = 5,
        startupMode = StartupMode.COLD,
        setupBlock = {
            startActivityAndWait()
            awaitFotos()
            openViewer(index = 3, close = false)
        }
    ) {
        repeat(5) {
            val pager = device.findObject(By.res(Journeys.VIEWER)) ?: return@measureRepeated
            pager.setGestureMargin(device.displayWidth / 8)
            pager.swipe(Direction.LEFT, 0.8f)
            device.waitForIdle()
        }
    }
}
