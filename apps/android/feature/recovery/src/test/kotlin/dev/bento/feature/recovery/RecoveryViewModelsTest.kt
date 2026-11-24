package dev.bento.feature.recovery

import dev.bento.testing.FakeApiTransport
import dev.bento.testing.MainDispatcherRule
import dev.bento.testing.TrustFixtures
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class RecoveryViewModelsTest {
    @get:Rule
    val main = MainDispatcherRule()

    private val api = FakeApiTransport()
    private val vault = VaultRepository(api.endpoints())
    private val code = TrustFixtures.RECOVERY_CODE

    @Test
    fun kitMismatchIsCaughtLocallyWithoutACall() = runTest(main.dispatcher) {
        val vm = RecoveryKitViewModel(vault)
        vm.confirm(code, "AAAA")
        advanceUntilIdle()
        assertEquals(KitConfirmError.Mismatch, vm.state.value.error)
        assertEquals(0, api.calls.size)
    }

    @Test
    fun kitConfirmSendsOnlyTheLastGroup() = runTest(main.dispatcher) {
        api.on("POST /api/vault/recovery-code/confirm") { TrustFixtures.vault(saved = true) }
        val vm = RecoveryKitViewModel(vault)
        vm.confirm(code, "yprt")
        advanceUntilIdle()
        assertTrue(vm.state.value.confirmed)
        assertEquals("""{"last_group":"YPRT"}""", api.calls.single().body)
    }

    @Test
    fun kitConfirmFailureIsRetryable() = runTest(main.dispatcher) {
        api.fail("POST /api/vault/recovery-code/confirm", 503, "telegram_network")
        val vm = RecoveryKitViewModel(vault)
        vm.confirm(code, "YPRT")
        advanceUntilIdle()
        assertEquals(KitConfirmError.Failed, vm.state.value.error)
        assertFalse(vm.state.value.confirming)
    }

    @Test
    fun unlockMapsErrorsAndSucceeds() = runTest(main.dispatcher) {
        api.fail("POST /api/vault/unlock", 400, "recovery_checksum_invalid")
        val vm = RecoveryEntryViewModel(vault)
        vm.unlock(code.lowercase())
        advanceUntilIdle()
        assertEquals(UnlockError.Checksum, vm.state.value.error)

        api.fail("POST /api/vault/unlock", 400, "recovery_code_invalid")
        vm.unlock(code)
        advanceUntilIdle()
        assertEquals(UnlockError.Invalid, vm.state.value.error)

        api.on("POST /api/vault/unlock") { TrustFixtures.vault(state = "bootstrapping") }
        vm.unlock(code)
        advanceUntilIdle()
        assertTrue(vm.state.value.unlocked)
        assertEquals("""{"recovery_code":"${RecoveryCodes.format(code)}"}""", api.calls.last().body)
    }

    @Test
    fun incompleteCodesAreNotSent() = runTest(main.dispatcher) {
        val vm = RecoveryEntryViewModel(vault)
        vm.unlock("K7QM-3XRA")
        advanceUntilIdle()
        assertEquals(0, api.calls.size)
    }

    @Test
    fun manageStatusRotateAndVerify() = runTest(main.dispatcher) {
        api.on("GET /api/vault") { TrustFixtures.vault(stale = true) }
        val vm = RecoveryManageViewModel(vault)
        advanceUntilIdle()
        assertEquals(KitStatus.Stale, vm.state.value.status)

        api.on("POST /api/vault/recovery-code") { TrustFixtures.recoveryCode() }
        vm.rotate()
        advanceUntilIdle()
        val fresh = vm.state.value.fresh
        assertNotNull(fresh)
        assertEquals(code, fresh!!.code)
        assertEquals("2026-11-24T10:00:00+00:00", fresh.createdAt)

        api.on("GET /api/vault") { TrustFixtures.vault(saved = true) }
        vm.kitDone()
        advanceUntilIdle()
        assertNull(vm.state.value.fresh)
        assertEquals(KitStatus.Saved, vm.state.value.status)

        api.on("POST /api/vault/recovery-code/verify") { """{"valid":false}""" }
        vm.verify(code)
        advanceUntilIdle()
        assertEquals(VerifyResult.Invalid, vm.state.value.verifyResult)
    }

    @Test
    fun manageLoadFailureShowsRetry() = runTest(main.dispatcher) {
        api.fail("GET /api/vault", 503, "engine_unavailable")
        val vm = RecoveryManageViewModel(vault)
        advanceUntilIdle()
        assertTrue(vm.state.value.loadFailed)
    }
}
