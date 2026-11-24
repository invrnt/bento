package dev.bento.feature.pairing

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import dev.bento.api.generated.PairingResponse
import dev.bento.designsystem.component.BentoAnnounce
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonSize
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoTextField
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.QrView
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.recovery.Hero
import dev.bento.feature.recovery.HeroTone
import dev.bento.feature.recovery.SecureWindow
import dev.bento.feature.recovery.SetupScaffold
import dev.bento.feature.recovery.toMatrix
import dev.bento.strings.R as StringsR

/** Every guest pairing state, relay and Sync-channel fallback (apps/web `PairingStep`, phone copy). */
@Suppress("CyclomaticComplexMethod", "LongMethod")
@Composable
internal fun GuestPairingStep(state: JoinState, pairing: PairingResponse, actions: JoinActions, modifier: Modifier) {
    val failureActions: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit = {
        BentoButton(
            stringResource(StringsR.string.pairing_retry),
            actions.onRetry,
            Modifier.fillMaxWidth(),
            variant = BentoButtonVariant.Primary,
            size = BentoButtonSize.Large
        )
        BentoButton(
            stringResource(StringsR.string.pairing_join_no_device),
            actions.onNoDevice,
            Modifier.fillMaxWidth(),
            variant = BentoButtonVariant.Ghost
        )
    }
    val cancel: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit = {
        BentoButton(
            stringResource(StringsR.string.common_action_cancel),
            actions.onCancel,
            Modifier.fillMaxWidth(),
            variant = BentoButtonVariant.Ghost
        )
    }
    val peerIsComputer = DeviceLabels.isComputer(pairing.peer?.platform) || pairing.peer == null

    if (state.mismatch) {
        SetupScaffold(
            title = stringResource(StringsR.string.pairing_mismatch_title),
            body = stringResource(StringsR.string.pairing_mismatch_body),
            hero = Hero.Icon(BentoIcons.ShieldAlert, HeroTone.Warning),
            modifier = modifier,
            actions = failureActions
        )
        return
    }

    if (PairingRepository.needsGuestConfirmation(pairing) && pairing.sas != null) {
        SetupScaffold(
            title = stringResource(StringsR.string.pairing_match_title),
            body = stringResource(StringsR.string.pairing_match_body),
            modifier = modifier,
            actions = {
                BentoButton(
                    stringResource(StringsR.string.pairing_match_yes),
                    actions.onMatch,
                    Modifier.fillMaxWidth(),
                    variant = BentoButtonVariant.Primary,
                    size = BentoButtonSize.Large,
                    loading = state.confirming
                )
                BentoButton(
                    stringResource(StringsR.string.pairing_match_no),
                    actions.onNoMatch,
                    Modifier.fillMaxWidth(),
                    size = BentoButtonSize.Large,
                    enabled = !state.confirming
                )
            }
        ) {
            PairingSas(pairing.sas.orEmpty())
            Spacer(Modifier.height(16.dp))
            VaultSummary(pairing.vault)
            if (state.confirmFailed) {
                Spacer(Modifier.height(12.dp))
                Callout(
                    tone = CalloutTone.Danger,
                    body = stringResource(StringsR.string.pairing_confirm_failed),
                    announce = BentoAnnounce.Assertive
                )
            }
        }
        return
    }

    val confirmedFallback = pairing.transport == "telegram" && pairing.state == "approving"
    when (pairing.state) {
        "awaiting_approval", "approving" -> SetupScaffold(
            title = stringResource(
                if (peerIsComputer) StringsR.string.pairing_confirm_title_computer else StringsR.string.pairing_confirm_title_device
            ),
            body = stringResource(
                when {
                    confirmedFallback -> StringsR.string.pairing_confirmed_body
                    peerIsComputer -> StringsR.string.pairing_confirm_body_computer
                    else -> StringsR.string.pairing_confirm_body_device
                }
            ),
            modifier = modifier,
            actions = cancel
        ) {
            pairing.sas?.let { PairingSas(it) }
            if (confirmedFallback) {
                Spacer(Modifier.height(12.dp))
                VaultSummary(pairing.vault)
            }
            Spacer(Modifier.height(16.dp))
            StatusLine(
                stringResource(
                    when {
                        confirmedFallback -> StringsR.string.pairing_waiting_access
                        pairing.state == "approving" -> StringsR.string.pairing_receiving
                        else -> StringsR.string.pairing_waiting_approval
                    }
                )
            )
        }

        "needs_telegram_login" -> NeedsTelegramLogin(state, pairing, actions, modifier)

        "rejected" -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_rejected_title),
            body = stringResource(StringsR.string.pairing_rejected_body),
            hero = Hero.Icon(BentoIcons.TriangleAlert, HeroTone.Warning),
            modifier = modifier,
            actions = failureActions
        )

        "expired" -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_expired_title),
            body = stringResource(StringsR.string.pairing_expired_body),
            hero = Hero.Icon(BentoIcons.Timer, HeroTone.Warning),
            modifier = modifier,
            actions = failureActions
        )

        "cancelled" -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_cancelled_title),
            body = stringResource(StringsR.string.pairing_cancelled_body),
            hero = Hero.Icon(BentoIcons.TriangleAlert, HeroTone.Warning),
            modifier = modifier,
            actions = failureActions
        )

        "failed" -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_failed_title),
            body = stringResource(pairingProblemText(pairingProblem(pairing.error?.code))),
            hero = Hero.Icon(BentoIcons.TriangleAlert, HeroTone.Danger),
            modifier = modifier,
            actions = failureActions
        )

        else -> SetupScaffold(
            title = stringResource(
                if (pairing.transport ==
                    "telegram"
                ) {
                    StringsR.string.pairing_request_title
                } else {
                    StringsR.string.pairing_connecting_title
                }
            ),
            body = stringResource(
                if (pairing.transport ==
                    "telegram"
                ) {
                    StringsR.string.pairing_request_body
                } else {
                    StringsR.string.pairing_connecting_body
                }
            ),
            hero = Hero.Loader,
            modifier = modifier,
            actions = cancel
        )
    }
}

