package dev.bento.feature.photos

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ApplicationProvider
import com.github.takahirom.roborazzi.captureRoboImage
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.testing.BentoScreenshots

/** Screen variants shared by the media features' goldens (design-system/android.md §9). */
data class ScreenVariant(val name: String, val dark: Boolean, val fontScale: Float, val width: Int, val height: Int)

val ScreenVariants = listOf(
    ScreenVariant("light", dark = false, fontScale = 1f, width = 411, height = 891),
    ScreenVariant("dark", dark = true, fontScale = 1f, width = 411, height = 891),
    ScreenVariant("font-200", dark = false, fontScale = 2f, width = 411, height = 891),
    ScreenVariant("compact", dark = false, fontScale = 1f, width = 320, height = 640),
    ScreenVariant("expanded", dark = true, fontScale = 1f, width = 840, height = 900)
)

/** The shared landscape frame (`BentoScreenshots.landscape`); run under `BentoScreenshots.LANDSCAPE_QUALIFIERS`. */
val LandscapeVariant: ScreenVariant = BentoScreenshots.landscape.let { ScreenVariant(it.name, it.dark, it.fontScale, it.width, it.height) }

/** One screen state rendered under every variant into `screenshots/<state>/<variant>.png`. */
class ScreenState(val name: String, val content: @Composable () -> Unit) {
    override fun toString() = name
}

/**
 * Captures [state] under every [ScreenVariants] entry. Images come from [fakeImageLoader] (flat colors per id), so the
 * goldens are deterministic.
 */
fun androidx.compose.ui.test.junit4.ComposeContentTestRule.captureVariants(state: ScreenState, variants: List<ScreenVariant> = ScreenVariants) {
    var variant by mutableStateOf(variants.first())
    mainClock.autoAdvance = false
    setContent {
        val density = LocalDensity.current
        CompositionLocalProvider(
            LocalDensity provides Density(density.density, variant.fontScale),
            LocalBentoImageLoader provides remember { fakeImageLoader(ApplicationProvider.getApplicationContext()) }
        ) {
            BentoTheme(darkTheme = variant.dark, reducedMotion = true) {
                Box(Modifier.testTag("screen").size(variant.width.dp, variant.height.dp).background(BentoTheme.colors.tray)) {
                    state.content()
                }
            }
        }
    }
    for (v in variants) {
        runOnUiThread {
            variant = v
            Snapshot.sendApplyNotifications()
        }
        mainClock.advanceTimeByFrame()
        mainClock.advanceTimeBy(800)
        waitForIdle()
        onNodeWithTag("screen").captureRoboImage("screenshots/${state.name}/${v.name}.png")
    }
}
