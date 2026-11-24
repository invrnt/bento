package dev.bento.feature.pairing

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.text.input.TextFieldState
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.foundation.text.input.setTextAndPlaceCursorAtEnd
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.bento.designsystem.component.BentoAnnounce
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonSize
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoChip
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.CodeField
import dev.bento.designsystem.component.ProgressBar
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoHaptic
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.designsystem.theme.bentoHaptics
import dev.bento.feature.onboarding.SignInCopy
import dev.bento.feature.onboarding.TelegramApp
import dev.bento.feature.onboarding.TelegramSignInScreen
import dev.bento.feature.recovery.CameraSlot
import dev.bento.feature.recovery.CameraXSlot
import dev.bento.feature.recovery.Hero
import dev.bento.feature.recovery.HeroTone
import dev.bento.feature.recovery.QrScannerPanel
import dev.bento.feature.recovery.RecoveryEntryScreen
import dev.bento.feature.recovery.SensitiveClipboard
import dev.bento.feature.recovery.SetupScaffold
import dev.bento.feature.recovery.rememberCameraPermission
import dev.bento.strings.R as StringsR
import java.text.NumberFormat

/**
 * Join an existing cloud (product/android.md §4.2): in-app scanner (CameraX + ML Kit), code entry with paste and
 * links, SAS confirmation, login-token forwarding, Sync-channel fallback with `Coinciden`/`No coinciden`, recovery
 * code, progressive bootstrap hand-off to Fotos.
 */
@Suppress("LongMethod")
@Composable
fun JoinScreen(
    code: String?,
    startAtChoice: Boolean,
    onDone: () -> Unit,
    onCreateVault: () -> Unit,
    onExit: () -> Unit,
    modifier: Modifier = Modifier,
    camera: CameraSlot = CameraXSlot,
    viewModel: JoinViewModel = hiltViewModel()
) {
    val context = LocalContext.current
    val state by viewModel.state.collectAsStateWithLifecycle()
    val haptics = bentoHaptics()
    LaunchedEffect(Unit) { viewModel.start(code, startAtChoice) }
    LaunchedEffect(viewModel) {
        viewModel.effect.collect { effect ->
            when (effect) {
                JoinEffect.Done -> onDone()
                JoinEffect.CreateVault -> onCreateVault()
                is JoinEffect.OpenTelegramLogin -> TelegramApp.openLogin(context, effect.url)
            }
        }
    }
    LaunchedEffect(state.step) { if (state.step == JoinStep.Bootstrap) haptics.perform(BentoHaptic.Confirm) }

    when (state.step) {
        JoinStep.SignIn -> TelegramSignInScreen(
            onAuthorized = { viewModel.signedIn() },
            onBack = { viewModel.leavePairing(JoinStep.Entry) },
            copy = SignInCopy(StringsR.string.pairing_signin_title, StringsR.string.pairing_signin_body),
            modifier = modifier
        )

        JoinStep.Recovery -> RecoveryEntryScreen(
            onUnlocked = viewModel::unlocked,
            onBack = viewModel::recoveryBack,
            camera = camera,
            modifier = modifier
        )

        else -> {
            val permission = rememberCameraPermission()
            var clipboard by remember { mutableStateOf<String?>(null) }
            LifecycleResumeEffect(state.step, state.entryMode) {
                clipboard = if (state.step == JoinStep.Entry && state.entryMode == EntryMode.Type) {
                    SensitiveClipboard.readText(context)?.let(PairingCodes::fromScanOrPaste)
                } else {
                    null
                }
                onPauseOrDispose {}
            }
            BackHandler(enabled = state.step != JoinStep.Entry && state.step != JoinStep.Checking) {
                when (state.step) {
                    JoinStep.Pairing, JoinStep.Choose, JoinStep.NoVault -> viewModel.leavePairing(JoinStep.Entry)
                    else -> onExit()
                }
            }
            JoinContent(
                state = state,
                clipboardCode = clipboard,
                actions = JoinActions(
                    onJoin = viewModel::join,
                    onEdited = viewModel::clearJoinProblem,
                    onMode = viewModel::setEntryMode,
                    onNoDevice = viewModel::noOtherDevice,
                    onRequestAccess = viewModel::requestAccess,
                    onRecovery = { viewModel.openRecovery(state.step) },
                    onHaveCode = viewModel::haveCode,
                    onCreateVault = viewModel::createVault,
                    onMatch = viewModel::confirmMatch,
                    onNoMatch = viewModel::rejectMatch,
                    onCancel = { viewModel.leavePairing(JoinStep.Entry) },
                    onRetry = viewModel::retry,
                    onContinueWithTelegram = viewModel::continueWithTelegram,
                    onUsePhoneInstead = { viewModel.leavePairing(JoinStep.SignIn) },
                    onSubmitPassword = viewModel::submitPassword,
                    onBootstrapContinue = viewModel::bootstrapContinue,
                    onExit = onExit
                ),
                modifier = modifier,
                scanner = { onScanned ->
                    QrScannerPanel(
                        onCode = { payload -> PairingCodes.fromScanOrPaste(payload)?.let(onScanned) },
                        accept = { PairingCodes.fromScanOrPaste(it) != null },
                        camera = camera,
                        access = permission.access,
                        onRequestAccess = permission.request,
                        onOpenSettings = permission.openSettings,
                        hint = stringResource(StringsR.string.pairing_scan_hint),
                        rejectedMessage = stringResource(StringsR.string.pairing_scan_wrong)
                    )
                }
            )
        }
    }
}

