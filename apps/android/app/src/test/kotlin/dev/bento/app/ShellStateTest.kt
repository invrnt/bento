package dev.bento.app

import androidx.compose.foundation.clickable
import androidx.compose.material3.Text
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import dev.bento.app.navigation.BentoApp
import dev.bento.app.navigation.EntryInsets
import dev.bento.app.navigation.Navigator
import dev.bento.app.navigation.Placeholder
import dev.bento.app.navigation.Route
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.engine.EngineState
import dev.bento.engine.WorkerMode
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** A tab root keeps its saved state while a full-screen route (no tab scaffold) sits on top of it. */
@RunWith(RobolectricTestRunner::class)
class ShellStateTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    @Config(qualifiers = "w411dp-h891dp-xxhdpi")
    fun tabStateSurvivesFullScreenRoute() {
        val navigator = Navigator()
        compose.setContent {
            BentoTheme(darkTheme = false, reducedMotion = true) {
                BentoApp(navigator, EngineState.Ready(1, "t", "k", WorkerMode.FULL), onExit = {}, entries = {
                    entry<Route.Photos>(metadata = EntryInsets.Tabs) {
                        var taps by rememberSaveable { mutableIntStateOf(0) }
                        Text("$taps", Modifier.testTag("count").clickable { taps++ })
                    }
                    entry<Route.Viewer>(metadata = EntryInsets.FullBleed) { Placeholder("Visor") }
                })
            }
        }
        compose.onNodeWithTag("count").performClick()
        compose.onNodeWithTag("count").performClick()
        compose.onNodeWithTag("count").assertTextEquals("2")

        compose.runOnIdle { navigator.navigate(Route.Viewer("a")) }
        compose.waitForIdle()
        compose.runOnIdle { navigator.back() }
        compose.waitForIdle()

        compose.onNodeWithTag("count").assertTextEquals("2")
    }
}
