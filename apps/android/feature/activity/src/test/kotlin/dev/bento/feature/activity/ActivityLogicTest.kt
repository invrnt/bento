package dev.bento.feature.activity

import dev.bento.designsystem.component.AvatarStatus
import dev.bento.engine.DegradedReason
import dev.bento.engine.EngineState
import dev.bento.feature.settings.BackupPolicy
import dev.bento.feature.settings.BackupStatus
import dev.bento.feature.settings.WaitReason
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Status line and avatar ring for every state of product/android.md §7 (pure). */
class ActivityLogicTest {
    private val f = ActivityFixtures

    @Test
    fun allSyncedHasNoRing() {
        val o = f.overview()
        assertEquals(AvatarStatus.Idle, o.avatar)
        assertEquals(StatusLine.UpToDate, o.status)
        assertNull(o.progress)
    }

    @Test
    fun uploadingIsADeterminateArcWithEta() {
        val o = f.overview(ActivityFixtures.UPLOADING)
        assertEquals(AvatarStatus.Syncing, o.avatar)
        assertEquals(0.3f, o.progress!!, 0.001f)
        assertEquals(StatusLine.Uploading(12, 170), o.status)
    }

    @Test
    fun attentionIsAWarningDotWithOneActionEach() {
        val o = f.overview(ActivityFixtures.ATTENTION, imports = listOf(ActivityFixtures.failure))
        assertEquals(AvatarStatus.Attention, o.avatar)
        assertEquals(StatusLine.Attention(6), o.status)
        val actions = o.attention.map { (it as? AttentionEntry.Backend)?.action }
        assertEquals(
            listOf(
                AttentionAction.Retry,
                AttentionAction.Reconnect,
                AttentionAction.SaveKit,
                AttentionAction.ReviewDevice,
                AttentionAction.None,
                null
            ),
            actions
        )
        assertEquals(AttentionEntry.ImportFailed(ActivityFixtures.failure), o.attention.last())
    }

    @Test
    fun offlineDimsTheAvatar() {
        assertEquals(AvatarStatus.Offline, f.overview("""{"summary":"offline"}""").avatar)
        assertEquals(StatusLine.Offline, f.overview("""{"summary":"offline"}""").status)
        val degraded = f.overview(engine = EngineState.Degraded(DegradedReason.STALLED))
        assertEquals(AvatarStatus.Offline, degraded.avatar)
    }

    @Test
    fun pausedShowsThePauseGlyph() {
        val o = f.overview(policy = BackupPolicy(paused = true))
        assertEquals(AvatarStatus.Paused, o.avatar)
        assertEquals(StatusLine.Paused(lowBattery = false), o.status)
        assertEquals(StatusLine.Paused(lowBattery = true), f.overview(policy = BackupPolicy(effectivePaused = true)).status)
    }

    @Test
    fun telegramWaitIsTheStatusLineNotAnAttentionItem() {
        val o = f.overview(ActivityFixtures.FLOOD)
        assertEquals(StatusLine.FloodWait(4), o.status)
        assertEquals(emptyList<AttentionEntry>(), o.attention)
        assertEquals(AvatarStatus.Syncing, o.avatar)
    }

    @Test
    fun waitingForWifiIsSaidOnlyWhenBackupIsOn() {
        val waiting = BackupStatus(pending = 340, waiting = mapOf("wifi" to 340))
        assertEquals(StatusLine.Waiting(340, WaitReason.Wifi), f.overview(backup = waiting).status)
        assertEquals(StatusLine.UpToDate, f.overview(backup = waiting, backupOn = false).status)
    }

    @Test
    fun beforeTheEngineAnswersItSaysStarting() {
        assertEquals(StatusLine.Starting, ActivityOverview(engine = EngineState.Starting).status)
    }

    @Test
    fun malformedActivityFallsBackToUpToDate() {
        assertEquals(ActivityDto(), ActivityFixtures.activity("""{"summary":12,"attention":"x"}"""))
    }
}