data class JoinActions(
    val onJoin: (String) -> Unit = {},
    val onEdited: () -> Unit = {},
    val onMode: (EntryMode) -> Unit = {},
    val onNoDevice: () -> Unit = {},
    val onRequestAccess: () -> Unit = {},
    val onRecovery: () -> Unit = {},
    val onHaveCode: () -> Unit = {},
    val onCreateVault: () -> Unit = {},
    val onMatch: () -> Unit = {},
    val onNoMatch: () -> Unit = {},
    val onCancel: () -> Unit = {},
    val onRetry: () -> Unit = {},
    val onContinueWithTelegram: () -> Unit = {},
    val onUsePhoneInstead: () -> Unit = {},
    val onSubmitPassword: (String) -> Unit = {},
    val onBootstrapContinue: () -> Unit = {},
    val onExit: () -> Unit = {}
)

@Composable
fun JoinContent(
    state: JoinState,
    actions: JoinActions,
    modifier: Modifier = Modifier,
    clipboardCode: String? = null,
    scanner: @Composable (onScanned: (String) -> Unit) -> Unit = {}
) {
    when (state.step) {
        JoinStep.Checking -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_join_title),
            hero = Hero.Loader,
            onBack = actions.onExit,
            modifier = modifier
        )

        JoinStep.Entry -> EntryStep(state, clipboardCode, actions, scanner, modifier)

        JoinStep.Pairing -> state.pairing?.let { GuestPairingStep(state, it, actions, modifier) }

        JoinStep.Choose -> ChooseStep(state, actions, modifier)

        JoinStep.NoVault -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_no_vault_title),
            body = stringResource(StringsR.string.pairing_no_vault_body),
            hero = Hero.Icon(BentoIcons.TriangleAlert, HeroTone.Warning),
            onBack = actions.onCancel,
            modifier = modifier,
            actions = {
                BentoButton(
                    stringResource(StringsR.string.pairing_no_vault_create),
                    actions.onCreateVault,
                    Modifier.fillMaxWidth(),
                    variant = BentoButtonVariant.Primary,
                    size = BentoButtonSize.Large
                )
                BentoButton(
                    stringResource(StringsR.string.pairing_choose_have_code),
                    actions.onHaveCode,
                    Modifier.fillMaxWidth(),
                    variant = BentoButtonVariant.Ghost
                )
            }
        )

        JoinStep.Bootstrap -> BootstrapStep(state.bootstrap, actions, modifier)

        JoinStep.Already -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_already_title),
            body = stringResource(StringsR.string.pairing_already_body),
            hero = Hero.Icon(BentoIcons.CircleCheck, HeroTone.Success),
            onBack = actions.onExit,
            modifier = modifier,
            actions = {
                BentoButton(
                    stringResource(StringsR.string.pairing_already_back),
                    actions.onExit,
                    Modifier.fillMaxWidth(),
                    variant = BentoButtonVariant.Primary,
                    size = BentoButtonSize.Large
                )
            }
        )

        JoinStep.SignIn, JoinStep.Recovery -> Unit
    }
}

