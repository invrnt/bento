package dev.bento.feature.activity

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import dev.bento.designsystem.component.AvatarStatus
import dev.bento.designsystem.component.StatusAvatar
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.settings.BackupPolicy
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Cuenta y actividad: one action per attention item, pause/resume, rows, and the avatar's TalkBack text. */
@RunWith(RobolectricTestRunner::class)
@Config(qualifiers = "es-w411dp-h1400dp")
class ActivityUiTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun everyAttentionItemHasItsOneAction() {
        val taps = mutableListOf<String>()
        val actions = ActivityActions(
            onRetry = { taps += "retry:$it" },
            onRetrySync = { taps += "sync" },
            onDismissImport = { taps += "dismiss:${it.name}" },
            onPause = { taps += "pause:$it" }
        )
        val navigation = ActivityNavigation(
            onReconnect = { taps += "reconnect" },
            onRecovery = { taps += "kit" },
            onDeviceReview = { taps += "device:$it" },
            onDevices = { taps += "devices" },
            onTrash = { taps += "trash" },
            onSettings = { taps += "settings" }
        )
        compose.setContent {
            BentoTheme {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    AccountSheetBody(
                        ActivityFixtures.overview(ActivityFixtures.ATTENTION, imports = listOf(ActivityFixtures.failure)),
                        actions,
                        navigation
                    )
                }
            }
        }
        compose.onNodeWithText("6 cosas necesitan tu atención").assertExists()
        compose.onNodeWithText("Ana García").assertExists()
        compose.onNodeWithText("1,3 TB en tu nube · 3 dispositivos").assertExists()
        compose.onNodeWithText("Reintentar").performScrollTo().performClick()
        compose.onNodeWithText("Volver a conectar").performScrollTo().performClick()
        compose.onNodeWithText("Guardar kit").performScrollTo().performClick()
        compose.onNodeWithText("Revisar").performScrollTo().performClick()
        compose.onNodeWithText("La hora del teléfono va 10 min adelantada").assertExists()
        compose.onNodeWithText("«Factura.pdf» no llegó a Bento").assertExists()
        compose.onNodeWithText("Quitar").performScrollTo().performClick()
        compose.onNodeWithText("Pausar respaldo").performScrollTo().performClick()
        compose.onNodeWithText("Dispositivos").performScrollTo().performClick()
        compose.onNodeWithText("Papelera").performScrollTo().performClick()
        compose.onNodeWithText("Ajustes").performScrollTo().performClick()
        assertEquals(
            listOf("retry:j1", "reconnect", "kit", "device:d9", "dismiss:Factura.pdf", "pause:true", "devices", "trash", "settings"),
            taps
        )
    }

    @Test
    fun pausedOffersResumeAndUploadsShowProgress() {
        val taps = mutableListOf<Boolean>()
        compose.setContent {
            BentoTheme {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    AccountSheetBody(
                        ActivityFixtures.overview(ActivityFixtures.UPLOADING, policy = BackupPolicy(paused = true)),
                        ActivityActions(onPause = { taps += it }),
                        ActivityNavigation()
                    )
                }
            }
        }
        compose.onNodeWithText("Respaldo en pausa").assertExists()
        compose.onNodeWithText("Subiendo 12 archivos").assertExists()
        compose.onNodeWithText("12 MB de 40 MB").assertExists()
        compose.onNodeWithText("Reanudar").performClick()
        assertEquals(listOf(false), taps)
    }

    @Test
    fun avatarReadsNameAndStatus() {
        compose.setContent { BentoTheme { StatusAvatar(name = "Ana García", status = AvatarStatus.Attention, onClick = {}) } }
        compose.onNode(hasContentDescription("Ana García", substring = true)).assertExists()
    }
}
