package dev.bento.feature.devices

import dev.bento.data.DevicesRepository
import dev.bento.data.Invalidations
import dev.bento.feature.pairing.PairingRepository
import dev.bento.feature.recovery.VaultRepository
import dev.bento.testing.FakeApiTransport
import dev.bento.testing.MainDispatcherRule
import dev.bento.testing.TrustFixtures
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class DevicesTest {
    @get:Rule
    val main = MainDispatcherRule()

    private val api = FakeApiTransport().apply {
        on("GET /api/vault") { TrustFixtures.vault() }
        on("GET /api/devices") {
            TrustFixtures.devices(
                TrustFixtures.device("d_lap", "Portátil", lastSeen = "2026-11-20T10:00:00+00:00"),
                TrustFixtures.device("d_me", "Pixel 8", platform = "android", current = true),
                TrustFixtures.device("d_new", "Equipo raro", platform = "windows", needsReview = true)
            )
        }
    }
    private fun vm() = DevicesViewModel(DevicesRepository(api.endpoints(), Invalidations()), PairingRepository(api.endpoints()), VaultRepository(api.endpoints()))

    @Test
    fun thisPhoneFirstThenReviews() = runTest(main.dispatcher) {
        val vm = vm()
        advanceUntilIdle()
        assertEquals(listOf("d_me", "d_new", "d_lap"), vm.state.value.devices.map { it.id })
        assertEquals(listOf("d_new"), vm.state.value.pendingReviews.map { it.id })
    }

    @Test
    fun localModeShowsConnect() = runTest(main.dispatcher) {
        api.on("GET /api/vault") { TrustFixtures.vault(state = "signed_out") }
        val vm = vm()
        advanceUntilIdle()
        assertTrue(vm.state.value.localOnly)
        assertEquals(0, api.count("GET /api/devices"))
    }

    @Test
    fun renameAndAcknowledge() = runTest(main.dispatcher) {
        api.on("PATCH /api/devices/d_lap") { TrustFixtures.device("d_lap", "Portátil de Ana") }
        api.on("POST /api/devices/d_new/acknowledge") { TrustFixtures.device("d_new", "Equipo raro", platform = "windows") }
        val vm = vm()
        advanceUntilIdle()
        vm.startRename(vm.state.value.devices.first { it.id == "d_lap" })
        vm.rename("  Portátil de Ana ")
        advanceUntilIdle()
        assertEquals("""{"name":"Portátil de Ana"}""", api.calls.last { it.method == "PATCH" }.body)
        assertNull(vm.state.value.renaming)
        vm.acknowledge(vm.state.value.devices.first { it.id == "d_new" })
        advanceUntilIdle()
        assertTrue(vm.state.value.pendingReviews.isEmpty())
    }

    @Test
    fun removalWithExclusionsYieldsTheMandatoryKit() = runTest(main.dispatcher) {
        api.on("GET /api/devices/d_lap/removal-preview") {
            """{"recipients":[${TrustFixtures.device("d_me", "Pixel 8", current = true)},${TrustFixtures.device("d_new", "Equipo raro", needsReview = true)}]}"""
        }
        api.on("DELETE /api/devices/d_lap") {
            """{"device":${TrustFixtures.device("d_lap", "Portátil")},"telegram_session_closed":false,"recovery_code":"${TrustFixtures.RECOVERY_CODE}",""" +
                """"recovery_qr":${TrustFixtures.QR},"removed_device_ids":["d_lap","d_new"]}"""
        }
        val vm = vm()
        advanceUntilIdle()
        vm.startRemoval(vm.state.value.devices.first { it.id == "d_lap" })
        advanceUntilIdle()
        assertEquals(listOf("d_me", "d_new"), vm.state.value.removal!!.recipients.map { it.id })
        vm.toggleKeep("d_new", keep = false)
        vm.confirmRemoval()
        advanceUntilIdle()
        assertEquals("""{"exclude_device_ids":["d_new"]}""", api.calls.last { it.method == "DELETE" }.body)
        val result = vm.state.value.result!!
        assertEquals(TrustFixtures.RECOVERY_CODE, result.code)
        assertEquals(1, result.alsoRemoved)
        assertTrue(result.sessionOpen)
        assertEquals(listOf("d_me"), vm.state.value.devices.map { it.id })
        vm.kitSaved()
        assertNull(vm.state.value.result)
        assertEquals("Portátil", vm.state.value.notice?.name)
    }

    @Test
    fun changedListAsksToReviewAgain() = runTest(main.dispatcher) {
        api.on("GET /api/devices/d_lap/removal-preview") { """{"recipients":[]}""" }
        api.fail("DELETE /api/devices/d_lap", 400, "device_exclusion_invalid")
        val vm = vm()
        advanceUntilIdle()
        vm.startRemoval(vm.state.value.devices.first { it.id == "d_lap" })
        advanceUntilIdle()
        vm.confirmRemoval()
        advanceUntilIdle()
        assertEquals(2, api.count("GET /api/devices/d_lap/removal-preview"))
    }
}
