package dev.bento.baselineprofile

import androidx.benchmark.macro.junit4.BaselineProfileRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import dev.bento.benchmark.common.BentoDevice
import dev.bento.benchmark.common.Journeys.awaitFotos
import dev.bento.benchmark.common.Journeys.backToFotos
import dev.bento.benchmark.common.Journeys.closeSearch
import dev.bento.benchmark.common.Journeys.dragFastScroller
import dev.bento.benchmark.common.Journeys.flingFotos
import dev.bento.benchmark.common.Journeys.openArchivosTab
import dev.bento.benchmark.common.Journeys.openSearch
import dev.bento.benchmark.common.Journeys.openSeededFolder
import dev.bento.benchmark.common.Journeys.openViewer
import dev.bento.benchmark.common.Journeys.scrollFotosToTop
import dev.bento.benchmark.common.Journeys.typeSearch
import dev.bento.benchmark.common.LibrarySeeder
import org.junit.BeforeClass
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Baseline Profile for the journeys of product/android.md §13 on a seeded library: cold start to Fotos (also the
 * startup profile used for dex layout), Fotos fling and fast scroller, viewer open + swipe, Archivos list + open
 * folder, Buscar typing. Startup is recorded separately so the startup profile holds only the launch path.
 */
@RunWith(AndroidJUnit4::class)
class BaselineProfileGenerator {
    @get:Rule
    val rule = BaselineProfileRule()

    companion object {
        @JvmStatic
        @BeforeClass
        fun seed() {
            BentoDevice.spanish()
            val endpoint = BentoDevice.ready()
            LibrarySeeder.ensureLibrary(endpoint)
            BentoDevice.forceStop()
        }
    }

    @Test
    fun startup() = rule.collect(packageName = BentoDevice.PACKAGE, includeInStartupProfile = true) {
        pressHome()
        startActivityAndWait()
        awaitFotos()
    }

    @Test
    fun journeys() = rule.collect(packageName = BentoDevice.PACKAGE, includeInStartupProfile = false) {
        pressHome()
        startActivityAndWait()
        awaitFotos()
        flingFotos()
        dragFastScroller()
        scrollFotosToTop()
        openViewer(index = 3, swipes = 3)
        openArchivosTab()
        openSeededFolder()
        backToFotos()
        openSearch()
        typeSearch()
        closeSearch()
    }
}
