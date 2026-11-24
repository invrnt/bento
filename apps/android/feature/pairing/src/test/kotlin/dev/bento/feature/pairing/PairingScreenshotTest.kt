package dev.bento.feature.pairing

import androidx.compose.runtime.Composable
import androidx.compose.ui.test.junit4.createComposeRule
import dev.bento.api.BentoJson
import dev.bento.api.generated.PairingResponse
import dev.bento.feature.recovery.CameraAccess
import dev.bento.feature.recovery.QrScannerPanel
import dev.bento.testing.BentoScreenshots
import dev.bento.testing.TrustFixtures
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = BentoScreenshots.QUALIFIERS)
class PairingScreenshotTest {
    @get:Rule
    val compose = createComposeRule()

    private fun shot(name: String, content: @Composable () -> Unit) = BentoScreenshots.capture(compose, "screenshots", name, content)
    private fun p(json: String) = BentoJson.decodeFromString(PairingResponse.serializer(), json)
    private val sas = TrustFixtures.SAS

    @Composable
    private fun join(state: JoinState, access: CameraAccess = CameraAccess.Unknown, clipboard: String? = null) =
        JoinContent(state, JoinActions(), clipboardCode = clipboard, scanner = { QrScannerPanel({}, { true }, camera = {}, access = access) })

    @Composable
    private fun guest(pairing: String, state: JoinState = JoinState()) = join(state.copy(step = JoinStep.Pairing, pairing = p(pairing)))

    @Test fun entryScanRationale() = shot("join-scan-rationale") { join(JoinState(step = JoinStep.Entry)) }

    @Test fun entryScanning() = shot("join-scanning") { join(JoinState(step = JoinStep.Entry), access = CameraAccess.Granted) }

    @Test fun entryScanDenied() = shot("join-scan-denied") { join(JoinState(step = JoinStep.Entry), access = CameraAccess.Denied) }

    @Test fun entryType() = shot("join-code") { join(JoinState(step = JoinStep.Entry, entryMode = EntryMode.Type), clipboard = "K7Q2MXR9T4WA") }

    @Test fun entryPrefilled() = shot("join-code-prefilled") { join(JoinState(step = JoinStep.Entry, entryMode = EntryMode.Type, prefill = "K7Q2MXR9T4WA")) }

    @Test fun entryWrongCode() = shot("join-code-wrong") {
        join(JoinState(step = JoinStep.Entry, entryMode = EntryMode.Type, prefill = "K7Q2MXR9T4WX", joinProblem = PairingProblem.WrongCode))
    }

    @Test fun entryRelay() = shot("join-relay-unavailable") {
        join(JoinState(step = JoinStep.Entry, entryMode = EntryMode.Type, prefill = "K7Q2MXR9T4WA", joinProblem = PairingProblem.RelayUnavailable))
    }

    @Test fun connecting() = shot("join-connecting") { guest(TrustFixtures.pairing("connected")) }

    @Test fun confirmComputer() = shot("join-confirm-computer") { guest(TrustFixtures.pairing("awaiting_approval", sas = sas)) }

    @Test fun receiving() = shot("join-receiving") { guest(TrustFixtures.pairing("approving", sas = sas)) }

    @Test fun fallbackWaiting() = shot("join-fallback-waiting") { guest(TrustFixtures.pairing("waiting", transport = "telegram", peer = null)) }

    @Test fun fallbackMatch() = shot("join-fallback-match") { guest(TrustFixtures.pairing("awaiting_approval", transport = "telegram", sas = sas, vault = true, peer = null)) }

    @Test fun fallbackConfirmed() = shot("join-fallback-confirmed") { guest(TrustFixtures.pairing("approving", transport = "telegram", sas = sas, vault = true, peer = null)) }

    @Test fun mismatch() = shot("join-mismatch") { guest(TrustFixtures.pairing("cancelled", transport = "telegram"), JoinState(mismatch = true)) }

