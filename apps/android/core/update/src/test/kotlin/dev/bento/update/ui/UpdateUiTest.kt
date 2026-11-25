package dev.bento.update.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.update.UpdateFailure
import dev.bento.update.UpdateState
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(qualifiers = "es-w411dp-h891dp")
class UpdateUiTest {
    @get:Rule
    val compose = createComposeRule()

    private val taps = mutableListOf<String>()
    private val actions = UpdateActions(
        onCheck = { taps += "check" },
        onDownload = { taps += "download" },
        onCancel = { taps += "cancel" },
        onInstall = { taps += "install" },
        onOpenSettings = { taps += "settings" },
        onDismiss = { taps += "dismiss" },
        onRetry = { taps += "retry" }
    )

    private fun card(state: UpdateState) = compose.setContent { BentoTheme { UpdateCardContent(state, actions) } }

    @Test
    fun availableCardDownloadsOrDismisses() {
        card(UpdateState.Available(release130))
        compose.onNodeWithText("Hay una versión nueva").assertExists()
        compose.onNodeWithText("Descargar").performClick()
        compose.onNodeWithText("Ahora no").performClick()
        assertEquals(listOf("download", "dismiss"), taps)
    }

    @Test
    fun downloadingCardCancels() {
        card(UpdateState.Downloading(release130, 0.42f))
        compose.onNodeWithText("Descargando Bento 1.3.0").assertExists()
        compose.onNodeWithText("Cancelar").performClick()
        assertEquals(listOf("cancel"), taps)
    }

    @Test
    fun readyCardInstalls() {
        card(UpdateState.Ready(release130))
        compose.onNodeWithText("Lista para instalar").assertExists()
        compose.onNodeWithText("Instalar").performClick()
        assertEquals(listOf("install"), taps)
    }

    @Test
    fun permissionCardOpensSettings() {
        card(UpdateState.Ready(release130, needsPermission = true))
        compose.onNodeWithText("Abrir Ajustes").performClick()
        assertEquals(listOf("settings"), taps)
    }

    @Test
    fun failedCardRetries() {
        card(UpdateState.Failed(UpdateFailure.Checksum, release130))
        compose.onNodeWithText("El archivo descargado no coincide con la versión firmada y se borró.").assertExists()
        compose.onNodeWithText("Reintentar").performClick()
        assertEquals(listOf("retry"), taps)
    }

    @Test
    fun cardNeverSaysOk() {
        card(UpdateState.Available(release130))
        assertEquals(0, compose.onAllNodesWithText("OK").fetchSemanticsNodes().size)
        assertEquals(0, compose.onAllNodesWithText("Aceptar").fetchSemanticsNodes().size)
    }

    @Test
    fun rowChecksWhenIdleAndIsDisabledWhenUnavailable() {
        var state by androidx.compose.runtime.mutableStateOf<UpdateState>(UpdateState.Idle(null, upToDate = true))
        compose.setContent { BentoTheme { UpdateRowContent(state, "1.2.0", actions) } }
        compose.onNodeWithText("Tienes la versión más reciente").performClick()
        compose.onNodeWithText("Versión 1.2.0").assertExists()
        assertEquals(listOf("check"), taps)
        state = UpdateState.Unavailable
        compose.onNodeWithText("Actualizaciones").assertExists()
        compose.onNodeWithText("Esta compilación no busca actualizaciones").assertExists()
        compose.onNodeWithText("Actualizaciones").assertIsNotEnabled()
    }

    @Test
    fun rowDownloadsAvailableVersion() {
        compose.setContent { BentoTheme { UpdateRowContent(UpdateState.Available(release130), "1.2.0", actions) } }
        compose.onNodeWithText("Hay una versión nueva: 1.3.0").performClick()
        assertEquals(listOf("download"), taps)
    }
}
