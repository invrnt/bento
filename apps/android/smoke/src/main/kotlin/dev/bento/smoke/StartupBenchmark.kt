package dev.bento.smoke

import androidx.benchmark.macro.ExperimentalMetricApi
import androidx.benchmark.macro.StartupMode
import androidx.benchmark.macro.StartupTimingMetric
import androidx.benchmark.macro.TraceSectionMetric
import androidx.benchmark.macro.junit4.MacrobenchmarkRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Macrobenchmark smoke: cold start to first frame, and engine-ready (the `bento.engine.startApi` trace
 * section ends when the API answers). Emulator + debuggable build: indicative only; agent 42 runs the real
 * matrix with a non-debuggable benchmark build and Baseline Profiles.
 */
@RunWith(AndroidJUnit4::class)
class StartupBenchmark {
    @get:Rule
    val rule = MacrobenchmarkRule()

    @OptIn(ExperimentalMetricApi::class)
    @Test
    fun coldStart() = rule.measureRepeated(
        packageName = AppDriver.PACKAGE,
        metrics = listOf(
            StartupTimingMetric(),
            TraceSectionMetric("bento.engine.warmUp", TraceSectionMetric.Mode.First),
            TraceSectionMetric("bento.engine.startApi", TraceSectionMetric.Mode.First),
            TraceSectionMetric("bento.engine.ready", TraceSectionMetric.Mode.First),
        ),
        iterations = 5,
        startupMode = StartupMode.COLD,
    ) {
        pressHome()
        startActivityAndWait()
        AppDriver.awaitEndpoint(timeoutMs = 60_000)
    }
}
