package dev.bento.testing

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.junit4.ComposeContentTestRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import com.github.takahirom.roborazzi.captureRoboImage
import dev.bento.designsystem.theme.BentoTheme

/**
 * Screenshot variants every feature screen state is rendered in (design-system/android.md §9): light, dark,
 * 200 % font, compact (320 dp) and expanded (840 dp). Run under `@Config(qualifiers = "es-w840dp-h1800dp-xhdpi")`
 * so the largest variant fits; each variant is a fixed-size frame.
 */
object BentoScreenshots {
    data class Variant(val name: String, val dark: Boolean, val fontScale: Float, val width: Int, val height: Int)

    val variants: List<Variant> = listOf(
        Variant("light", dark = false, fontScale = 1f, width = 411, height = 891),
        Variant("dark", dark = true, fontScale = 1f, width = 411, height = 891),
        Variant("font-200", dark = false, fontScale = 2f, width = 411, height = 891),
        Variant("compact", dark = false, fontScale = 1f, width = 320, height = 640),
        Variant("expanded", dark = true, fontScale = 1f, width = 840, height = 720)
    )

    const val QUALIFIERS: String = "es-w840dp-h1800dp-xhdpi"
    private const val TAG = "bento-screenshot"

    /**
     * Renders [content] once and captures every variant to `<directory>/<name>/<variant>.png`.
     * Animations are frozen (manual clock) so goldens are stable.
     */
    fun capture(rule: ComposeContentTestRule, directory: String, name: String, content: @Composable () -> Unit) {
        var variant by mutableStateOf(variants.first())
        rule.mainClock.autoAdvance = false
        rule.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, variant.fontScale)) {
                BentoTheme(darkTheme = variant.dark, reducedMotion = true) {
                    Box(Modifier.testTag(TAG).size(variant.width.dp, variant.height.dp).background(BentoTheme.colors.tray)) {
                        content()
                    }
                }
            }
        }
        for (v in variants) {
            rule.runOnUiThread {
                variant = v
                Snapshot.sendApplyNotifications()
            }
            rule.mainClock.advanceTimeByFrame()
            rule.mainClock.advanceTimeBy(FRAME_SETTLE_MS)
            rule.waitForIdle()
            rule.onNodeWithTag(TAG).captureRoboImage("$directory/$name/${v.name}.png")
        }
    }

    private const val FRAME_SETTLE_MS = 600L
}
