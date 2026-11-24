package dev.bento.feature.recovery

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.input.TextFieldState
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dev.bento.api.generated.VaultStatusResponse
import dev.bento.designsystem.component.Badge
import dev.bento.designsystem.component.BentoAnnounce
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonSize
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoDialog
import dev.bento.designsystem.component.BentoSheet
import dev.bento.designsystem.component.BentoTone
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.CodeField
import dev.bento.designsystem.component.ErrorState
import dev.bento.designsystem.component.LoadingState
import dev.bento.designsystem.component.QrMatrix
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.strings.R as StringsR
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Kit status in Ajustes › Cuenta y nube. */
enum class KitStatus { Saved, NotSaved, Stale }

data class FreshKit(val code: String, val qr: QrMatrix?, val createdAt: String?)

data class RecoveryManageState(
    val loading: Boolean = true,
    val loadFailed: Boolean = false,
    val status: KitStatus? = null,
    val rotating: Boolean = false,
    val rotateFailed: Boolean = false,
    val fresh: FreshKit? = null,
    val verifying: Boolean = false,
    val verifyResult: VerifyResult? = null
)

enum class VerifyResult { Valid, Invalid, Failed }

@HiltViewModel
class RecoveryManageViewModel @Inject constructor(private val vault: VaultRepository) : ViewModel() {
    private val _state = MutableStateFlow(RecoveryManageState())
    val state: StateFlow<RecoveryManageState> = _state.asStateFlow()
    private var createdAt: String? = null

    init {
        load()
    }

    fun load() {
        _state.update { it.copy(loading = true, loadFailed = false) }
        viewModelScope.launch {
            when (val result = attempt { vault.status() }) {
                is Outcome.Ok -> {
                    createdAt = result.value.createdAt
                    _state.update { it.copy(loading = false, status = statusOf(result.value)) }
                }

                is Outcome.Err -> _state.update { it.copy(loading = false, loadFailed = true) }
            }
        }
    }

    fun rotate() {
        if (_state.value.rotating) return
        _state.update { it.copy(rotating = true, rotateFailed = false) }
        viewModelScope.launch {
            when (val result = attempt { vault.rotate() }) {
                is Outcome.Ok -> _state.update {
                    it.copy(rotating = false, fresh = FreshKit(result.value.recoveryCode, result.value.recoveryQr.toMatrix(), createdAt))
                }

                is Outcome.Err -> _state.update { it.copy(rotating = false, rotateFailed = true) }
            }
        }
    }

    /** The new kit was confirmed: forget the code and show the saved status. */
    fun kitDone() {
        _state.update { it.copy(fresh = null) }
        load()
    }

    fun verify(code: String) {
        if (_state.value.verifying) return
        _state.update { it.copy(verifying = true, verifyResult = null) }
        viewModelScope.launch {
            val result = attempt { vault.verify(RecoveryCodes.format(code)) }
            _state.update {
                it.copy(
                    verifying = false,
                    verifyResult = when (result) {
                        is Outcome.Ok -> if (result.value) VerifyResult.Valid else VerifyResult.Invalid

                        is Outcome.Err -> if (RecoveryCodes.isChecksumProblem(
                                result.problem.code
                            )
                        ) {
                            VerifyResult.Invalid
                        } else {
                            VerifyResult.Failed
                        }
                    }
                )
            }
        }
    }

    fun clearVerify() = _state.update { it.copy(verifyResult = null) }

    companion object {
        fun statusOf(vault: VaultStatusResponse): KitStatus = when {
            vault.recoveryKitStale -> KitStatus.Stale
            vault.recoveryKitSaved -> KitStatus.Saved
            else -> KitStatus.NotSaved
        }
    }
}

/** Kit de recuperación (Ajustes › Cuenta y nube): status, `Generar nuevo código`, `Verificar código`. */
@Composable
fun RecoveryManageScreen(onBack: () -> Unit, modifier: Modifier = Modifier, viewModel: RecoveryManageViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val fresh = state.fresh
    if (fresh != null) {
        RecoveryKitScreen(
            code = fresh.code,
            qr = fresh.qr,
            occasion = KitOccasion.Rotated,
            vaultCreatedAt = fresh.createdAt,
            onConfirmed = viewModel::kitDone,
            modifier = modifier
        )
        return
    }
    RecoveryManageContent(
        state = state,
        onBack = onBack,
        onRetry = viewModel::load,
        onRotate = viewModel::rotate,
        onVerify = viewModel::verify,
        onVerifyClosed = viewModel::clearVerify,
        modifier = modifier
    )
}

