package dev.bento.feature.settings

import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsOff
import androidx.compose.ui.test.assertIsOn
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import dev.bento.designsystem.theme.BentoTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Compose UI of agent 41's settings: permission states, policy toggles, free-up preview/confirm, lock and reset. */
@RunWith(RobolectricTestRunner::class)
@Config(qualifiers = "es-w411dp-h891dp")
class SettingsUiTest {
    @get:Rule
    val compose = createComposeRule()

    private val buckets = listOf(
        BucketRow("b_cam", "Cámara", 120, suggested = true, sourceId = "s1", enabled = true, pending = 3),
        BucketRow("b_wa", "WhatsApp Images", 300, suggested = false)
    )
    private val settings = PhoneSettings(revision = 1)

    private fun backup(state: BackupUiState, actions: BackupActions = BackupActions()) = compose.setContent {
        BentoTheme { BackupSettingsContent(state, actions, now = 0, onBack = {}) }
    }

    @Test
    fun grantedShowsFoldersHeaderAndToggles() {
        val taps = mutableListOf<String>()
        backup(
            BackupUiState(
                loading = false,
                access = MediaAccess.Full,
                location = true,
                buckets = buckets,
                settings = settings,
                status = BackupStatus(pending = 340, waiting = mapOf("wifi" to 340)),
                policy = BackupPolicy()
            ),
            BackupActions(
                onWifiOnly = { taps += "wifi:$it" },
                onOnlyCharging = { taps += "charging:$it" },
                onBucket = { row, on -> taps += "${row.bucketId}:$on" },
                onRunNow = { taps += "now" }
            )
        )
        compose.onNodeWithText("Quedan 340 · esperando Wi-Fi").assertExists()
        compose.onNodeWithText("Respaldar ahora").performScrollTo().performClick()
        compose.onNodeWithText("WhatsApp Images").performScrollTo().performClick()
        compose.onNodeWithText("Solo con Wi-Fi").performScrollTo().assertIsOn().performClick()
        compose.onNodeWithText("Solo mientras carga").performScrollTo().assertIsOff().performClick()
        assertEquals(listOf("now", "b_wa:true", "wifi:false", "charging:true"), taps)
    }

    @Test
    fun partialAccessCardOffersAllowAllAndChooseMore() {
        val taps = mutableListOf<String>()
        backup(
            BackupUiState(loading = false, access = MediaAccess.Partial, visibleCount = 12, buckets = buckets, settings = settings),
            BackupActions(onAllowAll = { taps += "all" }, onChooseMore = { taps += "more" })
        )
        compose.onNodeWithText("Bento solo ve 12 fotos").assertExists()
        compose.onNodeWithText("Permitir todas").performClick()
        compose.onNodeWithText("Elegir más").performClick()
        assertEquals(listOf("all", "more"), taps)
    }

    @Test
    fun deniedKeepsBackupOffWithAWorkingPath() {
        val taps = mutableListOf<String>()
        backup(
            BackupUiState(
                loading = false,
                access = MediaAccess.Denied,
                deniedThisSession = true,
                permanentlyDenied = true,
                buckets = buckets.map {
                    it.copy(enabled = false)
                }
            ),
            BackupActions(onOpenSettings = { taps += "settings" })
        )
        compose.onNodeWithText("El respaldo está apagado").assertExists()
        compose.onNodeWithText("El respaldo sigue apagado").assertExists()
        compose.onNodeWithText("Abrir ajustes del teléfono").performClick()
        assertEquals(listOf("settings"), taps)
    }

    @Test
    fun revokedLaterShowsTheCard() {
        val taps = mutableListOf<String>()
        backup(
            BackupUiState(loading = false, access = MediaAccess.Denied, buckets = buckets),
            BackupActions(onTurnOn = { taps += "on" })
        )
        compose.onNodeWithText("Bento ya no puede ver tus fotos").assertExists()
        compose.onNodeWithText("Permitir acceso").performClick()
        assertEquals(listOf("on"), taps)
    }

    @Test
    fun freeUpPreviewConfirmAndDone() {
        var confirmed = 0
        var state by mutableStateOf<FreeUpState>(
            FreeUpState.Preview(FreeUpPreview(listOf(FreeUpItem("a1", "101", 3_200_000_000)), 3_200_000_000, 1))
        )
        compose.setContent { BentoTheme { FreeUpSheetBody(state, BackupActions(onFreeUpConfirm = { confirmed++ })) } }
        compose.onNodeWithText("1 foto ya está en tu nube · 3,2 GB").assertExists()
        compose.onNodeWithText("Liberar 3,2 GB en este teléfono").performClick()
        assertEquals(1, confirmed)
        state = FreeUpState.Done(1, 3_200_000_000)
        compose.onNodeWithText("Listo: se liberaron 3,2 GB (1 foto)").assertExists()
        state = FreeUpState.Cancelled
        compose.onNodeWithText("No se borró nada del teléfono.").assertExists()
    }

    @Test
    fun onboardingStepOffersBackupAndNotNow() {
        val taps = mutableListOf<String>()
        compose.setContent {
            BentoTheme {
                BackupSetupContent(
                    BackupUiState(loading = false, settings = settings),
                    BackupActions(onTurnOn = {
                        taps += "on"
                    }, onNotNow = {
                        taps +=
                            "later"
                    })
                )
            }
        }
        compose.onNodeWithText("Solo con Wi-Fi").assertIsOn()
        compose.onNodeWithText("Solo mientras carga").assertIsOff()
        compose.onNodeWithText("Respaldar fotos").performClick()
        compose.onNodeWithText("Ahora no").performClick()
        assertEquals(listOf("on", "later"), taps)
    }

    @Test
    fun lockNeedsAScreenLockAndShowsTimeoutsWhenOn() {
        val taps = mutableListOf<String>()
        var state by mutableStateOf(SettingsUiState(loading = false, lockAvailable = false))
        compose.setContent {
            BentoTheme {
                GeneralPage(state, SettingsActions(onLock = { taps += "lock:$it" }, onLockTimeout = { taps += it.name }), onBack = {})
            }
        }
        compose.onNodeWithText("Configura un bloqueo de pantalla en el teléfono para usarlo.").assertExists()
        state = SettingsUiState(loading = false, lockAvailable = true, prefs = LocalPrefs(lockEnabled = true))
        compose.onNodeWithText("5 min").performScrollTo().performClick()
        compose.onNodeWithText("Ocultar contenido en apps recientes").performScrollTo().assertIsEnabled()
        assertEquals(listOf("FiveMinutes"), taps)
    }

    @Test
    fun resetNeedsTheTypedWord() {
        var reset = 0
        compose.setContent {
            BentoTheme { ResetSheetBody("RESTABLECER", rememberTextFieldState(), SettingsActions(onReset = { reset++ })) }
        }
        compose.onNodeWithText("Restablecer este teléfono").assertIsNotEnabled()
        compose.onNode(
            hasSetTextAction() and hasContentDescription("Escribe RESTABLECER", substring = true)
        ).performTextInput("restablecer")
        compose.onNodeWithText("Restablecer este teléfono").assertIsEnabled().performClick()
        assertEquals(1, reset)
    }
}
