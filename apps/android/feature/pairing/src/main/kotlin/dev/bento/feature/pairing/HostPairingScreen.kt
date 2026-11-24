package dev.bento.feature.pairing

import android.content.Intent
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.bento.designsystem.component.BentoAnnounce
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonSize
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.QrView
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoHaptic
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.designsystem.theme.bentoHaptics
import dev.bento.feature.recovery.Hero
import dev.bento.feature.recovery.HeroTone
import dev.bento.feature.recovery.SecureWindow
import dev.bento.feature.recovery.SensitiveClipboard
import dev.bento.feature.recovery.SetupScaffold
import dev.bento.feature.recovery.toMatrix
import dev.bento.strings.R as StringsR

/**
 * Ajustes › Dispositivos › Añadir dispositivo with this phone as host (product/android.md §9): large QR, the code,
 * countdown and `Compartir enlace` (FLAG_SECURE), then "¿Añadir «…»?" with the emojis, then the outcome.
 */
@Composable
fun HostPairingScreen(onClose: () -> Unit, modifier: Modifier = Modifier, viewModel: HostPairingViewModel = hiltViewModel()) {
    val context = LocalContext.current
    val state by viewModel.state.collectAsStateWithLifecycle()
    val haptics = bentoHaptics()
    val close = {
        viewModel.close()
        onClose()
    }
    BackHandler(onBack = close)
    LaunchedEffect(state.phase) { if (state.phase == HostPhase.Completed) haptics.perform(BentoHaptic.Confirm) }
    val shareTitle = stringResource(StringsR.string.pairing_host_share_title)
    HostPairingContent(
        state = state,
        onClose = close,
        onRetry = viewModel::start,
        onApprove = { viewModel.decide(true) },
        onReject = { viewModel.decide(false) },
        onCopyCode = { code -> SensitiveClipboard.copy(context, code) },
        onShareLink = { link ->
            val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, link)
            runCatching { context.startActivity(Intent.createChooser(send, shareTitle).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
        },
        modifier = modifier
    )
}

@Suppress("LongMethod", "CyclomaticComplexMethod")
@Composable
fun HostPairingContent(
    state: HostState,
    onClose: () -> Unit,
    onRetry: () -> Unit,
    onApprove: () -> Unit,
    onReject: () -> Unit,
    onCopyCode: (String) -> Boolean,
    onShareLink: (String) -> Unit,
    modifier: Modifier = Modifier
) {
    val pairing = state.pairing
    val peer = pairing?.peer?.let { deviceDisplayName(it.deviceName, it.platform) }.orEmpty()
    val done: @Composable ColumnScope.() -> Unit = {
        BentoButton(
            stringResource(StringsR.string.pairing_host_done),
            onClose,
            Modifier.fillMaxWidth(),
            variant = BentoButtonVariant.Primary,
            size = BentoButtonSize.Large
        )
    }
    val retry: @Composable ColumnScope.() -> Unit = {
        BentoButton(
            stringResource(StringsR.string.pairing_host_new_code),
            onRetry,
            Modifier.fillMaxWidth(),
            variant = BentoButtonVariant.Primary,
            size = BentoButtonSize.Large,
            leadingIcon = BentoIcons.RotateCw
        )
        BentoButton(
            stringResource(StringsR.string.common_action_close),
            onClose,
            Modifier.fillMaxWidth(),
            variant = BentoButtonVariant.Ghost
        )
    }
    when (state.phase) {
        HostPhase.Loading -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_host_title),
            body = stringResource(StringsR.string.pairing_host_loading),
            hero = Hero.Loader,
            onBack = onClose,
            modifier = modifier
        )

        HostPhase.Code -> {
            SecureWindow()
            CodeView(state, onClose, onCopyCode, onShareLink, modifier)
        }

        HostPhase.Approve -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_host_approve_title, peer),
            body = stringResource(StringsR.string.pairing_host_approve_body),
            onBack = onClose,
            modifier = modifier,
            actions = {
                BentoButton(
                    stringResource(StringsR.string.pairing_host_approve),
                    onApprove,
                    Modifier.fillMaxWidth(),
                    variant = BentoButtonVariant.Primary,
                    size = BentoButtonSize.Large,
                    loading = state.acting
                )
                BentoButton(
                    stringResource(StringsR.string.pairing_host_reject),
                    onReject,
                    Modifier.fillMaxWidth(),
                    size = BentoButtonSize.Large,
                    enabled = !state.acting
                )
            }
        ) {
            pairing?.sas?.let { PairingSas(it) }
            Spacer(Modifier.height(8.dp))
            Text(
                stringResource(StringsR.string.pairing_host_sas_hint),
                color = BentoTheme.colors.inkMuted,
                style = BentoTheme.typography.metadata,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth()
            )
            if (state.actionFailed) {
                Spacer(Modifier.height(12.dp))
                Callout(
                    tone = CalloutTone.Danger,
                    body = stringResource(StringsR.string.pairing_host_action_failed),
                    announce = BentoAnnounce.Assertive
                )
            }
        }

        HostPhase.Approving, HostPhase.GuestLogin -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_host_title),
            hero = Hero.Loader,
            onBack = onClose,
            modifier = modifier
        ) {
            StatusLine(
                stringResource(
                    if (state.phase ==
                        HostPhase.GuestLogin
                    ) {
                        StringsR.string.pairing_host_guest_login
                    } else {
                        StringsR.string.pairing_host_approving
                    },
                    peer
                )
            )
        }

        HostPhase.Completed -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_host_completed_title),
            body = stringResource(StringsR.string.pairing_host_completed_body, peer),
            hero = Hero.Icon(BentoIcons.CircleCheck, HeroTone.Success),
            modifier = modifier,
            actions = done
        )

        HostPhase.Rejected -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_host_rejected_title),
            body = stringResource(StringsR.string.pairing_host_rejected_body),
            hero = Hero.Icon(BentoIcons.ShieldCheck),
            modifier = modifier,
            actions = done
        )

        HostPhase.Expired -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_host_expired_title),
            body = stringResource(StringsR.string.pairing_host_expired_body),
            hero = Hero.Icon(BentoIcons.Timer, HeroTone.Warning),
            onBack = onClose,
            modifier = modifier,
            actions = retry
        )

        HostPhase.RelayUnavailable -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_host_relay_title),
            body = stringResource(StringsR.string.pairing_host_relay_body),
            hero = Hero.Icon(BentoIcons.Unplug, HeroTone.Warning),
            onBack = onClose,
            modifier = modifier,
            actions = retry
        ) {
            Callout(tone = CalloutTone.Info, body = stringResource(StringsR.string.pairing_host_relay_fallback))
        }

        HostPhase.StartFailed, HostPhase.Failed -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_host_failed_title),
            body = stringResource(
                if (state.phase ==
                    HostPhase.StartFailed
                ) {
                    StringsR.string.pairing_host_start_failed
                } else {
                    pairingProblemText(pairingProblem(pairing?.error?.code))
                }
            ),
            hero = Hero.Icon(BentoIcons.TriangleAlert, HeroTone.Danger),
            onBack = onClose,
            modifier = modifier,
            actions = retry
        )
    }
}