@Composable
fun RecoveryManageContent(
    state: RecoveryManageState,
    onBack: () -> Unit,
    onRetry: () -> Unit,
    onRotate: () -> Unit,
    onVerify: (String) -> Unit,
    onVerifyClosed: () -> Unit,
    modifier: Modifier = Modifier,
    initialDialog: Boolean = false,
    initialVerifySheet: Boolean = false
) {
    var confirmRotate by remember { mutableStateOf(initialDialog) }
    var verifyOpen by remember { mutableStateOf(initialVerifySheet) }
    SetupScaffold(
        title = stringResource(StringsR.string.recovery_manage_title),
        body = stringResource(StringsR.string.recovery_manage_body),
        hero = Hero.Icon(BentoIcons.LifeBuoy),
        onBack = onBack,
        modifier = modifier,
        actions = if (state.status == null) {
            null
        } else {
            {
                BentoButton(
                    stringResource(StringsR.string.recovery_manage_rotate),
                    { confirmRotate = true },
                    Modifier.fillMaxWidth(),
                    variant = if (state.status == KitStatus.Saved) BentoButtonVariant.Secondary else BentoButtonVariant.Primary,
                    size = BentoButtonSize.Large,
                    loading = state.rotating
                )
                BentoButton(
                    stringResource(StringsR.string.recovery_manage_verify),
                    { verifyOpen = true },
                    Modifier.fillMaxWidth(),
                    variant = BentoButtonVariant.Ghost,
                    enabled = state.status != KitStatus.Stale
                )
            }
        }
    ) {
        when {
            state.loading -> LoadingState()
            state.loadFailed -> ErrorState(body = stringResource(StringsR.string.recovery_manage_load_failed), onRetry = onRetry)
            else -> KitStatusBlock(state.status!!)
        }
        if (state.rotateFailed) {
            Spacer(Modifier.height(12.dp))
            Callout(
                tone = CalloutTone.Danger,
                body = stringResource(StringsR.string.recovery_rotate_failed),
                announce = BentoAnnounce.Assertive
            )
        }
    }
    if (confirmRotate) {
        BentoDialog(
            title = stringResource(StringsR.string.recovery_rotate_title),
            consequence = stringResource(
                if (state.status ==
                    KitStatus.Saved
                ) {
                    StringsR.string.recovery_rotate_body_saved
                } else {
                    StringsR.string.recovery_rotate_body_unsaved
                }
            ),
            confirmLabel = stringResource(StringsR.string.recovery_rotate_confirm),
            onConfirm = {
                confirmRotate = false
                onRotate()
            },
            onDismissRequest = { confirmRotate = false },
            icon = BentoIcons.RotateCw
        )
    }
    if (verifyOpen) {
        VerifySheet(
            verifying = state.verifying,
            result = state.verifyResult,
            onVerify = onVerify,
            onDismiss = {
                verifyOpen = false
                onVerifyClosed()
            }
        )
    }
}

@Composable
private fun KitStatusBlock(status: KitStatus) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(
                stringResource(StringsR.string.recovery_manage_status),
                color = BentoTheme.colors.ink,
                style = BentoTheme.typography.bodyStrong
            )
            when (status) {
                KitStatus.Saved -> Badge(
                    stringResource(StringsR.string.recovery_status_saved),
                    tone = BentoTone.Success,
                    icon = BentoIcons.CircleCheck
                )

                KitStatus.NotSaved -> Badge(
                    stringResource(StringsR.string.recovery_status_not_saved),
                    tone = BentoTone.Warning,
                    icon = BentoIcons.TriangleAlert
                )

                KitStatus.Stale -> Badge(
                    stringResource(StringsR.string.recovery_status_stale),
                    tone = BentoTone.Danger,
                    icon = BentoIcons.TriangleAlert
                )
            }
        }
        when (status) {
            KitStatus.Stale -> Callout(
                tone = CalloutTone.Danger,
                title = stringResource(StringsR.string.recovery_stale_title),
                body = stringResource(StringsR.string.recovery_stale_body)
            )

            KitStatus.NotSaved -> Callout(tone = CalloutTone.Warning, body = stringResource(StringsR.string.recovery_not_saved_body))

            KitStatus.Saved -> Unit
        }
        Text(
            stringResource(StringsR.string.recovery_manage_note),
            color = BentoTheme.colors.inkMuted,
            style = BentoTheme.typography.metadata
        )
    }
}

@Composable
private fun VerifySheet(
    verifying: Boolean,
    result: VerifyResult?,
    onVerify: (String) -> Unit,
    onDismiss: () -> Unit,
    code: TextFieldState = rememberTextFieldState()
) {
    BentoSheet(onDismissRequest = onDismiss, title = stringResource(StringsR.string.recovery_verify_title), secure = true) {
        Column(Modifier.padding(horizontal = 24.dp).padding(bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Text(
                stringResource(StringsR.string.recovery_verify_body),
                color = BentoTheme.colors.inkMuted,
                style = BentoTheme.typography.body
            )
            CodeField(state = code, label = stringResource(StringsR.string.recovery_code_label), length = RecoveryCodes.LENGTH)
            when (result) {
                VerifyResult.Valid -> Callout(
                    tone = CalloutTone.Success,
                    body = stringResource(StringsR.string.recovery_verify_valid),
                    announce = BentoAnnounce.Polite
                )

                VerifyResult.Invalid -> Callout(
                    tone = CalloutTone.Danger,
                    body = stringResource(StringsR.string.recovery_verify_invalid),
                    announce = BentoAnnounce.Assertive
                )

                VerifyResult.Failed -> Callout(
                    tone = CalloutTone.Danger,
                    body = stringResource(StringsR.string.recovery_verify_failed),
                    announce = BentoAnnounce.Assertive
                )

                null -> Unit
            }
            BentoButton(
                stringResource(StringsR.string.recovery_verify_submit),
                { onVerify(code.text.toString()) },
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Primary,
                enabled = code.text.length == RecoveryCodes.LENGTH,
                loading = verifying
            )
        }
    }
}