    @Test fun telegramLogin() = shot("join-needs-telegram-login") {
        guest(TrustFixtures.pairing("needs_telegram_login", telegramQr = true), JoinState(guestLogin = GuestLogin(loginUrl = "tg://login?token=x")))
    }

    @Test fun telegramPassword() = shot("join-needs-telegram-password") {
        guest(TrustFixtures.pairing("needs_telegram_login"), JoinState(guestLogin = GuestLogin(passwordRequired = true, passwordHint = "el perro", passwordInvalid = true)))
    }

    @Test fun rejected() = shot("join-rejected") { guest(TrustFixtures.pairing("rejected")) }

    @Test fun expired() = shot("join-expired") { guest(TrustFixtures.pairing("expired")) }

    @Test fun deviceRemoved() = shot("join-failed-device-removed") { guest(TrustFixtures.pairing("failed", error = "pairing_device_removed")) }

    @Test fun choose() = shot("join-choose") { join(JoinState(step = JoinStep.Choose)) }

    @Test fun chooseAmbiguous() = shot("join-choose-ambiguous") { join(JoinState(step = JoinStep.Choose, requestProblem = PairingProblem.VaultAmbiguous)) }

    @Test fun noVault() = shot("join-no-vault") { join(JoinState(step = JoinStep.NoVault)) }

    @Test fun bootstrap() = shot("join-bootstrap") { join(JoinState(step = JoinStep.Bootstrap, bootstrap = BootstrapProgress(1240, 3000))) }

    @Test fun bootstrapDone() = shot("join-bootstrap-done") { join(JoinState(step = JoinStep.Bootstrap, bootstrap = BootstrapProgress(3000, 3000, finished = true))) }

    @Test fun already() = shot("join-already") { join(JoinState(step = JoinStep.Already)) }

    @Composable
    private fun host(state: HostState) = HostPairingContent(state, {}, {}, {}, {}, { true }, {})

    private val hostCode = TrustFixtures.pairing("waiting", role = "host", code = "K7Q2-MXR9-T4WA", peer = null)

    @Test fun hostLoading() = shot("host-loading") { host(HostState()) }

    @Test fun hostCode() = shot("host-code") { host(HostState(pairing = p(hostCode), starting = false, secondsLeft = 287)) }

    @Test fun hostApprove() = shot("host-approve") { host(HostState(pairing = p(TrustFixtures.pairing("awaiting_approval", role = "host", sas = sas, peer = "Pixel 8", platform = "android")), starting = false)) }

    @Test fun hostGuestLogin() = shot("host-guest-login") { host(HostState(pairing = p(TrustFixtures.pairing("needs_telegram_login", role = "host")), starting = false)) }

    @Test fun hostCompleted() = shot("host-completed") { host(HostState(pairing = p(TrustFixtures.pairing("completed", role = "host")), starting = false)) }

    @Test fun hostRejected() = shot("host-rejected") { host(HostState(pairing = p(TrustFixtures.pairing("rejected", role = "host")), starting = false)) }

    @Test fun hostExpired() = shot("host-expired") { host(HostState(pairing = p(hostCode), starting = false, secondsLeft = 0)) }

    @Test fun hostRelay() = shot("host-relay-unavailable") { host(HostState(starting = false, startProblem = PairingProblem.RelayUnavailable)) }

    @Test fun hostFailed() = shot("host-start-failed") { host(HostState(starting = false, startProblem = PairingProblem.Generic)) }

    @Test fun requestReview() = shot("request-review") {
        PairingRequestContent(RequestReviewState(loading = false, pairing = p(TrustFixtures.pairing("awaiting_approval", role = "host", transport = "telegram", sas = sas, peer = "Pixel 8", platform = "android"))), {}, {}, {})
    }

    @Test fun requestTaken() = shot("request-taken") { PairingRequestContent(RequestReviewState(loading = false, problem = PairingProblem.RequestTaken), {}, {}, {}) }

    @Test fun requestDeviceRemoved() = shot("request-device-removed") { PairingRequestContent(RequestReviewState(loading = false, problem = PairingProblem.DeviceRemoved), {}, {}, {}) }
}
