package dev.bento.update.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import dev.bento.testing.BentoScreenshots
import dev.bento.update.UpdateFailure
import dev.bento.update.UpdateState
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** Goldens in core/update/screenshots/<state>/<light|dark|font-200|compact|expanded>.png. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = BentoScreenshots.QUALIFIERS)
class UpdateScreenshotTest {
    @get:Rule
    val compose = createComposeRule()

    private fun shot(name: String, content: @Composable () -> Unit) =
        BentoScreenshots.capture(compose, "screenshots", name) { Column(Modifier.padding(16.dp)) { content() } }

    private fun card(name: String, state: UpdateState) = shot("card-$name") { UpdateCardContent(state, UpdateActions()) }

    private fun row(name: String, state: UpdateState) = shot("row-$name") { UpdateRowContent(state, "1.2.0", UpdateActions()) }

    @Test fun cardAvailable() = card("available", UpdateState.Available(release130))

    @Test fun cardDownloading() = card("downloading", UpdateState.Downloading(release130, 0.42f))

    @Test fun cardReady() = card("ready", UpdateState.Ready(release130))

    @Test fun cardCancelled() = card("cancelled", UpdateState.Ready(release130, cancelled = true))

    @Test fun cardPermission() = card("permission", UpdateState.Ready(release130, needsPermission = true))

    @Test fun cardInstalling() = card("installing", UpdateState.Installing(release130))

    @Test fun cardFailed() = card("failed-signer", UpdateState.Failed(UpdateFailure.Signer, release130))

    @Test fun rowUpToDate() = row("up-to-date", UpdateState.Idle(1L, upToDate = true))

    @Test fun rowChecking() = row("checking", UpdateState.Checking)

    @Test fun rowAvailable() = row("available", UpdateState.Available(release130))

    @Test fun rowDownloading() = row("downloading", UpdateState.Downloading(release130, 0.42f))

    @Test fun rowReady() = row("ready", UpdateState.Ready(release130))

    @Test fun rowFailed() = row("failed-network", UpdateState.Failed(UpdateFailure.Network))

    @Test fun rowUnavailable() = row("unavailable", UpdateState.Unavailable)
}
