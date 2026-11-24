package dev.bento.feature.onboarding

import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.onNodeWithContentDescription
import dev.bento.designsystem.theme.BentoTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(qualifiers = "es-w411dp-h891dp")
class OnboardingUiTest {
    @get:Rule
    val compose = createAndroidComposeRule<ComponentActivity>()

    private fun set(content: @androidx.compose.runtime.Composable () -> Unit) = compose.setContent { BentoTheme { content() } }

    @Test
    fun welcomeOffersTheThreeWaysIn() {
        val taps = mutableListOf<String>()
        set { WelcomeContent(onStart = { taps += "start" }, onJoin = { taps += "join" }, onLocalOnly = { taps += "local" }) }
        compose.onNodeWithText("Tu nube privada, en orden.").assertExists()
        compose.onNodeWithText("Empezar").performClick()
        compose.onNodeWithText("Ya uso Bento en otro dispositivo").performClick()
        compose.onNodeWithText("Usar solo en este teléfono").performClick()
        assertEquals(listOf("start", "join", "local"), taps)
        compose.onNodeWithText("Bento usa la API de Telegram y no está afiliado a Telegram.").assertExists()
    }

    @Test
    fun localModeExplainsWhatItMeans() {
        var confirmed = false
        set { LocalModeSheetBody(onConfirm = { confirmed = true }, onDismiss = {}) }
        compose.onNodeWithText("no se sincroniza", substring = true).assertExists()
        compose.onNodeWithText("Usar solo en este teléfono").performClick()
        assertTrue(confirmed)
    }

    @Test
    fun withoutTheTelegramAppThePhoneIsThePrimaryPath() {
        set { TelegramSignInContent(SignInState(loading = false), telegramAppInstalled = false, actions = SignInActions()) }
        compose.onNodeWithText("Continuar con Telegram").assertDoesNotExist()
        compose.onNodeWithText("Usar mi número de teléfono").assertExists()
        compose.onNodeWithText("No encontramos la app de Telegram", substring = true).assertExists()
    }

    @Test
    fun withTheTelegramAppContinueIsOffered() {
        var continued = false
        set { TelegramSignInContent(SignInState(loading = false), telegramAppInstalled = true, actions = SignInActions(onContinueWithTelegram = { continued = true })) }
        compose.onNodeWithText("Telegram te pedirá confirmar el inicio de sesión de Bento.").assertExists()
        compose.onNodeWithText("Continuar con Telegram").performClick()
        assertTrue(continued)
    }

    @Test
    fun codeAutoSubmitsOnTheLastDigitAndOffersPaste() {
        val submitted = mutableListOf<String>()
        set {
            TelegramSignInContent(
                SignInState(view = SignInView.Code, loading = false, resendSeconds = 42, national = "3001234567", country = PhoneNumbers.preselect("co", null)),
                telegramAppInstalled = true,
                actions = SignInActions(onSubmitCode = { submitted += it }),
                clipboardCode = "54321"
            )
        }
        compose.onNodeWithText("Reenviar en 0:42").assertIsNotEnabled()
        compose.onNodeWithText("Pegar 54321").performClick()
        compose.waitForIdle()
        assertEquals(listOf("54321"), submitted)
    }

    @Test
    fun typingFiveDigitsSubmits() {
        val submitted = mutableListOf<String>()
        set {
            TelegramSignInContent(
                SignInState(view = SignInView.Code, loading = false),
                telegramAppInstalled = false,
                actions = SignInActions(onSubmitCode = { submitted += it })
            )
        }
        compose.onNodeWithContentDescription("Código de Telegram", substring = true).performTextInput("12a345")
        compose.waitForIdle()
        assertEquals(listOf("12345"), submitted)
    }

    @Test
    fun passwordStepIsSecureAndShowsTheHint() {
        set {
            TelegramSignInContent(
                SignInState(
                    view = SignInView.Password,
                    loading = false,
                    status = dev.bento.api.generated.AccountStatusResponse(null, null, "demo", null, null, null, "password_required"),
                    problem = SignInProblem.PasswordInvalid
                ),
                telegramAppInstalled = false,
                actions = SignInActions()
            )
        }
        compose.onNodeWithText("Pista: demo").assertExists()
        compose.onNodeWithText("La contraseña no es correcta. Inténtalo otra vez.").assertExists()
        assertTrue(compose.activity.window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE != 0)
    }

    @Test
    fun floodWaitSaysItRetriesByItself() {
        set {
            TelegramSignInContent(
                SignInState(view = SignInView.Phone, loading = false, problem = SignInProblem.FloodWait, floodWaitSeconds = 180, national = "3001234567"),
                telegramAppInstalled = false,
                actions = SignInActions()
            )
        }
        compose.onNodeWithText("Telegram pidió esperar 3 minutos. Lo intentaremos solo.").assertExists()
        compose.onNodeWithText("Enviar código").assertIsNotEnabled()
    }

    @Test
    fun phoneStepEnablesSendWithAPlausibleNumber() {
        set {
            TelegramSignInContent(SignInState(view = SignInView.Phone, loading = false, national = "3001234567"), telegramAppInstalled = false, actions = SignInActions())
        }
        compose.onNodeWithText("Enviar código").assertIsEnabled()
        compose.onNodeWithText("Código 57").assertExists()
    }

    @Test
    fun creatingStatesAnnounceProgressAndFailure() {
        val ana = dev.bento.api.generated.TelegramAccountResponse("Ana", null, false, 1, "ana")
        set { CreatingContent(ana, null, CreatingState(failed = true), onRetry = {}) }
        compose.onNodeWithText("Conectado como Ana").assertExists()
        compose.onNodeWithText("No se pudo crear tu nube. Tu cuenta sigue intacta.").assertExists()
        compose.onNodeWithText("Reintentar").assertExists()
    }

    @Test
    fun doneGoesToPhotos() {
        var finished = false
        set { DoneContent(onFinish = { finished = true }) }
        compose.onNodeWithContentDescription("Consejo 1 de 3").assertExists()
        compose.onNodeWithText("Ir a mis fotos").performClick()
        assertTrue(finished)
    }

    @Test
    fun notificationsCanBeSkipped() {
        var skipped = false
        set { NotificationsContent(onAllow = {}, onSkip = { skipped = true }) }
        compose.onNodeWithText("Solo te avisaremos del progreso del respaldo y si algo necesita tu atención.").assertExists()
        compose.onNodeWithText("Ahora no").performClick()
        assertTrue(skipped)
    }

    @Test
    @Config(qualifiers = "en-w411dp-h891dp")
    fun englishCopy() {
        set { WelcomeContent({}, {}, {}) }
        compose.onNodeWithText("Your private cloud, in order.").assertExists()
        compose.onNodeWithText("Use only on this phone").assertExists()
    }
}