/**
 * The host could not sign this phone in with the forwarded token. On the same phone the Telegram app confirms the
 * login; a cloud password is typed here; another phone can scan the QR.
 */
@Composable
private fun NeedsTelegramLogin(state: JoinState, pairing: PairingResponse, actions: JoinActions, modifier: Modifier) {
    val login = state.guestLogin
    val password = rememberTextFieldState()
    if (login.passwordRequired) SecureWindow()
    SetupScaffold(
        title = stringResource(StringsR.string.pairing_telegram_title),
        body = stringResource(
            if (login.passwordRequired) StringsR.string.pairing_telegram_password_body else StringsR.string.pairing_telegram_body
        ),
        hero = Hero.Icon(if (login.passwordRequired) BentoIcons.KeyRound else BentoIcons.Send),
        modifier = modifier,
        actions = {
            if (login.passwordRequired) {
                BentoButton(
                    stringResource(StringsR.string.onboarding_password_submit),
                    { actions.onSubmitPassword(password.text.toString()) },
                    Modifier.fillMaxWidth(),
                    variant = BentoButtonVariant.Primary,
                    size = BentoButtonSize.Large,
                    enabled = password.text.isNotEmpty(),
                    loading = login.busy
                )
            } else {
                BentoButton(
                    stringResource(StringsR.string.common_telegram_continue),
                    actions.onContinueWithTelegram,
                    Modifier.fillMaxWidth(),
                    variant = BentoButtonVariant.Primary,
                    size = BentoButtonSize.Large,
                    enabled = login.loginUrl != null
                )
                BentoButton(
                    stringResource(StringsR.string.pairing_telegram_use_phone),
                    actions.onUsePhoneInstead,
                    Modifier.fillMaxWidth(),
                    variant = BentoButtonVariant.Ghost
                )
            }
            BentoButton(
                stringResource(StringsR.string.common_action_cancel),
                actions.onCancel,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Ghost
            )
        }
    ) {
        if (login.passwordRequired) {
            login.passwordHint?.takeIf { it.isNotBlank() }?.let { hint ->
                Text(
                    stringResource(StringsR.string.onboarding_password_hint, hint),
                    color = BentoTheme.colors.inkMuted,
                    style = BentoTheme.typography.body,
                    modifier = Modifier.padding(bottom = 12.dp)
                )
            }
            BentoTextField(
                state = password,
                label = stringResource(StringsR.string.onboarding_password_label),
                error = if (login.passwordInvalid) stringResource(StringsR.string.onboarding_error_password_invalid) else null,
                secure = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                onKeyboardAction = { actions.onSubmitPassword(password.text.toString()) }
            )
        } else {
            Column(
                Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                pairing.telegramQr?.let {
                    QrView(
                        it.toMatrix(),
                        Modifier.fillMaxWidth(0.7f),
                        contentDescription = stringResource(StringsR.string.onboarding_qr_label)
                    )
                    Text(
                        stringResource(StringsR.string.pairing_telegram_qr_hint),
                        color = BentoTheme.colors.inkMuted,
                        style = BentoTheme.typography.metadata
                    )
                }
                StatusLine(stringResource(StringsR.string.pairing_telegram_waiting))
            }
        }
    }
}
