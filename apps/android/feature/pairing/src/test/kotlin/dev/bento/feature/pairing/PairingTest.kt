package dev.bento.feature.pairing

import androidx.lifecycle.viewModelScope
import androidx.test.core.app.ApplicationProvider
import dev.bento.api.BentoHttp
import dev.bento.feature.onboarding.AppGateResolver
import dev.bento.feature.onboarding.GateStore
import dev.bento.feature.onboarding.LoginRepository
import dev.bento.feature.recovery.VaultRepository
import dev.bento.testing.FakeApiTransport
import dev.bento.testing.MainDispatcherRule
import dev.bento.testing.TrustFixtures
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class PairingTest {
    @get:Rule
    val main = MainDispatcherRule()

    private val api = FakeApiTransport()
    private val repo = PairingRepository(api.endpoints())
    private val http = BentoHttp(
        OkHttpClient(),
        object : dev.bento.api.EndpointProvider {
            override suspend fun ready(): dev.bento.engine.EngineState.Ready = throw dev.bento.api.ApiException.EngineUnavailable()
        }
    )
    private val vault = VaultRepository(api.endpoints())
    private val store = GateStore(ApplicationProvider.getApplicationContext())

    /** Sessions that never end on their own keep polling; stop them so runTest can finish. */
    private fun stop(vararg vms: androidx.lifecycle.ViewModel) = vms.forEach { it.viewModelScope.cancel() }

    private fun join() = JoinViewModel(repo, vault, LoginRepository(api.endpoints(), http), AppGateResolver(vault, store))

    @Test
    fun problemMapping() {
        assertEquals(PairingProblem.RequestTaken, pairingProblem("pairing_request_taken"))
        assertEquals(PairingProblem.DeviceRemoved, pairingProblem("pairing_device_removed"))
        assertEquals(PairingProblem.VaultAmbiguous, pairingProblem("pairing_vault_ambiguous"))
        assertEquals(PairingProblem.RelayUnavailable, pairingProblem("relay_unreachable"))
        assertEquals(PairingProblem.NotFound, pairingProblem("room_not_found"))
        assertEquals(PairingProblem.NotFound, pairingProblem("pairing_expired"))
        assertEquals(PairingProblem.RateLimited, pairingProblem("rate_limited"))
        assertEquals(PairingProblem.WrongCode, pairingProblem("pairing_protocol"))
        assertEquals(PairingProblem.Network, pairingProblem("network_error"))
        assertEquals(PairingProblem.Generic, pairingProblem(null))
    }

    @Test
    fun codesFromScansAndPastes() {
        assertEquals("K7Q2MXR9T4WA", PairingCodes.fromScanOrPaste("bento://join?v=1&c=K7Q2-MXR9-T4WA"))
        assertEquals("K7Q2MXR9T4WA", PairingCodes.fromScanOrPaste("https://bento.example/join#v=1&c=k7q2-mxr9-t4wa"))
        assertEquals("K7Q2MXR9T4WA", PairingCodes.fromScanOrPaste("k7q2-mxr9-t4wa"))
        assertNull(PairingCodes.fromScanOrPaste("K7Q2MXR9T4WA"))
        assertNull(PairingCodes.fromScanOrPaste("https://evil.example/other#c=K7Q2-MXR9-T4WA"))
        assertNull(PairingCodes.fromScanOrPaste("bento-recovery:${TrustFixtures.RECOVERY_CODE}"))
    }

    @Test
    fun deviceLabels() {
        assertEquals("Portátil · Linux", DeviceLabels.displayName("Portátil", "Linux"))
        assertEquals("Mac de Ana macOS", DeviceLabels.displayName("Mac de Ana macOS", "macOS"))
        assertTrue(DeviceLabels.isComputer("windows"))
    }

    @Test
    fun linksPrefillButNeverAutoJoin() = runTest(main.dispatcher) {
        api.on("GET /api/vault") { TrustFixtures.vault(state = "signed_out") }
        val vm = join()
        vm.start("K7Q2-MXR9-T4WA", choose = false)
        advanceUntilIdle()
        assertEquals(JoinStep.Entry, vm.state.value.step)
        assertEquals(EntryMode.Type, vm.state.value.entryMode)
        assertEquals("K7Q2MXR9T4WA", vm.state.value.prefill)
        assertEquals(0, api.count("POST /api/pairing/join"))
    }

    @Test
    fun alreadyMemberSeesAlready() = runTest(main.dispatcher) {
        api.on("GET /api/vault") { TrustFixtures.vault(state = "ready") }
        val vm = join()
        vm.start(null, choose = false)
        advanceUntilIdle()
        assertEquals(JoinStep.Already, vm.state.value.step)
    }

    @Test
    fun relayJoinFollowsToBootstrapAndLandsInPhotos() = runTest(main.dispatcher) {
        api.on("GET /api/vault") { TrustFixtures.vault(state = "signed_out") }
        api.on("POST /api/pairing/join") { TrustFixtures.pairing("connected") }
        var state = TrustFixtures.pairing("awaiting_approval", sas = TrustFixtures.SAS)
        api.on("GET /api/pairing/pair_1") { state }
        api.on("GET /api/sync/status") { TrustFixtures.sync("bootstrapping", 1240, 3000) }
        val vm = join()
        vm.start(null, false)
        advanceUntilIdle()
        vm.join("K7Q2-MXR9-T4WA")
        runCurrent()
        assertEquals(JoinStep.Pairing, vm.state.value.step)
        assertEquals("""{"code":"K7Q2-MXR9-T4WA"}""", api.calls.first { it.path == "/api/pairing/join" }.body)
        advanceTimeBy(1_100)
        assertEquals(TrustFixtures.SAS, vm.state.value.pairing?.sas)
        state = TrustFixtures.pairing("bootstrapping")
        advanceTimeBy(1_100)
        assertEquals(JoinStep.Bootstrap, vm.state.value.step)
        assertEquals(1240L, vm.state.value.bootstrap.done)
        advanceTimeBy(2_600)
        assertEquals(JoinEffect.Done, vm.effect.first())
        assertTrue(store.cachedApp)
    }

    @Test
    fun wrongCodeAndRelayProblemsStayOnEntry() = runTest(main.dispatcher) {
        api.on("GET /api/vault") { TrustFixtures.vault(state = "signed_out") }
        api.fail("POST /api/pairing/join", 400, "pairing_code_mismatch")
        val vm = join()
        vm.start(null, false)
        advanceUntilIdle()
        vm.join("K7Q2MXR9T4WA")
        advanceUntilIdle()
        assertEquals(PairingProblem.WrongCode, vm.state.value.joinProblem)
        api.fail("POST /api/pairing/join", 503, "relay_unavailable")
        vm.join("K7Q2MXR9T4WA")
        advanceUntilIdle()
        assertEquals(PairingProblem.RelayUnavailable, vm.state.value.joinProblem)
        assertEquals(JoinStep.Entry, vm.state.value.step)
    }

    @Test
    fun fallbackRequiresCoincidenAndNoCoincidenCancels() = runTest(main.dispatcher) {
        api.on("GET /api/vault") { TrustFixtures.vault(state = "locked") }
        val awaiting = TrustFixtures.pairing(
            "awaiting_approval",
            transport = "telegram",
            sas = TrustFixtures.SAS,
            vault = true,
            peer = null
        )
        api.on("POST /api/pairing/request") { awaiting }
        api.on("GET /api/pairing/pair_1") { awaiting }
        api.on("POST /api/pairing/pair_1/confirm") {
            TrustFixtures.pairing("approving", transport = "telegram", sas = TrustFixtures.SAS, vault = true, peer = null)
        }
        api.on("DELETE /api/pairing/pair_1") { TrustFixtures.pairing("cancelled", transport = "telegram") }
        val vm = join()
        vm.start(null, choose = true)
        advanceUntilIdle()
        assertEquals(JoinStep.Choose, vm.state.value.step)
        vm.requestAccess()
        runCurrent()
        assertTrue(PairingRepository.needsGuestConfirmation(vm.state.value.pairing!!))
        vm.confirmMatch()
        runCurrent()
        assertEquals("approving", vm.state.value.pairing?.state)

        // The first session keeps polling, so time never goes idle: step it explicitly.
        val other = join()
        other.start(null, choose = true)
        runCurrent()
        other.requestAccess()
        runCurrent()
        other.rejectMatch()
        runCurrent()
        assertTrue(other.state.value.mismatch)
        assertEquals(1, api.count("DELETE /api/pairing/pair_1"))
        assertEquals(1, api.count("POST /api/pairing/pair_1/confirm"))
        stop(vm, other)
    }

    @Test
    fun removedIdentityAndTakenRequestsSurface() = runTest(main.dispatcher) {
        api.on("GET /api/vault") { TrustFixtures.vault(state = "signed_out") }
        api.on("POST /api/pairing/join") { TrustFixtures.pairing("connected") }
        api.on("GET /api/pairing/pair_1") { TrustFixtures.pairing("rejected", error = "pairing_device_removed") }
        val vm = join()
        vm.start(null, false)
        advanceUntilIdle()
        vm.join("K7Q2MXR9T4WA")
        advanceTimeBy(1_100)
        assertEquals("rejected", vm.state.value.pairing?.state)

        api.on("POST /api/pairing/requests/req_1/review") {
            throw dev.bento.api.ApiErrors.from(409, """{"error":{"code":"pairing_request_taken","message":"x"}}""")
        }
        val review = PairingRequestViewModel(repo)
        review.review("req_1")
        advanceUntilIdle()
        assertEquals(PairingProblem.RequestTaken, review.state.value.problem)
    }

    @Test
    fun phoneLoginDuringPairingKeepsThePairingAndResumesItsCode() = runTest(main.dispatcher) {
        api.on("GET /api/vault") { TrustFixtures.vault(state = "signed_out") }
        api.on("POST /api/pairing/join") { TrustFixtures.pairing("needs_telegram_login", telegramQr = true) }
        api.on("GET /api/pairing/pair_1") { TrustFixtures.pairing("needs_telegram_login") }
        api.on("GET /api/account") { TrustFixtures.account("signed_out") }
        val vm = join()
        vm.start(null, false)
        advanceUntilIdle()
        vm.join("K7Q2MXR9T4WA")
        advanceTimeBy(500)
        assertEquals(JoinStep.Pairing, vm.state.value.step)
        assertFalse(vm.state.value.guestLogin.phone)
        vm.usePhoneDuringPairing()
        assertTrue(vm.state.value.guestLogin.phone)
        assertEquals(JoinStep.Pairing, vm.state.value.step)
        assertEquals("the pairing is not cancelled", 0, api.count("DELETE /api/pairing/pair_1"))
        vm.phoneLoginClosed()
        assertFalse(vm.state.value.guestLogin.phone)
        // A phone login already waiting for its code (screen recreated) resumes there.
        api.on("GET /api/account") { TrustFixtures.account("code_required") }
        advanceTimeBy(1_100)
        assertTrue(vm.state.value.guestLogin.phone)
        api.on("GET /api/pairing/pair_1") { TrustFixtures.pairing("cancelled") }
        advanceTimeBy(1_100)
    }

    @Test
    fun engineRestartEndsTheSessionAsNotFound() = runTest(main.dispatcher) {
        api.on("GET /api/vault") { TrustFixtures.vault(state = "signed_out") }
        api.on("POST /api/pairing/join") { TrustFixtures.pairing("connected") }
        val vm = join()
        vm.start(null, false)
        advanceUntilIdle()
        vm.join("K7Q2MXR9T4WA")
        advanceTimeBy(1_100)
        assertEquals("failed", vm.state.value.pairing?.state)
        assertEquals(PairingProblem.NotFound, pairingProblem(vm.state.value.pairing?.error?.code))
    }

    @Test
    fun hostShowsCodeThenApprovesAndCancelsWhenLeaving() = runTest(main.dispatcher) {
        api.on("POST /api/pairing/host") { TrustFixtures.pairing("waiting", role = "host", code = "K7Q2-MXR9-T4WA", peer = null) }
        api.on("GET /api/pairing/pair_1") { TrustFixtures.pairing("awaiting_approval", role = "host", sas = TrustFixtures.SAS) }
        api.on("POST /api/pairing/pair_1/approve") { TrustFixtures.pairing("approving", role = "host", sas = TrustFixtures.SAS) }
        val vm = HostPairingViewModel(repo, backgroundScope)
        runCurrent()
        assertEquals(HostPhase.Code, vm.state.value.phase)
        advanceTimeBy(1_100)
        assertEquals(HostPhase.Approve, vm.state.value.phase)
        vm.decide(true)
        runCurrent()
        assertEquals(HostPhase.Approving, vm.state.value.phase)

        api.on("DELETE /api/pairing/pair_1") { TrustFixtures.pairing("cancelled", role = "host") }
        vm.close()
        vm.close()
        runCurrent()
        assertEquals(1, api.count("DELETE /api/pairing/pair_1"))
        stop(vm)
    }

    @Test
    fun hostRelayUnavailableExplainsTheFallback() = runTest(main.dispatcher) {
        api.fail("POST /api/pairing/host", 503, "relay_unavailable")
        val vm = HostPairingViewModel(repo, backgroundScope)
        advanceUntilIdle()
        assertEquals(HostPhase.RelayUnavailable, vm.state.value.phase)
    }
}
