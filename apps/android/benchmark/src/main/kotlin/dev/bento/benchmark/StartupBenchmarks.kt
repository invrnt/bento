package dev.bento.benchmark

import androidx.benchmark.macro.CompilationMode
import androidx.benchmark.macro.ExperimentalMetricApi
import androidx.benchmark.macro.StartupMode
import androidx.benchmark.macro.StartupTimingMetric
import androidx.benchmark.macro.TraceSectionMetric
import androidx.benchmark.macro.junit4.MacrobenchmarkRule
import dev.bento.benchmark.common.BentoDevice
import dev.bento.benchmark.common.Journeys.awaitFotos
import org.junit.BeforeClass
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized

/**
 * §13 startup budgets on a seeded library: cold start → first frame (TTID ≤ 500 ms), cold start → cached Fotos grid
 * with thumbnails (TTFD, `ReportDrawnWhen` in Fotos: ≤ 900 ms p50 / 1.5 s p90), engine ready (`bento.engine.ready`:
 * ≤ 2.5 s p50), plus warm start. The `bento.app.*` and `bento.engine.*` sections break the cold start down.
 */
@OptIn(ExperimentalMetricApi::class)
@RunWith(Parameterized::class)
class StartupBenchmarks(@Suppress("unused") private val name: String, private val compilation: CompilationMode) {
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
    fun coldStart() = rule.measureRepeated(
        packageName = BentoDevice.PACKAGE,
        metrics = listOf(
            StartupTimingMetric(),
            // TTID breakdown (docs/dev/android-performance.md §TTID): platform phases, then ours.
            TraceSectionMetric("bindApplication", TraceSectionMetric.Mode.First),
            TraceSectionMetric("bento.app.onCreate", TraceSectionMetric.Mode.First),
            TraceSectionMetric("activityStart", TraceSectionMetric.Mode.First),
            TraceSectionMetric("bento.app.setContent", TraceSectionMetric.Mode.First),
            TraceSectionMetric("activityResume", TraceSectionMetric.Mode.First),
            TraceSectionMetric("traversal", TraceSectionMetric.Mode.First),
            TraceSectionMetric("TextStringSimpleNode::measure", TraceSectionMetric.Mode.First),
            // GPU programs compiled for the first frame (Macrobenchmark drops the shader cache on cold starts).
            TraceSectionMetric("shader_compile", TraceSectionMetric.Mode.Sum),
            TraceSectionMetric("bento.engine.warmUp", TraceSectionMetric.Mode.First),
            TraceSectionMetric("bento.engine.startApi", TraceSectionMetric.Mode.First),
            TraceSectionMetric("bento.engine.ready", TraceSectionMetric.Mode.First)
        ),
        compilationMode = compilation,
        iterations = 10,
        startupMode = StartupMode.COLD
    ) {
        pressHome()
        startActivityAndWait()
        awaitFotos()
        // Engine ready ends asynchronously after the first frame: keep tracing until it is published.
        BentoDevice.awaitEndpoint(timeoutMs = 60_000)
    }

    @Test
    fun warmStart() = rule.measureRepeated(
        packageName = BentoDevice.PACKAGE,
        metrics = listOf(StartupTimingMetric()),
        compilationMode = compilation,
        iterations = 10,
        startupMode = StartupMode.WARM,
        setupBlock = {
            pressHome()
        }
    ) {
        startActivityAndWait()
        awaitFotos()
    }
}
