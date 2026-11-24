package dev.bento.feature.onboarding

import androidx.test.core.app.ApplicationProvider
import dev.bento.api.BentoHttp
import dev.bento.feature.recovery.VaultRepository
import dev.bento.testing.FakeApiTransport
import dev.bento.testing.MainDispatcherRule
import dev.bento.testing.TrustFixtures
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class OnboardingViewModelsTest {
    @get:Rule
    val main = MainDispatcherRule()

    private val api = FakeApiTransport()

    /** The avatar endpoint is binary (BentoHttp); with no engine it simply yields no avatar. */
    private val http = BentoHttp(
        OkHttpClient(),
        object : dev.bento.api.EndpointProvider {
            override suspend fun ready(): dev.bento.engine.EngineState.Ready = throw dev.bento.api.ApiException.EngineUnavailable()
        }
    )
    private val login = LoginRepository(api.endpoints(), http)
    private val store = GateStore(ApplicationProvider.getApplicationContext())

    private fun signIn() = TelegramSignInViewModel(login)

    @Test
    fun phoneThenCodeThenAuthorized() = runTest(main.dispatcher) {
        api.on("GET /api/account") { TrustFixtures.account("signed_out") }
        api.on("POST /api/account/login/phone") { TrustFixtures.account("code_required") }
        api.on("POST /api/account/login/code") { TrustFixtures.account("authorized") }
        val vm = signIn()
        vm.start("co", null)
        advanceUntilIdle()
        assertEquals(SignInView.Options, vm.state.value.view)
        vm.usePhone()
        vm.editNational("300 123 4567")
        vm.submitPhone()
        runCurrent()
        assertEquals(SignInView.Code, vm.state.value.view)
        assertEquals("""{"phone":"+573001234567"}""", api.calls.last().body)
        assertEquals(60, vm.state.value.resendSeconds)
        advanceTimeBy(10_500)
        assertEquals(50, vm.state.value.resendSeconds)
        vm.submitCode("12 345")
        advanceUntilIdle()
        assertEquals("""{"code":"12345"}""", api.calls.last().body)
        assertEquals("Ana", vm.state.value.authorized?.displayName)
    }

    @Test
    fun implausibleNumberIsCaughtBeforeTelegram() = runTest(main.dispatcher) {
        api.on("GET /api/account") { TrustFixtures.account("signed_out") }
        val vm = signIn()
        vm.start("co", null)
        advanceUntilIdle()
        vm.usePhone()
        vm.editNational("123")
        vm.submitPhone()
        advanceUntilIdle()
        assertEquals(SignInProblem.PhoneInvalid, vm.state.value.problem)
        assertEquals(0, api.count("POST /api/account/login/phone"))
    }

    @Test
    fun wrongCodeAndPasswordStep() = runTest(main.dispatcher) {
        api.on("GET /api/account") { TrustFixtures.account("code_required") }
        api.on("POST /api/account/login/code") { TrustFixtures.account("code_required", error = "telegram_code_invalid") }
        val vm = signIn()
        vm.start(null, null)
        advanceUntilIdle()
        assertEquals(SignInView.Code, vm.state.value.view)
        vm.submitCode("11111")
        advanceUntilIdle()
        assertEquals(SignInProblem.CodeInvalid, vm.state.value.problem)

        api.on("POST /api/account/login/code") { TrustFixtures.account("password_required", hint = "demo") }
        vm.submitCode("12345")
        advanceUntilIdle()
        assertEquals(SignInView.Password, vm.state.value.view)
        assertEquals("demo", vm.state.value.status?.passwordHint)

        api.on("POST /api/account/login/password") { TrustFixtures.account("password_required", error = "telegram_password_invalid", hint = "demo") }
        vm.submitPassword("nope")
        advanceUntilIdle()
        assertEquals(SignInProblem.PasswordInvalid, vm.state.value.problem)
    }

    @Test
    fun floodWaitCountsDownAndRetriesByItself() = runTest(main.dispatcher) {
        api.on("GET /api/account") { TrustFixtures.account("signed_out") }
        var calls = 0
        api.on("POST /api/account/login/phone") {
            calls++
            if (calls == 1) TrustFixtures.account("signed_out", error = "telegram_flood_wait", retryAfter = 3) else TrustFixtures.account("code_required")
        }
        val vm = signIn()
        vm.start("co", null)
        advanceUntilIdle()
        vm.usePhone()
        vm.editNational("3001234567")
        vm.submitPhone()
        runCurrent()
        assertEquals(SignInProblem.FloodWait, vm.state.value.problem)
        assertEquals(3L, vm.state.value.floodWaitSeconds)
        advanceTimeBy(1_100)
        assertEquals(2L, vm.state.value.floodWaitSeconds)
        advanceTimeBy(2_500)
        runCurrent()
        assertEquals(2, calls)
        assertEquals(SignInView.Code, vm.state.value.view)
        assertNull(vm.state.value.problem)
    }

    @Test
    fun continueWithTelegramOpensTheLinkAndPollsUntilAuthorized() = runTest(main.dispatcher) {
        var status = TrustFixtures.account("qr_pending", qrUrl = "tg://login?token=abc", expiresAt = "2099-01-01T00:00:00+00:00")
        api.on("GET /api/account") { status }
        api.on("POST /api/account/login/qr") { TrustFixtures.account("qr_pending", qrUrl = "tg://login?token=abc", expiresAt = "2099-01-01T00:00:00+00:00") }
        val vm = signIn()
        vm.start(null, null)
        advanceUntilIdle()
        vm.continueWithTelegram()
        runCurrent()
        assertEquals(SignInEffect.OpenTelegramLogin("tg://login?token=abc"), vm.effect.first())
        assertTrue(vm.state.value.awaitingTelegramApp)
        status = TrustFixtures.account("authorized")
        advanceTimeBy(TelegramSignInViewModel.POLL_MS + 100)
        assertNotNull(vm.state.value.authorized)
        assertFalse(vm.state.value.awaitingTelegramApp)
    }

    @Test
    fun telegramAppMissingFallsBackToPhone() = runTest(main.dispatcher) {
        api.on("GET /api/account") { TrustFixtures.account("signed_out") }
        val vm = signIn()
        vm.start(null, null)
        advanceUntilIdle()
        vm.telegramAppMissing()
        assertEquals(SignInView.Phone, vm.state.value.view)
        assertEquals(SignInProblem.TelegramAppMissing, vm.state.value.problem)
    }

    @Test
    fun networkErrorsAreCalm() = runTest(main.dispatcher) {
        api.on("GET /api/account") { TrustFixtures.account("signed_out") }
        api.fail("POST /api/account/login/phone", 503, "telegram_network")
        val vm = signIn()
        vm.start("co", null)
        advanceUntilIdle()
        vm.usePhone()
        vm.editNational("3001234567")
        vm.submitPhone()
        advanceUntilIdle()
        assertEquals(SignInProblem.Network, vm.state.value.problem)
        assertFalse(vm.state.value.busy)
    }

    private fun onboarding() = OnboardingViewModel(VaultRepository(api.endpoints()), login, AppGateResolver(VaultRepository(api.endpoints()), store))

    private val ana = dev.bento.api.generated.TelegramAccountResponse("Ana", null, false, 1, "ana")

    @Test
    fun createsTheVaultKeepsTheKitInMemoryAndHandsOffToBackup() = runTest(main.dispatcher) {
        api.on("GET /api/vault") { TrustFixtures.vault(state = "no_vault", vaultId = null) }
        api.on("POST /api/vault") { TrustFixtures.createdVault() }
        val vm = onboarding()
        vm.start()
        vm.authorized(ana)
        assertEquals(OnboardingStep.Creating, vm.state.value.step)
        advanceUntilIdle()
        assertEquals(OnboardingEffect.OpenBackupSetup, vm.effect.first())
        assertEquals(OnboardingStep.Notifications, vm.state.value.step)
        assertEquals(TrustFixtures.RECOVERY_CODE, vm.state.value.kit?.code)
        vm.notificationsDone()
        assertEquals(OnboardingStep.Kit, vm.state.value.step)
        vm.kitDone()
        assertNull(vm.state.value.kit)
        assertEquals(OnboardingStep.Done, vm.state.value.step)
        vm.finish()
        assertEquals(OnboardingEffect.Finished, vm.effect.first())
        assertTrue(store.cachedApp)
    }

    @Test
    fun existingCloudGoesToJoin() = runTest(main.dispatcher) {
        api.on("GET /api/vault") { TrustFixtures.vault(state = "locked") }
        val vm = onboarding()
        vm.authorized(ana)
        advanceUntilIdle()
        assertEquals(OnboardingEffect.ExistingVault, vm.effect.first())
        assertEquals(0, api.count("POST /api/vault"))
    }

    @Test
    fun alreadyExistsConflictGoesToJoin() = runTest(main.dispatcher) {
        api.on("GET /api/vault") { TrustFixtures.vault(state = "no_vault") }
        api.fail("POST /api/vault", 409, "vault_already_exists")
        val vm = onboarding()
        vm.authorized(ana)
        advanceUntilIdle()
        assertEquals(OnboardingEffect.ExistingVault, vm.effect.first())
    }

    @Test
    fun failedCreationOffersRetry() = runTest(main.dispatcher) {
        api.on("GET /api/vault") { TrustFixtures.vault(state = "no_vault") }
        api.fail("POST /api/vault", 503, "telegram_network")
        val vm = onboarding()
        vm.authorized(ana)
        advanceUntilIdle()
        assertTrue(vm.state.value.creating.failed)
        vm.create()
        advanceUntilIdle()
        assertEquals(2, api.count("POST /api/vault"))
    }

    @Test
    fun localModeIsRememberedAndFinishes() = runTest(main.dispatcher) {
        val vm = onboarding()
        vm.confirmLocalMode()
        assertEquals(OnboardingEffect.Finished, vm.effect.first())
        assertTrue(store.localMode)
        assertTrue(store.cachedApp)
    }

    @Test
    fun reconnectFindsTheReadyCloud() = runTest(main.dispatcher) {
        api.on("GET /api/vault") { TrustFixtures.vault(state = "ready") }
        val vm = onboarding()
        vm.begin(reconnect = true)
        assertEquals(OnboardingStep.Reconnect, vm.state.value.step)
        vm.reconnected()
        advanceUntilIdle()
        assertEquals(OnboardingEffect.Finished, vm.effect.first())
    }
}
