package dev.bento.benchmark

import android.os.Bundle
import androidx.benchmark.macro.CompilationMode
import androidx.benchmark.macro.ExperimentalMetricApi
import androidx.benchmark.macro.MemoryUsageMetric
import androidx.benchmark.macro.junit4.MacrobenchmarkRule
import androidx.test.platform.app.InstrumentationRegistry
import dev.bento.benchmark.common.BentoDevice
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
 * §13 memory: total PSS of the app process (Kotlin + Python engine) after a Fotos session on the seeded library
 * (fling, fast scroller, viewer). `dumpsys meminfo` after each iteration; median and max are reported as
 * instrumentation status (`bento.pss.*`) and logged under `BentoBenchmark`. Budget ≤ 350 MB (100k library).
 */
@OptIn(ExperimentalMetricApi::class)
@RunWith(Parameterized::class)
class MemoryBenchmark(private val name: String, private val compilation: CompilationMode) {
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
    fun fotosSessionPss() {
        val samples = mutableListOf<Long>()
        rule.measureRepeated(
            packageName = BentoDevice.PACKAGE,
            metrics = listOf(MemoryUsageMetric(MemoryUsageMetric.Mode.Last)),
            compilationMode = compilation,
            iterations = 3,
            startupMode = null,
            setupBlock = {
                killProcess()
                startActivityAndWait()
                awaitFotos()
            }
        ) {
            flingFotos()
            dragFastScroller()
            openViewer(index = 3, swipes = 3)
            device.waitForIdle()
            BentoDevice.totalPssKb()?.let(samples::add)
        }
        check(samples.isNotEmpty()) { "no PSS sample" }
        val sorted = samples.sorted()
        val median = sorted[sorted.size / 2]
        val max = sorted.last()
        android.util.Log.i("BentoBenchmark", "PSS [$name] median ${median / 1024} MB, max ${max / 1024} MB, samples $samples")
        InstrumentationRegistry.getInstrumentation().sendStatus(
            2,
            Bundle().apply {
                putLong("bento.pss.$name.median_kb", median)
                putLong("bento.pss.$name.max_kb", max)
            }
        )
    }
}
