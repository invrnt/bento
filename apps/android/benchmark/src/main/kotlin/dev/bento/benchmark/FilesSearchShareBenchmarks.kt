package dev.bento.benchmark

import androidx.benchmark.macro.CompilationMode
import androidx.benchmark.macro.ExperimentalMetricApi
import androidx.benchmark.macro.FrameTimingMetric
import androidx.benchmark.macro.StartupMode
import androidx.benchmark.macro.TraceSectionMetric
import androidx.benchmark.macro.junit4.MacrobenchmarkRule
import dev.bento.benchmark.common.BentoDevice
import dev.bento.benchmark.common.Journeys
import dev.bento.benchmark.common.Journeys.awaitFotos
import dev.bento.benchmark.common.Journeys.openArchivosTab
import dev.bento.benchmark.common.Journeys.openSearch
import dev.bento.benchmark.common.Journeys.openSeededFolder
import dev.bento.benchmark.common.Journeys.openShareSheet
import dev.bento.benchmark.common.Journeys.saveShare
import dev.bento.benchmark.common.Journeys.typeSearch
import org.junit.BeforeClass
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized

/**
 * Archivos open folder (`bento.files.open`: tap → first frame listing the folder), Buscar first results
 * (`bento.search.results`: first key → first frame with results) and the §13 share budget (`bento.share.dismiss`:
 * `Guardar en Bento` → sheet paused, ≤ 200 ms). The app emits these slices (core/designsystem `InteractionTrace`).
 */
@OptIn(ExperimentalMetricApi::class)
@RunWith(Parameterized::class)
class FilesSearchShareBenchmarks(@Suppress("unused") private val name: String, private val compilation: CompilationMode) {
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
    fun archivosOpenFolder() = rule.measureRepeated(
        packageName = BentoDevice.PACKAGE,
        metrics = listOf(TraceSectionMetric("bento.files.open", TraceSectionMetric.Mode.First), FrameTimingMetric()),
        compilationMode = compilation,
        iterations = 10,
        startupMode = StartupMode.COLD,
        setupBlock = {
            startActivityAndWait()
            awaitFotos()
            openArchivosTab()
        }
    ) {
        openSeededFolder()
    }

    @Test
    fun searchFirstResults() = rule.measureRepeated(
        packageName = BentoDevice.PACKAGE,
        metrics = listOf(TraceSectionMetric("bento.search.results", TraceSectionMetric.Mode.First), FrameTimingMetric()),
        compilationMode = compilation,
        iterations = 10,
        startupMode = StartupMode.COLD,
        setupBlock = {
            startActivityAndWait()
            awaitFotos()
            // The engine answers search: measure typing, not the engine's cold start.
            BentoDevice.awaitEndpoint(timeoutMs = 60_000)
            openSearch()
        }
    ) {
        typeSearch()
    }

    @Test
    fun shareSheetDismiss() {
        val image = Journeys.sharedImage()
        rule.measureRepeated(
            packageName = BentoDevice.PACKAGE,
            metrics = listOf(TraceSectionMetric("bento.share.dismiss", TraceSectionMetric.Mode.First)),
            compilationMode = compilation,
            iterations = 10,
            startupMode = StartupMode.COLD,
            setupBlock = {
                pressHome()
                openShareSheet(image)
            }
        ) {
            saveShare()
        }
    }
}
