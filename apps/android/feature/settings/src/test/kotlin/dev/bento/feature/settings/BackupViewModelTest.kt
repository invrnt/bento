package dev.bento.feature.settings

import dev.bento.testing.MainDispatcherRule
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/** Permission states, policy toggles reflected in backend settings, and the free-up-space flow (agent 41 tests). */
@RunWith(RobolectricTestRunner::class)
class BackupViewModelTest {
    @get:Rule
    val main = MainDispatcherRule()

    private val api = SettingsFixtures.api()
    private val media = FakePhoneMedia()
    private val local = LocalSettings(FakePrefsStore())

    private fun vm() = BackupViewModel(
        SettingsFixtures.backup(api),
        SettingsFixtures.phoneSettings(api),
        media,
        local,
        { SettingsFixtures.NOW },
        main.dispatcher
    )

    private fun TestScope.effects(vm: BackupViewModel): MutableList<BackupEffect> {
        val out = mutableListOf<BackupEffect>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.effects.collect { out += it } }
        return out
    }

    private fun noSources() = api.on("GET /api/backup/sources") { """{"items":[]}""" }

    @Test
    fun grantedTurnsOnTheSuggestedFoldersAndStartsTheTransfer() = runTest(main.dispatcher) {
        noSources()
        media.access = MediaAccess.Full
        api.on("POST /api/backup/sources") { call ->
            val bucket = if ("b_cam" in call.body!!) "b_cam" else "b_shots"
            api.on("GET /api/backup/sources") {
                """{"items":[${SettingsFixtures.source("s_cam", "b_cam", pending = 3)},${SettingsFixtures.source("s_shots", bucket)}]}"""
            }
            SettingsFixtures.source("s_$bucket", bucket)
        }
        val vm = vm()
        val effects = effects(vm)
        advanceUntilIdle()
        assertFalse(vm.state.value.configuredOn)
        vm.turnOn()
        advanceUntilIdle()
        val bodies = api.calls.filter { it.method == "POST" && it.path == "/api/backup/sources" }.map { it.body!! }
        assertEquals(2, bodies.size)
        assertTrue(bodies.all { "\"kind\":\"media_store\"" in it })
        assertTrue(bodies.none { "b_wa" in it }) // only the suggested Cámara and Capturas de pantalla
        assertEquals(1, media.transfers)
        assertTrue(BackupEffect.Finished in effects)
        assertTrue(vm.state.value.configuredOn)
    }

    @Test
    fun deniedShowsRationaleOnceThenKeepsBackupOff() = runTest(main.dispatcher) {
        noSources()
        val vm = vm()
        val effects = effects(vm)
        advanceUntilIdle()
        vm.turnOn()
        assertTrue(vm.state.value.showRationale)
        vm.rationaleAccepted()
        advanceUntilIdle()
        assertEquals(BackupEffect.RequestMedia(MediaPermissions.media()), effects.single())
        vm.onMediaResult(canAskAgain = true)
        advanceUntilIdle()
        assertTrue(vm.state.value.deniedThisSession)
        assertFalse(vm.state.value.permanentlyDenied)
        assertEquals(0, api.count("POST /api/backup/sources"))
        // Denied for good ("Don't allow" twice): the action opens the app's settings, never a third prompt.
        vm.onMediaResult(canAskAgain = false)
        vm.turnOn()
        advanceUntilIdle()
        assertEquals(BackupEffect.OpenAppSettings, effects.last())
        assertEquals(BackupHeader.Off, vm.state.value.header)
    }

    @Test
    fun partialAccessIsRespectedAndExplained() = runTest(main.dispatcher) {
        media.access = MediaAccess.Partial
        media.visible = 12
        val vm = vm()
        advanceUntilIdle()
        assertEquals(MediaAccess.Partial, vm.state.value.access)
        assertEquals(12, vm.state.value.visibleCount)
        assertTrue(vm.state.value.configuredOn)
        assertFalse(vm.state.value.revoked)
    }

    @Test
    fun revokedLaterIsDetectedOnResumeAndToldToTheEngine() = runTest(main.dispatcher) {
        media.access = MediaAccess.Full
        val vm = vm()
        advanceUntilIdle()
        assertFalse(vm.state.value.revoked)
        media.access = MediaAccess.Denied
        vm.refresh()
        advanceUntilIdle()
        assertTrue(vm.state.value.revoked)
        assertEquals(BackupHeader.NoAccess, vm.state.value.header)
        assertEquals(1, media.accessEvents)
    }

    @Test
    fun locationDeniedIsToldOnce() = runTest(main.dispatcher) {
        media.access = MediaAccess.Full
        media.location = false
        val vm = vm()
        advanceUntilIdle()
        assertTrue(vm.state.value.showLocationNotice)
        vm.dismissLocationNotice()
        advanceUntilIdle()
        assertTrue(local.prefs.first().locationNoticeShown)
        assertFalse(vm().also { advanceUntilIdle() }.state.value.showLocationNotice)
    }

    @Test
    fun policyTogglesPatchTheBackendSettings() = runTest(main.dispatcher) {
        media.access = MediaAccess.Full
        val vm = vm()
        advanceUntilIdle()
        assertEquals(BackupHeader.Waiting(3, WaitReason.Wifi), vm.state.value.header)
        vm.setWifiOnly(false)
        vm.setVideosWifiOnly(false)
        vm.setOnlyCharging(true)
        advanceUntilIdle()
        val patches = api.calls.filter { it.method == "PATCH" && it.path == "/api/settings/values" }.map { it.body!! }
        assertEquals(3, patches.size)
        assertTrue(patches[0].contains("\"revision\":3") && patches[0].contains("\"backup_wifi_only\":false"))
        assertTrue(patches[1].contains("\"backup_videos_on_metered\":true"))
        assertTrue(patches[2].contains("\"backup_only_charging\":true"))
    }

    @Test
    fun aConcurrentSettingsEditIsRetriedOnTheFreshRevision() = runTest(main.dispatcher) {
        media.access = MediaAccess.Full
        var first = true
        api.on("PATCH /api/settings/values") {
            if (first) {
                first = false
                api.on("GET /api/settings/values") { SettingsFixtures.values(revision = 4) }
                throw dev.bento.api.ApiErrors.from(409, """{"error":{"code":"settings_revision_conflict","message":"x"}}""")
            }
            SettingsFixtures.values(revision = 5, wifiOnly = false)
        }
        val vm = vm()
        advanceUntilIdle()
        vm.setWifiOnly(false)
        advanceUntilIdle()
        val patches = api.calls.filter { it.method == "PATCH" }.map { it.body!! }
        assertEquals(listOf(true, true), patches.map { "\"backup_wifi_only\":false" in it })
        assertTrue("\"revision\":4" in patches[1])
        assertFalse(vm.state.value.failed)
    }

    @Test
    fun runNowLiftsTheWifiRuleAsAUserInitiatedTransfer() = runTest(main.dispatcher) {
        media.access = MediaAccess.Full
        api.on("POST /api/backup/run-now") { """{"accepted":true,"pending":3}""" }
        val vm = vm()
        advanceUntilIdle()
        vm.runNow()
        advanceUntilIdle()
        assertEquals(1, api.count("POST /api/backup/run-now"))
        assertEquals(1, media.transfers)
    }

    @Test
    fun freeUpPreviewThenReportsOnlyWhatTheSystemDeleted() = runTest(main.dispatcher) {
        media.access = MediaAccess.Full
        api.on("GET /api/backup/free-up-space/preview") {
            """{"items":[{"asset_id":"a1","media_id":"101","size_bytes":1000},{"asset_id":"a2","media_id":"102","size_bytes":2000},
            {"asset_id":"a9","media_id":"999","size_bytes":5}],"total_bytes":3005,"count":3}"""
        }
        api.on("POST /api/backup/free-up-space/confirm") { """{"freed":1}""" }
        val vm = vm()
        val effects = effects(vm)
        advanceUntilIdle()
        vm.openFreeUp()
        advanceUntilIdle()
        assertEquals(3, (vm.state.value.freeUp as FreeUpState.Preview).preview.count)
        vm.confirmFreeUp()
        advanceUntilIdle()
        val request = effects.filterIsInstance<BackupEffect.DeleteRequest>().single()
        assertEquals(2, request.uris.size) // 999 is no longer on the phone: never part of the request
        media.present -= "101" // the person approved; the system deleted only 101 (102 failed)
        vm.onDeleteResult(approved = true)
        advanceUntilIdle()
        assertTrue(api.calls.single { it.path == "/api/backup/free-up-space/confirm" }.body!!.contains("\"media_ids\":[\"101\"]"))
        assertEquals(FreeUpState.Done(1, 1000), vm.state.value.freeUp)
    }

    @Test
    fun freeUpCancelledDeletesAndReportsNothing() = runTest(main.dispatcher) {
        media.access = MediaAccess.Full
        api.on("GET /api/backup/free-up-space/preview") {
            """{"items":[{"asset_id":"a1","media_id":"101","size_bytes":1000}],"total_bytes":1000,"count":1}"""
        }
        val vm = vm()
        advanceUntilIdle()
        vm.openFreeUp()
        advanceUntilIdle()
        vm.confirmFreeUp()
        advanceUntilIdle()
        vm.onDeleteResult(approved = false)
        advanceUntilIdle()
        assertEquals(FreeUpState.Cancelled, vm.state.value.freeUp)
        assertEquals(0, api.count("POST /api/backup/free-up-space/confirm"))
    }

    @Test
    fun notNowKeepsBackupOffAndRemembersTheCard() = runTest(main.dispatcher) {
        noSources()
        val vm = vm()
        val effects = effects(vm)
        advanceUntilIdle()
        vm.notNow()
        advanceUntilIdle()
        assertEquals(SettingsFixtures.NOW, local.prefs.first().backupPromptDismissedAt)
        assertEquals(BackupEffect.Finished, effects.single())
        assertTrue(LocalSettings.backupPromptVisible(local.prefs.first(), backupOn = false, now = SettingsFixtures.NOW + 6 * 86_400_000L))
        assertFalse(LocalSettings.backupPromptVisible(local.prefs.first(), backupOn = false, now = SettingsFixtures.NOW + 8 * 86_400_000L))
    }

    @Test
    fun pauseAndResumePatchThePolicy() = runTest(main.dispatcher) {
        media.access = MediaAccess.Full
        api.on("PATCH /api/backup/policy") { SettingsFixtures.policy(paused = true) }
        val vm = vm()
        advanceUntilIdle()
        api.on("GET /api/backup/policy") { SettingsFixtures.policy(paused = true) }
        vm.setPaused(true)
        advanceUntilIdle()
        assertTrue(api.calls.single { it.method == "PATCH" && it.path == "/api/backup/policy" }.body!!.contains("\"paused\":true"))
        assertEquals(BackupHeader.Paused(lowBattery = false), vm.state.value.header)
    }
}