@Suppress("LongMethod")
@Composable
private fun EntryStep(
    state: JoinState,
    clipboardCode: String?,
    actions: JoinActions,
    scanner: @Composable (onScanned: (String) -> Unit) -> Unit,
    modifier: Modifier,
    code: TextFieldState = remember(state.prefill) { TextFieldState(state.prefill.orEmpty()) }
) {
    LaunchedEffect(code) { snapshotFlow { code.text.toString() }.collect { actions.onEdited() } }
    val fieldError = when (state.joinProblem) {
        PairingProblem.WrongCode, PairingProblem.NotFound -> stringResource(pairingProblemText(state.joinProblem))
        else -> null
    }
    val scanning = state.entryMode == EntryMode.Scan
    SetupScaffold(
        title = stringResource(StringsR.string.pairing_join_title),
        body = stringResource(if (scanning) StringsR.string.pairing_join_scan_body else StringsR.string.pairing_join_code_body),
        onBack = actions.onExit,
        modifier = modifier,
        actions = {
            if (!scanning) {
                BentoButton(
                    stringResource(StringsR.string.pairing_join_submit),
                    { actions.onJoin(code.text.toString()) },
                    Modifier.fillMaxWidth(),
                    variant = BentoButtonVariant.Primary,
                    size = BentoButtonSize.Large,
                    enabled = code.text.length == PairingCodes.LENGTH,
                    loading = state.joining,
                    loadingLabel = stringResource(StringsR.string.pairing_connecting_title)
                )
            }
            BentoButton(
                stringResource(StringsR.string.pairing_join_no_device),
                actions.onNoDevice,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Ghost
            )
        }
    ) {
        if (scanning) {
            scanner { scanned ->
                code.setTextAndPlaceCursorAtEnd(scanned)
                actions.onMode(EntryMode.Type)
                actions.onJoin(scanned)
            }
            Spacer(Modifier.height(12.dp))
            BentoButton(
                stringResource(StringsR.string.pairing_join_type_code),
                { actions.onMode(EntryMode.Type) },
                Modifier.fillMaxWidth(),
                leadingIcon = BentoIcons.Keyboard
            )
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                CodeField(
                    state = code,
                    label = stringResource(StringsR.string.pairing_code_label),
                    length = PairingCodes.LENGTH,
                    hint = stringResource(StringsR.string.pairing_code_hint),
                    error = fieldError
                )
                if (clipboardCode != null && code.text.isEmpty()) {
                    BentoChip(
                        label = stringResource(StringsR.string.pairing_code_paste, PairingCodes.format(clipboardCode)),
                        onClick = { code.setTextAndPlaceCursorAtEnd(clipboardCode) },
                        leadingIcon = BentoIcons.ClipboardPaste
                    )
                }
                BentoButton(
                    stringResource(StringsR.string.pairing_join_scan_instead),
                    { actions.onMode(EntryMode.Scan) },
                    leadingIcon = BentoIcons.ScanLine,
                    variant = BentoButtonVariant.Secondary
                )
            }
        }
        val problem = state.joinProblem
        if (problem != null && fieldError == null) {
            Spacer(Modifier.height(16.dp))
            Callout(
                tone = if (problem == PairingProblem.RelayUnavailable) CalloutTone.Warning else CalloutTone.Danger,
                body = stringResource(pairingProblemText(problem)),
                announce = BentoAnnounce.Assertive,
                action = if (problem == PairingProblem.RelayUnavailable) {
                    {
                        BentoButton(
                            stringResource(StringsR.string.pairing_join_use_telegram),
                            actions.onNoDevice,
                            size = BentoButtonSize.Small
                        )
                    }
                } else {
                    null
                }
            )
        }
    }
}