@Suppress("LongMethod")
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun CodeView(
    state: HostState,
    onClose: () -> Unit,
    onCopyCode: (String) -> Boolean,
    onShareLink: (String) -> Unit,
    modifier: Modifier
) {
    val pairing = state.pairing ?: return
    val c = BentoTheme.colors
    var copied by remember { mutableStateOf(false) }
    val code = pairing.code.orEmpty()
    val link = pairing.webLink ?: pairing.link
    val spoken = stringResource(StringsR.string.pairing_host_code_spoken, code.toCharArray().filter { it != '-' }.joinToString(" "))
    SetupScaffold(
        title = stringResource(StringsR.string.pairing_host_title),
        body = stringResource(StringsR.string.pairing_host_instructions),
        onBack = onClose,
        modifier = modifier,
        actions = {
            if (link != null) {
                BentoButton(
                    stringResource(StringsR.string.pairing_host_share_link),
                    { onShareLink(link) },
                    Modifier.fillMaxWidth(),
                    variant = BentoButtonVariant.Primary,
                    size = BentoButtonSize.Large,
                    leadingIcon = BentoIcons.Share2
                )
            }
            BentoButton(
                stringResource(StringsR.string.common_action_cancel),
                onClose,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Ghost
            )
        }
    ) {
        Column(
            Modifier.fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            pairing.qr?.let {
                QrView(
                    it.toMatrix(),
                    Modifier.fillMaxWidth(0.86f),
                    contentDescription = stringResource(StringsR.string.pairing_host_qr_label)
                )
            }
            Text(
                code,
                color = c.ink,
                style = BentoTheme.typography.monoLarge,
                textAlign = TextAlign.Center,
                modifier = Modifier
                    .clip(BentoShapes.lg)
                    .background(c.sunken)
                    .border(1.dp, c.line, BentoShapes.lg)
                    .padding(horizontal = 20.dp, vertical = 12.dp)
                    .clearAndSetSemantics { contentDescription = spoken }
            )
            state.secondsLeft?.let { left ->
                Text(
                    stringResource(StringsR.string.pairing_host_expires_in, "%d:%02d".format(left / 60, left % 60)),
                    color = c.inkMuted,
                    style = BentoTheme.typography.numeric
                )
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally)) {
                BentoButton(
                    stringResource(if (copied) StringsR.string.pairing_host_copied else StringsR.string.pairing_host_copy_code),
                    { copied = onCopyCode(code) },
                    size = BentoButtonSize.Small,
                    leadingIcon = if (copied) BentoIcons.Check else BentoIcons.Copy
                )
            }
            StatusLine(
                stringResource(
                    if (pairing.state ==
                        "connected"
                    ) {
                        StringsR.string.pairing_host_connecting
                    } else {
                        StringsR.string.pairing_host_waiting
                    }
                )
            )
        }
    }
}
