package dev.bento.feature.recovery

import androidx.compose.foundation.text.input.TextFieldState
import androidx.compose.ui.test.junit4.createComposeRule
import dev.bento.testing.BentoScreenshots
import dev.bento.testing.TrustFixtures
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** Goldens: feature/recovery/screenshots/<state>/<light|dark|font-200|compact|expanded>.png. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = BentoScreenshots.QUALIFIERS)
class RecoveryScreenshotTest {
    @get:Rule
    val compose = createComposeRule()

    private val code = TrustFixtures.RECOVERY_CODE

    private fun shot(name: String, content: @androidx.compose.runtime.Composable () -> Unit) = BentoScreenshots.capture(compose, "screenshots", name, content)

    private fun kit(ui: RecoveryKitUi, later: Boolean = true, typed: String = "") = shot(
        "kit-${ui.occasion.name.lowercase()}${ui.notice?.let { "-" + it.name.lowercase() }.orEmpty()}${ui.confirm.error?.let { "-" + it.name.lowercase() }.orEmpty()}"
    ) {
        RecoveryKitContent(ui, {}, {}, {}, {}, {}, onLater = if (later) ({}) else null, typed = TextFieldState(typed))
    }

    @Test fun kitFirstRun() = kit(RecoveryKitUi(code, KitOccasion.FirstRun))

    @Test fun kitCopied() = kit(RecoveryKitUi(code, KitOccasion.FirstRun, notice = KitNotice.Copied))

    @Test fun kitMismatch() = kit(RecoveryKitUi(code, KitOccasion.FirstRun, confirm = KitConfirmState(error = KitConfirmError.Mismatch)), typed = "AAAA")

    @Test fun kitAfterRemoval() = kit(RecoveryKitUi(code, KitOccasion.NewAfterRemoval), later = false)

    @Test fun entryEmpty() = shot("entry-empty") { RecoveryEntryContent(RecoveryEntryState(), clipboardCode = code, onSubmit = {}, onEdited = {}) }

    @Test fun entryChecksum() = shot("entry-checksum") {
        RecoveryEntryContent(RecoveryEntryState(error = UnlockError.Checksum), null, {}, {}, code = TextFieldState(code.dropLast(1) + "X"))
    }

    @Test fun entryFailed() = shot("entry-failed") { RecoveryEntryContent(RecoveryEntryState(error = UnlockError.Failed), null, {}, {}, code = TextFieldState(code)) }

    @Test fun entryScanRationale() = shot("entry-scan-rationale") {
        RecoveryEntryContent(RecoveryEntryState(), null, {}, {}, initiallyScanning = true, scanner = { QrScannerPanel({}, { true }, camera = {}, access = CameraAccess.Unknown) })
    }

    @Test fun entryScanDenied() = shot("entry-scan-denied") {
        RecoveryEntryContent(RecoveryEntryState(), null, {}, {}, initiallyScanning = true, scanner = { QrScannerPanel({}, { true }, camera = {}, access = CameraAccess.Denied) })
    }

    @Test fun entryScanning() = shot("entry-scanning") {
        RecoveryEntryContent(RecoveryEntryState(), null, {}, {}, initiallyScanning = true, scanner = { QrScannerPanel({}, { true }, camera = {}, access = CameraAccess.Granted) })
    }

    @Test fun manageSaved() = shot("manage-saved") { RecoveryManageContent(RecoveryManageState(loading = false, status = KitStatus.Saved), {}, {}, {}, {}, {}) }

    @Test fun manageNotSaved() = shot("manage-not-saved") { RecoveryManageContent(RecoveryManageState(loading = false, status = KitStatus.NotSaved), {}, {}, {}, {}, {}) }

    @Test fun manageStale() = shot("manage-stale") { RecoveryManageContent(RecoveryManageState(loading = false, status = KitStatus.Stale), {}, {}, {}, {}, {}) }

    @Test fun manageLoading() = shot("manage-loading") { RecoveryManageContent(RecoveryManageState(), {}, {}, {}, {}, {}) }

    @Test fun manageError() = shot("manage-error") { RecoveryManageContent(RecoveryManageState(loading = false, loadFailed = true), {}, {}, {}, {}, {}) }

    @Test fun manageRotateFailed() = shot("manage-rotate-failed") {
        RecoveryManageContent(RecoveryManageState(loading = false, status = KitStatus.Saved, rotateFailed = true), {}, {}, {}, {}, {})
    }

}
