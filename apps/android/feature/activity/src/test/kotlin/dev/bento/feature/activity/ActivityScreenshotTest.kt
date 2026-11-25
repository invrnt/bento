package dev.bento.feature.activity

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import dev.bento.designsystem.component.AvatarStatus
import dev.bento.designsystem.component.StatusAvatar
import dev.bento.engine.EngineState
import dev.bento.feature.settings.BackupPolicy
import dev.bento.feature.settings.BackupStatus
import dev.bento.testing.BentoScreenshots
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** Roborazzi goldens of Cuenta y actividad (sheet body and Activity screen) and every avatar ring state. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = BentoScreenshots.QUALIFIERS)
class ActivityScreenshotTest {
    @get:Rule
    val compose = createComposeRule()

    private fun shot(name: String, content: @Composable () -> Unit) = BentoScreenshots.capture(compose, "screenshots", name, content)

    private fun sheet(overview: ActivityOverview) = shot("sheet-${overviewName(overview)}") {
        Column { AccountSheetBody(overview, ActivityActions(), ActivityNavigation()) }
    }

    private var name = ""
    private fun overviewName(@Suppress("UNUSED_PARAMETER") o: ActivityOverview) = name

    @Test fun sheetUpToDate() = run {
        name = "up-to-date"
        sheet(ActivityFixtures.overview())
    }

    @Test fun sheetUploading() = run {
        name = "uploading"
        sheet(ActivityFixtures.overview(ActivityFixtures.UPLOADING))
    }

    @Test fun sheetWaitingWifi() = run {
        name = "waiting-wifi"
        sheet(ActivityFixtures.overview(backup = BackupStatus(pending = 340, waiting = mapOf("wifi" to 340))))
    }

    @Test fun sheetAttention() = run {
        name = "attention"
        sheet(ActivityFixtures.overview(ActivityFixtures.ATTENTION, imports = listOf(ActivityFixtures.failure)))
    }

    @Test fun sheetOffline() = run {
        name = "offline"
        sheet(ActivityFixtures.overview("""{"summary":"offline"}"""))
    }

    @Test fun sheetPausedStalled() = run {
        name = "paused-stalled"
        sheet(ActivityFixtures.overview(policy = BackupPolicy(paused = true), backup = BackupStatus(pending = 30), stalled = true))
    }

    @Test fun sheetFloodWait() = run {
        name = "flood-wait"
        sheet(ActivityFixtures.overview(ActivityFixtures.FLOOD))
    }

    @Test fun activityScreenEmpty() = shot("screen-empty") {
        ActivityContent(ActivityFixtures.overview(), ActivityActions(), ActivityNavigation(), onBack = {})
    }

    @Test fun activityScreenStarting() = shot("screen-starting") {
        ActivityContent(ActivityOverview(engine = EngineState.Starting), ActivityActions(), ActivityNavigation(), onBack = {})
    }

    @Test fun avatarRingStates() = shot("avatar-states") {
        Row(Modifier.padding(16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            StatusAvatar("Ana García", AvatarStatus.Idle, {})
            StatusAvatar("Ana García", AvatarStatus.Syncing, {}, progress = 0.3f)
            StatusAvatar("Ana García", AvatarStatus.Syncing, {})
            StatusAvatar("Ana García", AvatarStatus.Attention, {})
            StatusAvatar("Ana García", AvatarStatus.Offline, {})
            StatusAvatar("Ana García", AvatarStatus.Paused, {})
        }
    }
}
