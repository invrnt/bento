package dev.bento.feature.onboarding

import androidx.compose.runtime.Composable
import androidx.compose.ui.test.junit4.createComposeRule
import dev.bento.api.BentoJson
import dev.bento.api.generated.AccountStatusResponse
import dev.bento.api.generated.TelegramAccountResponse
import dev.bento.testing.BentoScreenshots
import dev.bento.testing.TrustFixtures
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** Goldens: feature/onboarding/screenshots/<state>/<variant>.png. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = BentoScreenshots.QUALIFIERS)
class OnboardingScreenshotTest {
    @get:Rule
    val compose = createComposeRule()

    private fun shot(name: String, content: @Composable () -> Unit) = BentoScreenshots.capture(compose, "screenshots", name, content)

    private fun landscape(name: String, content: @Composable () -> Unit) =
        BentoScreenshots.captureLandscape(compose, "screenshots", name, content)

    private val co = PhoneNumbers.preselect("co", null)
    private val ana = TelegramAccountResponse("Ana", "+57 ••• 12", false, 1, "ana")
    private fun status(json: String) = BentoJson.decodeFromString(AccountStatusResponse.serializer(), json)

    @Composable
    private fun signIn(state: SignInState, app: Boolean = true, clipboard: String? = null) {
        TelegramSignInContent(
            state.copy(loading = false, country = co),
            telegramAppInstalled = app,
            actions = SignInActions(),
            clipboardCode = clipboard
        )
    }

    @Test fun welcome() = shot("welcome") { WelcomeContent({}, {}, {}) }

    @Test
    @Config(qualifiers = BentoScreenshots.LANDSCAPE_QUALIFIERS)
    fun welcomeLandscape() = landscape("welcome") { WelcomeContent({}, {}, {}) }

    @Test fun localSheet() = shot("local-mode-sheet") { LocalModeSheetBody({}, {}) }

    @Test fun signInOptions() = shot("signin-options") { signIn(SignInState()) }

    @Test fun signInNoTelegramApp() = shot("signin-no-telegram-app") { signIn(SignInState(), app = false) }

    @Test fun signInWaitingTelegram() = shot("signin-waiting-telegram") { signIn(SignInState(awaitingTelegramApp = true)) }

    @Test fun phone() = shot("signin-phone") { signIn(SignInState(view = SignInView.Phone, national = "3001234567")) }

    @Test fun phoneInvalid() = shot("signin-phone-invalid") {
        signIn(SignInState(view = SignInView.Phone, national = "300", problem = SignInProblem.PhoneInvalid))
    }

    @Test fun phoneFloodWait() = shot("signin-phone-flood-wait") {
        signIn(SignInState(view = SignInView.Phone, national = "3001234567", problem = SignInProblem.FloodWait, floodWaitSeconds = 180))
    }

    @Test fun phoneNetwork() = shot("signin-phone-network") {
        signIn(SignInState(view = SignInView.Phone, national = "3001234567", problem = SignInProblem.Network))
    }

    @Test fun code() = shot("signin-code") {
        signIn(SignInState(view = SignInView.Code, national = "3001234567", resendSeconds = 42), clipboard = "54321")
    }

    @Test
    @Config(qualifiers = BentoScreenshots.LANDSCAPE_QUALIFIERS)
    fun codeLandscape() = landscape("signin-code") {
        signIn(SignInState(view = SignInView.Code, national = "3001234567", resendSeconds = 42), clipboard = "54321")
    }

    @Test fun codeInvalid() = shot("signin-code-invalid") {
        signIn(SignInState(view = SignInView.Code, national = "3001234567", problem = SignInProblem.CodeInvalid))
    }

    @Test fun codeExpired() = shot("signin-code-expired") {
        signIn(SignInState(view = SignInView.Code, national = "3001234567", problem = SignInProblem.Expired))
    }

    @Test fun password() = shot("signin-password") {
        signIn(SignInState(view = SignInView.Password, status = status(TrustFixtures.account("password_required", hint = "el perro"))))
    }

    @Test fun passwordInvalid() = shot("signin-password-invalid") {
        signIn(
            SignInState(
                view = SignInView.Password,
                status = status(TrustFixtures.account("password_required", hint = "el perro")),
                problem = SignInProblem.PasswordInvalid
            )
        )
    }

    @Test fun qr() = shot("signin-qr") {
        signIn(SignInState(view = SignInView.Qr, status = status(TrustFixtures.account("qr_pending", qrUrl = "tg://x"))))
    }

    @Test fun creating() = shot("creating") { CreatingContent(ana, null, CreatingState(), {}) }

    @Test fun creatingProgress() = shot("creating-progress") {
        CreatingContent(
            ana,
            null,
            CreatingState(
                steps = mapOf(
                    "files" to "done",
                    "sync" to "done",
                    "inbox" to "running",
                    "header" to "pending",
                    "device" to "pending"
                )
            ),
            {}
        )
    }

    @Test fun reconnectChecking() = shot("reconnect-checking") { CheckingContent() }

    @Test fun creatingSlow() = shot("creating-slow") { CreatingContent(ana, null, CreatingState(slow = true), {}) }

    @Test fun creatingDone() = shot("creating-done") { CreatingContent(ana, null, CreatingState(done = true), {}) }

    @Test fun creatingFailed() = shot("creating-failed") { CreatingContent(ana, null, CreatingState(failed = true), {}) }

    @Test fun notifications() = shot("notifications") { NotificationsContent({}, {}) }

    @Test fun done() = shot("done") { DoneContent({}) }

    @Test fun reconnect() = shot("reconnect") { ReconnectContent({}, {}) }
}
