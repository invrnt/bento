package dev.bento.feature.pairing

import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import dev.bento.api.BentoJson
import dev.bento.api.generated.PairingResponse
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.testing.TrustFixtures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(qualifiers = "es-w411dp-h891dp")
class PairingUiTest {
    @get:Rule
    val compose = createAndroidComposeRule<ComponentActivity>()

    private fun p(json: String) = BentoJson.decodeFromString(PairingResponse.serializer(), json)

    @Test
    fun sasEmojisAreOneTalkBackSentence() {
        compose.setContent {
            BentoTheme { JoinContent(JoinState(step = JoinStep.Pairing, pairing = p(TrustFixtures.pairing("awaiting_approval", sas = TrustFixtures.SAS))), JoinActions()) }
        }
        compose.onNodeWithContentDescription("Emojis de verificación: 🐙 🌵 🎈 🚀").assertExists()
        compose.onNodeWithText("Confirma en tu computador").assertExists()
    }

    @Test
    fun fallbackGuestMustAnswerCoinciden() {
        val taps = mutableListOf<String>()
        compose.setContent {
            BentoTheme {
                JoinContent(
                    JoinState(step = JoinStep.Pairing, pairing = p(TrustFixtures.pairing("awaiting_approval", transport = "telegram", sas = TrustFixtures.SAS, vault = true, peer = null))),
                    JoinActions(onMatch = { taps += "match" }, onNoMatch = { taps += "no" })
                )
            }
        }
        compose.onNodeWithText("Creada el", substring = true).assertExists()
        compose.onNodeWithText("Coinciden").performClick()
        compose.onNodeWithText("No coinciden").performClick()
        assertEquals(listOf("match", "no"), taps)
    }

    @Test
    fun relayUnavailableOffersTelegramInstead() {
        var signIn = false
        compose.setContent {
            BentoTheme {
                JoinContent(JoinState(step = JoinStep.Entry, entryMode = EntryMode.Type, joinProblem = PairingProblem.RelayUnavailable), JoinActions(onNoDevice = { signIn = true }))
            }
        }
        compose.onNodeWithText("Iniciar sesión en Telegram").performClick()
        assertTrue(signIn)
    }

    @Test
    fun hostCodeIsSecureAndSpelledForTalkBack() {
        compose.setContent {
            BentoTheme {
                HostPairingContent(
                    HostState(pairing = p(TrustFixtures.pairing("waiting", role = "host", code = "K7Q2-MXR9-T4WA", peer = null)), starting = false, secondsLeft = 125),
                    {}, {}, {}, {}, { true }, {}
                )
            }
        }
        // FLAG_SECURE is set by HostPairingContent's code phase.
        compose.waitForIdle()
        assertTrue(compose.activity.window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE != 0)
        compose.onNodeWithContentDescription("Código: K 7 Q 2 M X R 9 T 4 W A").assertExists()
        compose.onNodeWithText("Caduca en 2:05").assertExists()
        compose.onNodeWithText("Compartir enlace").assertExists()
    }

    @Test
    fun requestTakenIsExplained() {
        compose.setContent { BentoTheme { PairingRequestContent(RequestReviewState(loading = false, problem = PairingProblem.RequestTaken), {}, {}, {}) } }
        compose.onNodeWithText("Otro dispositivo respondió a esta solicitud. Si no fuiste tú, cancela en el dispositivo nuevo.").assertExists()
    }
}
