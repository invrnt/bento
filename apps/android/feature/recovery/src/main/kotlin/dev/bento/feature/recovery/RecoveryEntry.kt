package dev.bento.feature.recovery

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.text.input.TextFieldState
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.foundation.text.input.setTextAndPlaceCursorAtEnd
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dev.bento.designsystem.component.BentoAnnounce
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonSize
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoChip
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.CodeField
import dev.bento.designsystem.component.CrockfordCode
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.strings.R as StringsR
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class UnlockError { Checksum, Invalid, Failed }

data class RecoveryEntryState(val unlocking: Boolean = false, val error: UnlockError? = null, val unlocked: Boolean = false)

/** `POST /vault/unlock` with the kit's code; maps checksum typos and codes of another vault to plain copy. */
@HiltViewModel
class RecoveryEntryViewModel @Inject constructor(private val vault: VaultRepository) : ViewModel() {
    private val _state = MutableStateFlow(RecoveryEntryState())
    val state: StateFlow<RecoveryEntryState> = _state.asStateFlow()

    fun clearError() = _state.update { it.copy(error = null) }

    fun unlock(code: String) {
        val normalized = CrockfordCode.normalize(code)
        if (normalized.length != RecoveryCodes.LENGTH || _state.value.unlocking) return
        _state.update { it.copy(unlocking = true, error = null) }
        viewModelScope.launch {
            when (val result = attempt { vault.unlock(RecoveryCodes.format(normalized)) }) {
                is Outcome.Ok -> _state.update { RecoveryEntryState(unlocked = true) }

                is Outcome.Err -> _state.update {
                    it.copy(unlocking = false, error = unlockError(result.problem))
                }
            }
        }
    }

    companion object {
        fun unlockError(problem: ApiProblem): UnlockError = when {
            RecoveryCodes.isChecksumProblem(problem.code) -> UnlockError.Checksum
            problem.code == "recovery_code_invalid" -> UnlockError.Invalid
            else -> UnlockError.Failed
        }
    }
}

/**
 * Recovery code entry (product/android.md §4.2 "Without the other device"): 9 groups with auto-dash, paste chip,
 * or scan the kit's `bento-recovery:` QR. FLAG_SECURE while shown.
 */
@Composable
fun RecoveryEntryScreen(
    onUnlocked: () -> Unit,
    modifier: Modifier = Modifier,
    onBack: (() -> Unit)? = null,
    camera: CameraSlot = CameraXSlot,
    viewModel: RecoveryEntryViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    var clipboardCode by rememberSaveable { mutableStateOf<String?>(null) }
    LifecycleResumeEffect(Unit) {
        clipboardCode =
            SensitiveClipboard.readText(context)?.let { CrockfordCode.normalize(it) }?.takeIf { it.length == RecoveryCodes.LENGTH }
        onPauseOrDispose {}
    }
    LaunchedEffect(state.unlocked) { if (state.unlocked) onUnlocked() }
    SecureWindow()
    val permission = rememberCameraPermission()
    RecoveryEntryContent(
        state = state,
        clipboardCode = clipboardCode,
        onSubmit = viewModel::unlock,
        onEdited = viewModel::clearError,
        onBack = onBack,
        modifier = modifier,
        scanner = { onScanned ->
            QrScannerPanel(
                onCode = { payload -> RecoveryCodes.fromScan(payload)?.let(onScanned) },
                accept = { RecoveryCodes.fromScan(it) != null },
                camera = camera,
                access = permission.access,
                onRequestAccess = permission.request,
                onOpenSettings = permission.openSettings,
                hint = stringResource(StringsR.string.recovery_entry_scan_hint),
                rejectedMessage = stringResource(StringsR.string.recovery_entry_scan_wrong)
            )
        }
    )
}

@Composable
fun RecoveryEntryContent(
    state: RecoveryEntryState,
    clipboardCode: String?,
    onSubmit: (String) -> Unit,
    onEdited: () -> Unit,
    modifier: Modifier = Modifier,
    onBack: (() -> Unit)? = null,
    code: TextFieldState = rememberTextFieldState(),
    initiallyScanning: Boolean = false,
    scanner: @Composable (onScanned: (String) -> Unit) -> Unit = {}
) {
    var scanning by rememberSaveable { mutableStateOf(initiallyScanning) }
    LaunchedEffect(code) { snapshotFlow { code.text.toString() }.collect { onEdited() } }
    SetupScaffold(
        title = stringResource(StringsR.string.recovery_entry_title),
        body = stringResource(StringsR.string.recovery_entry_body),
        hero = Hero.Icon(BentoIcons.LifeBuoy),
        onBack = onBack,
        modifier = modifier,
        actions = {
            BentoButton(
                text = stringResource(StringsR.string.recovery_entry_submit),
                onClick = { onSubmit(code.text.toString()) },
                modifier = Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Primary,
                size = BentoButtonSize.Large,
                enabled = code.text.length == RecoveryCodes.LENGTH,
                loading = state.unlocking,
                loadingLabel = stringResource(StringsR.string.recovery_entry_unlocking)
            )
        }
    ) {
        if (scanning) {
            scanner { scanned ->
                code.setTextAndPlaceCursorAtEnd(scanned)
                scanning = false
                onSubmit(scanned)
            }
            Spacer(Modifier.height(12.dp))
            BentoButton(
                stringResource(StringsR.string.recovery_entry_type_instead),
                { scanning = false },
                leadingIcon = BentoIcons.Keyboard,
                variant = BentoButtonVariant.Ghost
            )
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                CodeField(
                    state = code,
                    label = stringResource(StringsR.string.recovery_code_label),
                    length = RecoveryCodes.LENGTH,
                    hint = stringResource(StringsR.string.recovery_entry_hint),
                    error = when (state.error) {
                        UnlockError.Checksum -> stringResource(StringsR.string.recovery_error_checksum)
                        UnlockError.Invalid -> stringResource(StringsR.string.recovery_error_invalid)
                        UnlockError.Failed, null -> null
                    },
                    onComplete = onSubmit
                )
                if (clipboardCode != null && code.text.isEmpty()) {
                    BentoChip(
                        label = stringResource(StringsR.string.recovery_entry_paste),
                        onClick = { code.setTextAndPlaceCursorAtEnd(clipboardCode) },
                        leadingIcon = BentoIcons.ClipboardPaste
                    )
                }
                BentoButton(
                    stringResource(StringsR.string.recovery_entry_scan),
                    { scanning = true },
                    leadingIcon = BentoIcons.ScanLine,
                    variant = BentoButtonVariant.Secondary
                )
                if (state.error == UnlockError.Failed) {
                    Callout(
                        tone = CalloutTone.Danger,
                        body = stringResource(StringsR.string.recovery_error_failed),
                        announce = BentoAnnounce.Assertive
                    )
                }
            }
        }
    }
}
