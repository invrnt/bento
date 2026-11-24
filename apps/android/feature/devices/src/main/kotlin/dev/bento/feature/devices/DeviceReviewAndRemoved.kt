package dev.bento.feature.devices

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonSize
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.ErrorState
import dev.bento.designsystem.component.LoadingState
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.recovery.Hero
import dev.bento.feature.recovery.HeroTone
import dev.bento.feature.recovery.KitOccasion
import dev.bento.feature.recovery.RecoveryKitScreen
import dev.bento.feature.recovery.SetupScaffold
import dev.bento.strings.R as StringsR

/**
 * New-device review (from the `Dispositivos` notification or an Activity item): "Se añadió «X» a tu nube".
 * `Es mío` acknowledges it; `No lo reconozco` opens the removal (preview, exclusions, new kit).
 */
@Composable
fun DeviceReviewScreen(
    deviceId: String,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: DevicesViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val device = state.devices.firstOrNull { it.id == deviceId }
    val result = state.result
    if (result != null) {
        RecoveryKitScreen(
            code = result.code,
            qr = result.qr,
            occasion = KitOccasion.NewAfterRemoval,
            vaultCreatedAt = state.vaultCreatedAt,
            onConfirmed = {
                viewModel.kitSaved()
                onClose()
            },
            modifier = modifier
        )
        return
    }
    // Reviewed (acknowledged) or already removed elsewhere: nothing left to decide here.
    val settled = !state.loading && !state.loadFailed && state.removal == null
    LaunchedEffect(settled, device?.needsReview) { if (settled && device?.needsReview != true) onClose() }
    SetupScaffold(
        title = stringResource(StringsR.string.devices_review_screen_title),
        hero = Hero.Icon(BentoIcons.ShieldAlert, HeroTone.Warning),
        onBack = onClose,
        modifier = modifier
    ) {
        when {
            state.loading -> LoadingState()

            state.loadFailed -> ErrorState(body = stringResource(StringsR.string.devices_load_failed), onRetry = viewModel::load)

            device != null -> ReviewCard(
                device,
                busy = state.acknowledging == device.id,
                failed = state.reviewFailed == device.id,
                actions = DevicesActions(onAcknowledge = viewModel::acknowledge, onRemove = viewModel::startRemoval)
            )
        }
    }
    state.removal?.let {
        RemovalSheet(
            it,
            DevicesActions(
                onToggleKeep = viewModel::toggleKeep,
                onConfirmRemoval = viewModel::confirmRemoval,
                onCancelRemoval = viewModel::cancelRemoval
            )
        )
    }
}

/**
 * This phone was removed by another device (§11): the library stays readable here, nothing syncs. `Volver a unirme`
 * joins again with a new identity (pairing or recovery kit); the backend generates it.
 */
@Composable
fun DeviceRemovedScreen(onRejoin: () -> Unit, onUseRecovery: () -> Unit, onLater: () -> Unit, modifier: Modifier = Modifier) {
    SetupScaffold(
        title = stringResource(StringsR.string.devices_removed_self_title),
        body = stringResource(StringsR.string.devices_removed_self_body),
        hero = Hero.Icon(BentoIcons.Unplug, HeroTone.Warning),
        onBack = onLater,
        modifier = modifier,
        actions = {
            BentoButton(
                stringResource(StringsR.string.devices_removed_self_rejoin),
                onRejoin,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Primary,
                size = BentoButtonSize.Large
            )
            BentoButton(
                stringResource(StringsR.string.devices_removed_self_recovery),
                onUseRecovery,
                Modifier.fillMaxWidth(),
                size = BentoButtonSize.Large,
                leadingIcon = BentoIcons.LifeBuoy
            )
            BentoButton(
                stringResource(StringsR.string.devices_removed_self_later),
                onLater,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Ghost
            )
        }
    ) {
        Text(
            stringResource(StringsR.string.devices_removed_self_next),
            color = BentoTheme.colors.inkMuted,
            style = BentoTheme.typography.body
        )
    }
}