@Composable
private fun ChooseStep(state: JoinState, actions: JoinActions, modifier: Modifier) {
    SetupScaffold(
        title = stringResource(StringsR.string.pairing_choose_title),
        body = stringResource(StringsR.string.pairing_choose_body),
        hero = Hero.Icon(BentoIcons.ShieldCheck),
        onBack = actions.onCancel,
        modifier = modifier,
        actions = {
            BentoButton(
                stringResource(StringsR.string.pairing_choose_request),
                actions.onRequestAccess,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Primary,
                size = BentoButtonSize.Large,
                leadingIcon = BentoIcons.Users,
                loading = state.requesting
            )
            BentoButton(
                stringResource(StringsR.string.pairing_choose_recovery),
                actions.onRecovery,
                Modifier.fillMaxWidth(),
                size = BentoButtonSize.Large,
                leadingIcon = BentoIcons.LifeBuoy
            )
            BentoButton(
                stringResource(StringsR.string.pairing_choose_have_code),
                actions.onHaveCode,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Ghost
            )
        }
    ) {
        Text(
            stringResource(StringsR.string.pairing_choose_request_body),
            color = BentoTheme.colors.inkMuted,
            style = BentoTheme.typography.body
        )
        Spacer(Modifier.height(8.dp))
        Text(
            stringResource(StringsR.string.pairing_choose_recovery_body),
            color = BentoTheme.colors.inkMuted,
            style = BentoTheme.typography.body
        )
        state.requestProblem?.let { problem ->
            Spacer(Modifier.height(16.dp))
            Callout(tone = CalloutTone.Danger, body = stringResource(pairingProblemText(problem)), announce = BentoAnnounce.Assertive)
        }
    }
}

@Composable
private fun BootstrapStep(progress: BootstrapProgress, actions: JoinActions, modifier: Modifier) {
    val format = NumberFormat.getIntegerInstance()
    SetupScaffold(
        title = stringResource(
            if (progress.finished) StringsR.string.pairing_bootstrap_done_title else StringsR.string.pairing_bootstrap_title
        ),
        body = stringResource(
            if (progress.finished) StringsR.string.pairing_bootstrap_done_body else StringsR.string.pairing_bootstrap_body
        ),
        hero = if (progress.finished) Hero.Icon(BentoIcons.CircleCheck, HeroTone.Success) else Hero.Loader,
        modifier = modifier,
        actions = {
            BentoButton(
                stringResource(
                    if (progress.finished) StringsR.string.pairing_bootstrap_open else StringsR.string.pairing_bootstrap_continue
                ),
                actions.onBootstrapContinue,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Primary,
                size = BentoButtonSize.Large
            )
        }
    ) {
        val label = if (progress.total > 0) {
            stringResource(StringsR.string.pairing_bootstrap_progress, format.format(progress.done), format.format(progress.total))
        } else {
            stringResource(StringsR.string.pairing_bootstrap_preparing)
        }
        ProgressBar(progress = if (progress.finished) 1f else progress.fraction, label = label, modifier = Modifier.fillMaxWidth())
        Spacer(Modifier.height(8.dp))
        Text(label, color = BentoTheme.colors.inkMuted, style = BentoTheme.typography.numeric)
    }
}
