package dev.bento.feature.devices

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import dev.bento.api.BentoJson
import dev.bento.api.generated.DeviceResponse
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.testing.TrustFixtures
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(qualifiers = "es-w411dp-h891dp")
class DevicesUiTest {
    @get:Rule
    val compose = createComposeRule()

    private fun d(json: String) = BentoJson.decodeFromString(DeviceResponse.serializer(), json)

    @Test
    fun reviewCardActions() {
        val taps = mutableListOf<String>()
        val device = d(TrustFixtures.device("d_new", "Equipo raro", platform = "windows", needsReview = true))
        compose.setContent { BentoTheme { ReviewCard(device, busy = false, failed = false, actions = DevicesActions(onAcknowledge = { taps += "mine" }, onRemove = { taps += "remove" })) } }
        compose.onNodeWithText("Se añadió «Equipo raro · Windows» a tu nube").assertExists()
        compose.onNodeWithText("Es mío").performClick()
        compose.onNodeWithText("No lo reconozco").performClick()
        assertEquals(listOf("mine", "remove"), taps)
    }

    @Test
    fun removalStatesConsequencesAndCountsExclusions() {
        val removal = RemovalState(
            device = d(TrustFixtures.device("d_lap", "Portátil")),
            loadingPreview = false,
            recipients = listOf(d(TrustFixtures.device("d_me", "Pixel 8", platform = "android", current = true)), d(TrustFixtures.device("d_new", "Equipo raro", needsReview = true))),
            excluded = setOf("d_new")
        )
        var confirmed = false
        compose.setContent { BentoTheme { RemovalSheetBody(removal, DevicesActions(onConfirmRemoval = { confirmed = true })) } }
        compose.onNodeWithText("Dejará de sincronizarse y se cerrará su sesión de Telegram.").assertExists()
        compose.onNodeWithText("También se quitará 1 dispositivo más").assertExists()
        compose.onNodeWithText("Este teléfono: siempre conserva el acceso").assertExists()
        compose.onNodeWithText("Quitar 2 dispositivos").performClick()
        assertEquals(true, confirmed)
    }

    @Test
    fun listShowsThisPhoneAndRequests() {
        val state = DevicesState(
            loading = false,
            devices = listOf(d(TrustFixtures.device("d_me", "Pixel 8", platform = "android", current = true))),
            requests = listOf(dev.bento.api.generated.PairingRequestItem("2026-11-24T10:00:00+00:00", "Pixel 9", "req_1", "android"))
        )
        var reviewed: String? = null
        compose.setContent { BentoTheme { DevicesContent(state, DevicesActions(onReviewRequest = { reviewed = it })) } }
        compose.onNodeWithText("Este teléfono").assertExists()
        compose.onNodeWithText("Revisar").performClick()
        assertEquals("req_1", reviewed)
    }
}
