package dev.bento.app

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import com.github.takahirom.roborazzi.captureRoboImage
import dev.bento.app.navigation.BentoApp
import dev.bento.app.navigation.Navigator
import dev.bento.app.navigation.TopLevel
import dev.bento.app.navigation.shellPreviewEntries
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.engine.EngineState
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** Shell screenshots (BentoTheme): compact and expanded, light and dark, engine starting. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class ShellScreenshotTest {
    @get:Rule
    val compose = createComposeRule()

    private fun shell(dark: Boolean, state: EngineState = EngineState.Ready(1, "t", "k", dev.bento.engine.WorkerMode.FULL)) {
        compose.setContent {
            BentoTheme(darkTheme = dark, reducedMotion = true) {
                BentoApp(Navigator(), state, onExit = {}, entries = { shellPreviewEntries() })
            }
        }
    }

    @Test
    @Config(qualifiers = "w411dp-h891dp-xxhdpi")
    fun compactLight() {
        shell(dark = false)
        compose.onRoot().captureRoboImage("src/test/screenshots/shell_compact_light.png")
    }

    @Test
    @Config(qualifiers = "w411dp-h891dp-night-xxhdpi")
    fun compactDarkStarting() {
        shell(dark = true, state = EngineState.Starting)
        compose.onRoot().captureRoboImage("src/test/screenshots/shell_compact_dark_starting.png")
    }

    @Test
    @Config(qualifiers = "w1000dp-h800dp-xhdpi")
    fun expandedLightFiles() {
        compose.setContent {
            val nav = Navigator().apply { selectTab(TopLevel.FILES) }
            BentoTheme(darkTheme = false, reducedMotion = true) {
                BentoApp(nav, EngineState.Stopped, onExit = {}, entries = { shellPreviewEntries() })
            }
        }
        compose.onRoot().captureRoboImage("src/test/screenshots/shell_expanded_light_files.png")
    }
}
