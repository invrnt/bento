package dev.bento.feature.settings

import android.Manifest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Pure rules of agent 41's settings: permissions per SDK, status header, stall card, lock timing, parsing, copy guards. */
class SettingsLogicTest {
    private fun granted(vararg names: String): (String) -> Boolean = { it in names }

    @Test
    fun mediaAccessPerSdk() {
        assertEquals(MediaAccess.Full, MediaPermissions.access(29, granted(Manifest.permission.READ_EXTERNAL_STORAGE)))
        assertEquals(MediaAccess.Denied, MediaPermissions.access(29, granted()))
        assertEquals(MediaAccess.Full, MediaPermissions.access(33, granted(Manifest.permission.READ_MEDIA_IMAGES)))
        assertEquals(MediaAccess.Denied, MediaPermissions.access(33, granted(Manifest.permission.READ_EXTERNAL_STORAGE)))
        assertEquals(MediaAccess.Partial, MediaPermissions.access(34, granted(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)))
        assertEquals(
            MediaAccess.Full,
            MediaPermissions.access(35, granted(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED))
        )
        assertEquals(listOf(Manifest.permission.READ_EXTERNAL_STORAGE), MediaPermissions.media(29))
        assertEquals(3, MediaPermissions.media(34).size)
    }

    @Test
    fun headerFollowsProductCopyOrder() {
        val waiting = BackupStatus(pending = 340, waiting = mapOf("wifi" to 340))
        assertEquals(BackupHeader.Off, BackupHeader.of(false, MediaAccess.Full, waiting, null))
        assertEquals(BackupHeader.NoAccess, BackupHeader.of(true, MediaAccess.Denied, waiting, null))
        assertEquals(BackupHeader.Waiting(340, WaitReason.Wifi), BackupHeader.of(true, MediaAccess.Full, waiting, BackupPolicy()))
        assertEquals(BackupHeader.Paused(false), BackupHeader.of(true, MediaAccess.Full, waiting, BackupPolicy(paused = true)))
        assertEquals(BackupHeader.Paused(true), BackupHeader.of(true, MediaAccess.Full, waiting, BackupPolicy(effectivePaused = true)))
        assertEquals(
            BackupHeader.Paused(true),
            BackupHeader.of(true, MediaAccess.Full, BackupStatus(pending = 5, waiting = mapOf("battery" to 5)), BackupPolicy())
        )
        assertEquals(BackupHeader.Running(7), BackupHeader.of(true, MediaAccess.Partial, BackupStatus(pending = 7), BackupPolicy()))
        val done = BackupHeader.of(true, MediaAccess.Full, BackupStatus(lastBackupAt = "2026-11-24T09:57:00+00:00"), BackupPolicy())
        assertEquals(BackupHeader.Done(java.time.Instant.parse("2026-11-24T09:57:00Z").toEpochMilli()), done)
        // Offline is the most actionable wait, then Wi-Fi.
        assertEquals(WaitReason.Offline, BackupStatus(pending = 1, waiting = mapOf("wifi" to 1, "offline" to 1)).waitReason)
        assertNull(BackupStatus(pending = 1, waiting = mapOf("wifi" to 0)).waitReason)
    }

    @Test
    fun stallNeedsADayOfUnexplainedPendingWork() {
        val day = StallDetector.STALL_MS
        val since = 1_000_000L
        val prefs = LocalPrefs(pendingSinceAt = since)
        val stuck = BackupStatus(pending = 30, lastBackupAt = null)
        assertFalse(StallDetector.stalled(stuck, BackupPolicy(), true, prefs, since + day - 1))
        assertTrue(StallDetector.stalled(stuck, BackupPolicy(), true, prefs, since + day + 1))
        // Waiting for Wi-Fi/charging or paused is not a stall; neither is backup off.
        assertFalse(StallDetector.stalled(stuck.copy(waiting = mapOf("wifi" to 30)), BackupPolicy(), true, prefs, since + 2 * day))
        assertFalse(StallDetector.stalled(stuck, BackupPolicy(paused = true), true, prefs, since + 2 * day))
        assertFalse(StallDetector.stalled(stuck, BackupPolicy(), false, prefs, since + 2 * day))
        // Dismissed for this backlog → hidden; a new backlog brings it back.
        assertFalse(StallDetector.stalled(stuck, BackupPolicy(), true, prefs.copy(stallDismissedAt = since + 1), since + 2 * day))
        val tracked = StallDetector.track(LocalPrefs(), pending = 3, now = 42)
        assertEquals(42L, tracked.pendingSinceAt)
        assertNull(StallDetector.track(tracked, pending = 0, now = 50).pendingSinceAt)
        assertEquals("https://dontkillmyapp.com/xiaomi", StallDetector.helpUrl("Redmi"))
        assertEquals("https://dontkillmyapp.com/samsung", StallDetector.helpUrl("samsung"))
        assertEquals("https://dontkillmyapp.com/", StallDetector.helpUrl("Acme"))
    }

