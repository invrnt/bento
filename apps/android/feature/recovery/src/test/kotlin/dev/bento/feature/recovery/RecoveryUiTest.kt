package dev.bento.feature.recovery

import android.content.ClipDescription
import android.content.ClipboardManager
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.compose.foundation.text.input.TextFieldState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ApplicationProvider
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.testing.FakeApiTransport
import dev.bento.testing.TrustFixtures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(qualifiers = "es-w411dp-h891dp")
class RecoveryUiTest {
    @get:Rule
    val compose = createAndroidComposeRule<ComponentActivity>()

    private val code = TrustFixtures.RECOVERY_CODE
    private fun secure(): Boolean = compose.activity.window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE != 0

    @Test
    fun kitSetsFlagSecureAndClearsItWhenLeaving() {
        var shown by mutableStateOf(true)
        compose.setContent {
            BentoTheme {
                if (shown) {
                    RecoveryKitScreen(code, null, KitOccasion.FirstRun, onConfirmed = {}, onLater = {}, viewModel = RecoveryKitViewModel(VaultRepository(FakeApiTransport().endpoints())))
                }
            }
        }
        compose.waitForIdle()
        assertTrue("FLAG_SECURE on the recovery kit", secure())
        shown = false
        compose.waitForIdle()
        assertFalse("FLAG_SECURE cleared after the kit", secure())
    }

    @Test
    fun nestedSecureScreensKeepTheFlagUntilTheLastOneLeaves() {
        var outer by mutableStateOf(true)
        var inner by mutableStateOf(true)
        compose.setContent {
            if (outer) SecureWindow()
            if (inner) SecureWindow()
        }
        compose.waitForIdle()
        inner = false
        compose.waitForIdle()
        assertTrue(secure())
        outer = false
        compose.waitForIdle()
        assertFalse(secure())
    }

    @Test
    fun kitReadsTheCodeForTalkBackAndConfirmNeedsFourCharacters() {
        val typed = TextFieldState()
        var confirmed: String? = null
        compose.setContent {
            BentoTheme {
                RecoveryKitContent(
                    ui = RecoveryKitUi(code, KitOccasion.FirstRun),
                    onCopy = {},
                    onSavePdf = {},
                    onPrint = {},
                    onConfirm = { confirmed = it },
                    onTypedChange = {},
                    onLater = {},
                    typed = typed
                )
            }
        }
        compose.onNodeWithContentDescription("Código de recuperación: K 7 Q M", substring = true).assertExists()
        compose.onNodeWithText("Confirmar").assertIsNotEnabled()
        compose.runOnIdle { typed.edit { replace(0, length, "YPRT") } }
        compose.onNodeWithText("Confirmar").assertIsEnabled().performClick()
        assertEquals("YPRT", confirmed)
        compose.onNodeWithText("Más tarde").assertExists()
    }

    @Test
    fun mandatoryKitHasNoLater() {
        compose.setContent {
            BentoTheme {
                RecoveryKitContent(RecoveryKitUi(code, KitOccasion.NewAfterRemoval), {}, {}, {}, {}, {}, onLater = null)
            }
        }
        compose.onNodeWithText("Guarda tu nuevo kit de recuperación").assertExists()
        compose.onNodeWithText("Más tarde").assertDoesNotExist()
    }

    @Test
    fun copyMarksTheClipSensitive() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        assertTrue(SensitiveClipboard.copy(context, RecoveryCodes.format(code)))
        val clipboard = context.getSystemService(ClipboardManager::class.java)
        val description = clipboard.primaryClipDescription!!
        assertTrue(description.extras!!.getBoolean(ClipDescription.EXTRA_IS_SENSITIVE))
        assertEquals(RecoveryCodes.format(code), SensitiveClipboard.readText(context))
        // The scheduled clear only removes our own clip.
        SensitiveClipboard.clearIfOurs(clipboard, "someone-else")
        assertTrue(clipboard.hasPrimaryClip())
        SensitiveClipboard.clearIfOurs(clipboard, description.label.toString())
        assertFalse(clipboard.hasPrimaryClip() && clipboard.primaryClip!!.itemCount > 0 && clipboard.primaryClip!!.getItemAt(0).text != null)
    }

    @Test
    fun entryShowsChecksumErrorAndPasteChip() {
        val field = TextFieldState()
        compose.setContent {
            BentoTheme {
                RecoveryEntryContent(RecoveryEntryState(error = UnlockError.Checksum), clipboardCode = code, onSubmit = {}, onEdited = {}, code = field)
            }
        }
        compose.onNodeWithText("Revisa el código: algún carácter no es correcto.").assertExists()
        compose.onNodeWithText("Pegar el código copiado").performClick()
        assertEquals(code, field.text.toString())
        compose.onNodeWithText("Desbloquear").assertIsEnabled()
    }

    @Test
    fun entryEnablesUnlockOnlyWithAFullCodeAndSetsFlagSecure() {
        compose.setContent {
            BentoTheme { RecoveryEntryScreen(onUnlocked = {}, camera = {}, viewModel = RecoveryEntryViewModel(VaultRepository(FakeApiTransport().endpoints()))) }
        }
        compose.onNodeWithText("Desbloquear").assertIsNotEnabled()
        assertTrue(secure())
    }

    @Test
    fun scannerDeniedFallsBackToTyping() {
        var settings = false
        compose.setContent {
            BentoTheme { QrScannerPanel(onCode = {}, accept = { true }, camera = {}, access = CameraAccess.Denied, onOpenSettings = { settings = true }) }
        }
        compose.onNodeWithText("Sin acceso a la cámara", substring = true).assertExists()
        compose.onNodeWithText("Abrir Ajustes").performClick()
        assertTrue(settings)
    }

    @Test
    fun scannerAsksWithARationaleFirst() {
        var asked = false
        compose.setContent {
            BentoTheme { QrScannerPanel(onCode = {}, accept = { true }, camera = {}, access = CameraAccess.Unknown, onRequestAccess = { asked = true }) }
        }
        compose.onNodeWithText("Bento usa la cámara solo para leer el código QR. No guarda imágenes.").assertExists()
        compose.onNodeWithText("Permitir cámara").performClick()
        assertTrue(asked)
    }

    @Test
    fun scannerReportsTheFirstAcceptedCodeOnceAndExplainsWrongOnes() {
        val codes = mutableListOf<String>()
        compose.setContent {
            BentoTheme {
                QrScannerPanel(
                    onCode = { codes += it },
                    accept = { it.startsWith("bento-recovery:") },
                    camera = { decoded ->
                        androidx.compose.runtime.LaunchedEffect(Unit) {
                            decoded("https://example.com")
                            decoded("bento-recovery:$code")
                            decoded("bento-recovery:$code")
                        }
                    },
                    access = CameraAccess.Granted,
                    rejectedMessage = "wrong"
                )
            }
        }
        compose.waitForIdle()
        assertEquals(listOf("bento-recovery:$code"), codes)
        compose.onNodeWithText("wrong").assertExists()
    }

    @Test
    fun manageStaleOffersANewCodeAndDisablesVerify() {
        compose.setContent {
            BentoTheme { RecoveryManageContent(RecoveryManageState(loading = false, status = KitStatus.Stale), {}, {}, {}, {}, {}) }
        }
        compose.onNodeWithText("Ya no sirve").assertExists()
        compose.onNodeWithText("Verificar código").assertIsNotEnabled()
        compose.onNodeWithText("Generar nuevo código").assertIsEnabled()
    }
}
