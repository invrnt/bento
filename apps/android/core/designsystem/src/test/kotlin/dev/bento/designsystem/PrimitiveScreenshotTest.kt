package dev.bento.designsystem

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import com.github.takahirom.roborazzi.captureRoboImage
import dev.bento.designsystem.specimen.BentoSpecimens
import dev.bento.designsystem.specimen.Specimen
import dev.bento.designsystem.theme.BentoTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.ParameterizedRobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/**
 * Roborazzi goldens for every primitive state (design-system/android.md §9): light, dark, 200 % font (411 dp),
 * compact (320 dp) and expanded (840 dp). Record with `./gradlew :core:designsystem:recordRoborazziDebug`, verify with
 * `verifyRoborazziDebug`. Images: core/designsystem/screenshots/<specimen>/<variant>.png.
 */
@RunWith(ParameterizedRobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = "es-w840dp-h1800dp-xhdpi")
class PrimitiveScreenshotTest(private val specimen: Specimen) {
    @get:Rule
    val compose = createComposeRule()

    private data class Variant(val name: String, val dark: Boolean, val fontScale: Float, val width: Int)

    private val variants = listOf(
        Variant("light", dark = false, fontScale = 1f, width = 411),
        Variant("dark", dark = true, fontScale = 1f, width = 411),
        Variant("font-200", dark = false, fontScale = 2f, width = 411),
        Variant("compact", dark = false, fontScale = 1f, width = 320),
        Variant("expanded", dark = true, fontScale = 1f, width = 840)
    )

    @Test
    fun capture() {
        var variant by mutableStateOf(variants.first())
        compose.mainClock.autoAdvance = false
        compose.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, variant.fontScale)) {
                BentoTheme(darkTheme = variant.dark, reducedMotion = false) {
                    Box(Modifier.testTag(TAG).width(variant.width.dp).background(BentoTheme.colors.surface)) { specimen.content() }
                }
            }
        }
        for (v in variants) {
            compose.runOnUiThread {
                variant = v
                Snapshot.sendApplyNotifications()
            }
            compose.mainClock.advanceTimeByFrame()
            compose.mainClock.advanceTimeBy(600)
            compose.waitForIdle()
            compose.onNodeWithTag(TAG).captureRoboImage("screenshots/${specimen.name}/${v.name}.png")
        }
    }

    companion object {
        private const val TAG = "specimen"

        @JvmStatic
        @ParameterizedRobolectricTestRunner.Parameters(name = "{0}")
        fun specimens(): List<Array<Any>> = BentoSpecimens.map { arrayOf<Any>(it) }
    }
}