    @Test
    fun appLockTiming() {
        var now = 0L
        val lock = AppLockState(initiallyLocked = true) { now }
        val on = LocalPrefs(lockEnabled = true, lockTimeout = LockTimeout.OneMinute)
        assertTrue(lock.locked.value) // cold start: locked before the first frame
        lock.onForeground(on)
        lock.unlock()
        assertFalse(lock.locked.value)
        lock.onBackground()
        now = 59_000
        lock.onForeground(on)
        assertFalse(lock.locked.value) // back within the timeout
        lock.onBackground()
        now = 59_000 + 60_000
        lock.onForeground(on)
        assertTrue(lock.locked.value) // away for the whole minute
        lock.unlock()
        // "Inmediatamente": any trip away locks; a foreground without leaving (config change) does not.
        val immediately = on.copy(lockTimeout = LockTimeout.Immediately)
        lock.onForeground(immediately)
        assertFalse(lock.locked.value)
        lock.onBackground()
        lock.onForeground(immediately)
        assertTrue(lock.locked.value)
        // Turning the lock off unlocks.
        lock.onForeground(LocalPrefs(lockEnabled = false))
        assertFalse(lock.locked.value)
    }

    @Test
    fun turningTheLockOnDoesNotLockTheCurrentScreen() {
        val lock = AppLockState { 0 }
        lock.onForeground(LocalPrefs())
        lock.enabledNow()
        lock.onForeground(LocalPrefs(lockEnabled = true))
        assertFalse(lock.locked.value)
    }

    @Test
    fun recentsHidingFollowsTheLock() {
        assertTrue(RecentsPrivacy.shouldHide(LocalPrefs(lockEnabled = true, hideInRecents = true)))
        assertFalse(RecentsPrivacy.shouldHide(LocalPrefs(lockEnabled = false, hideInRecents = true)))
        assertFalse(RecentsPrivacy.shouldHide(LocalPrefs(lockEnabled = true, hideInRecents = false)))
    }

    @Test
    fun phoneSettingsParseValuesAndDefaults() {
        val parsed = PhoneSettings.parse(
            Json.parseToJsonElement(SettingsFixtures.values(revision = 9, wifiOnly = false, charging = true)).jsonObject
        )
        assertEquals(9L, parsed.revision)
        assertFalse(parsed.wifiOnly)
        assertTrue(parsed.onlyCharging)
        assertTrue(parsed.ocrEnabled)
        assertEquals(2, parsed.cacheMaxGb)
        assertEquals(PhoneSettings(revision = 0), PhoneSettings.parse(kotlinx.serialization.json.JsonObject(emptyMap())))
    }

    @Test
    fun relayAndResetGuards() {
        assertTrue(RelayUrls.valid("wss://relay.bento.example"))
        assertTrue(RelayUrls.valid("ws://127.0.0.1:8788"))
        assertFalse(RelayUrls.valid("ws://relay.example"))
        assertFalse(RelayUrls.valid("https://relay.example"))
        assertFalse(RelayUrls.valid("nonsense"))
        assertTrue(PhoneReset.confirmed(" restablecer ", "RESTABLECER"))
        assertFalse(PhoneReset.confirmed("RESTABLECE", "RESTABLECER"))
    }

    @Test
    fun diagnosticsNeverCarrySecrets() {
        val values = Json.parseToJsonElement(SettingsFixtures.values()).jsonObject
        val lines = Diagnostics.settingsLines(values)
        assertTrue("telegram_api_hash: (hidden)" in lines)
        assertTrue(lines.any { it.startsWith("backup_wifi_only: true") })
        val scrubbed = Diagnostics.scrub("token=AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_- phone +57 300 123 4567 mail ana@example.com ok")
        assertFalse("AbCdEf" in scrubbed)
        assertFalse("300 123" in scrubbed)
        assertFalse("ana@" in scrubbed)
        assertTrue(scrubbed.endsWith("ok"))
        val report = Diagnostics.report(
            DiagnosticFacts("0.1.0", "ready (full)", "telegram", "idle", "pending=0", "summary=up_to_date", values),
            "Google Pixel",
            listOf("2026 worker started", "session 0123456789abcdef0123456789abcdef0123")
        )
        assertTrue("app_version: 0.1.0" in report)
        assertFalse("0123456789abcdef0123456789abcdef0123" in report)
    }

    @Test
    fun accountInitials() {
        assertEquals("AG", initialsOf("Ana García"))
        assertEquals("B", initialsOf(" "))
    }
}
