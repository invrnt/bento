package dev.bento.feature.devices

import android.text.format.DateUtils
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.input.TextFieldState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.bento.api.generated.DeviceResponse
import dev.bento.api.generated.PairingRequestItem
import dev.bento.designsystem.component.AttentionCard
import dev.bento.designsystem.component.Badge
import dev.bento.designsystem.component.BentoAnnounce
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonSize
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.BentoSheet
import dev.bento.designsystem.component.BentoTextField
import dev.bento.designsystem.component.BentoTone
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.EmptyState
import dev.bento.designsystem.component.ErrorState
import dev.bento.designsystem.component.ListRow
import dev.bento.designsystem.component.LoadingState
import dev.bento.designsystem.component.SectionHeader
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.pairing.DeviceLabels
import dev.bento.feature.pairing.deviceDisplayName
import dev.bento.feature.pairing.platformLabel
import dev.bento.feature.recovery.KitOccasion
import dev.bento.feature.recovery.ObscuredTouchGuard
import dev.bento.feature.recovery.RecoveryKitScreen
import dev.bento.feature.recovery.SetupScaffold
import dev.bento.feature.recovery.TrustDates
import dev.bento.strings.R as StringsR

/**
 * Ajustes › Dispositivos (product/android.md §9): pending reviews and join requests at the top, then every device
 * ("Este teléfono" first) with platform icon and last seen; rename; `Añadir dispositivo` (phone as host);
 * `Quitar` with the removal preview, exclusions and the mandatory new kit.
 */
@Composable
fun DevicesScreen(
    onBack: () -> Unit,
    onAddDevice: () -> Unit,
    onReviewRequest: (String) -> Unit,
    onConnectTelegram: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: DevicesViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    LifecycleResumeEffect(Unit) {
        viewModel.load()
        viewModel.watchRequests(true)
        onPauseOrDispose { viewModel.watchRequests(false) }
    }
    val result = state.result
    if (result != null) {
        RecoveryKitScreen(
            code = result.code,
            qr = result.qr,
            occasion = KitOccasion.NewAfterRemoval,
            vaultCreatedAt = state.vaultCreatedAt,
            onConfirmed = viewModel::kitSaved,
            modifier = modifier
        )
        return
    }
    DevicesContent(
        state = state,
        actions = DevicesActions(
            onBack = onBack,
            onRetry = viewModel::load,
            onAdd = onAddDevice,
            onConnect = onConnectTelegram,
            onReviewRequest = onReviewRequest,
            onRename = viewModel::startRename,
            onRenameSave = viewModel::rename,
            onRenameCancel = viewModel::cancelRename,
            onRemove = viewModel::startRemoval,
            onToggleKeep = viewModel::toggleKeep,
            onConfirmRemoval = viewModel::confirmRemoval,
            onCancelRemoval = viewModel::cancelRemoval,
            onAcknowledge = viewModel::acknowledge,
            onDismissNotice = viewModel::dismissNotice
        ),
        modifier = modifier
    )
}

data class DevicesActions(
    val onBack: () -> Unit = {},
    val onRetry: () -> Unit = {},
    val onAdd: () -> Unit = {},
    val onConnect: () -> Unit = {},
    val onReviewRequest: (String) -> Unit = {},
    val onRename: (DeviceResponse) -> Unit = {},
    val onRenameSave: (String) -> Unit = {},
    val onRenameCancel: () -> Unit = {},
    val onRemove: (DeviceResponse) -> Unit = {},
    val onToggleKeep: (String, Boolean) -> Unit = { _, _ -> },
    val onConfirmRemoval: () -> Unit = {},
    val onCancelRemoval: () -> Unit = {},
    val onAcknowledge: (DeviceResponse) -> Unit = {},
    val onDismissNotice: () -> Unit = {}
)

@Composable
fun DevicesContent(state: DevicesState, actions: DevicesActions, modifier: Modifier = Modifier, now: Long = System.currentTimeMillis()) {
    var menuFor by remember { mutableStateOf<DeviceResponse?>(null) }
    SetupScaffold(
        title = stringResource(StringsR.string.devices_title),
        body = stringResource(StringsR.string.devices_body),
        onBack = actions.onBack,
        modifier = modifier,
        actions = if (state.localOnly || state.loading) {
            null
        } else {
            {
                BentoButton(
                    stringResource(StringsR.string.devices_add),
                    actions.onAdd,
                    Modifier.fillMaxWidth(),
                    variant = BentoButtonVariant.Primary,
                    size = BentoButtonSize.Large,
                    leadingIcon = BentoIcons.Plus
                )
            }
        }
    ) {
        when {
            state.loading -> LoadingState(label = stringResource(StringsR.string.devices_loading))

            state.localOnly -> EmptyState(
                title = stringResource(StringsR.string.devices_local_title),
                body = stringResource(StringsR.string.devices_local_body),
                icon = BentoIcons.MonitorSmartphone,
                action = {
                    BentoButton(stringResource(StringsR.string.devices_connect), actions.onConnect, variant = BentoButtonVariant.Primary)
                }
            )

            state.loadFailed -> ErrorState(body = stringResource(StringsR.string.devices_load_failed), onRetry = actions.onRetry)

            else -> DeviceList(state, actions, now, onMenu = { menuFor = it })
        }
    }
    menuFor?.let { device ->
        DeviceMenu(
            device = device,
            onRename = {
                menuFor = null
                actions.onRename(device)
            },
            onRemove = {
                menuFor = null
                actions.onRemove(device)
            },
            onDismiss = { menuFor = null }
        )
    }
    state.renaming?.let { RenameSheet(it, state.renameBusy, state.renameFailed, actions) }
    state.removal?.let { RemovalSheet(it, actions) }
}

@Composable
private fun DeviceList(state: DevicesState, actions: DevicesActions, now: Long, onMenu: (DeviceResponse) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        state.notice?.let { RemovalNoticeCard(it, actions.onDismissNotice) }
        state.requests.forEach { RequestCard(it, actions.onReviewRequest) }
        state.pendingReviews.forEach { device ->
            ReviewCard(
                device,
                busy = state.acknowledging == device.id,
                failed =
                    state.reviewFailed == device.id,
                actions = actions
            )
        }
        SectionHeader(stringResource(StringsR.string.devices_section_all))
        Column(
            Modifier.fillMaxWidth().clip(
                BentoShapes.lg
            ).background(BentoTheme.colors.raised).border(1.dp, BentoTheme.colors.line, BentoShapes.lg)
        ) {
            state.devices.forEach { device -> DeviceRow(device, now, onClick = { onMenu(device) }) }
        }
    }
}

@Composable
private fun DeviceRow(device: DeviceResponse, now: Long, onClick: () -> Unit) {
    val c = BentoTheme.colors
    val supporting = when {
        device.current -> stringResource(StringsR.string.devices_this_phone)
        else -> lastSeen(device, now)
    }
    ListRow(
        headline = deviceDisplayName(device.name, device.platform),
        supporting = supporting,
        leading = {
            Box(Modifier.size(40.dp).clip(BentoShapes.md).background(c.subtle), contentAlignment = Alignment.Center) {
                BentoIcon(DeviceLabels.icon(device.platform), contentDescription = platformLabel(device.platform), tint = c.inkMuted)
            }
        },
        trailing = {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (device.needsReview) Badge(stringResource(StringsR.string.devices_new), tone = BentoTone.Warning)
                BentoIcon(BentoIcons.EllipsisVertical, contentDescription = null, tint = c.inkMuted)
            }
        },
        onClick = onClick,
        onClickLabel = stringResource(StringsR.string.devices_options, device.name)
    )
}

@Composable
private fun lastSeen(device: DeviceResponse, now: Long): String {
    val seen = TrustDates.parse(device.lastSeenAt)?.toEpochMilli()
    return when {
        seen == null -> stringResource(StringsR.string.devices_added_on, TrustDates.long(device.addedAt).orEmpty())

        now - seen < ACTIVE_WINDOW_MS -> stringResource(StringsR.string.devices_active_now)

        else -> stringResource(
            StringsR.string.devices_last_seen,
            DateUtils.getRelativeTimeSpanString(seen, now, DateUtils.MINUTE_IN_MILLIS).toString().replaceFirstChar { it.lowercase() }
        )
    }
}

private const val ACTIVE_WINDOW_MS = 5 * 60 * 1000L

@Composable
private fun RequestCard(request: PairingRequestItem, onReview: (String) -> Unit) {
    AttentionCard(
        title = stringResource(StringsR.string.devices_request_title),
        body = stringResource(StringsR.string.devices_request_body, deviceDisplayName(request.deviceName, request.platform)),
        actionLabel = stringResource(StringsR.string.common_action_review),
        onAction = { onReview(request.id) },
        tone = CalloutTone.Info,
        icon = BentoIcons.MonitorSmartphone
    )
}

/** "Se añadió «X» a tu nube…": `Es mío` acknowledges, `No lo reconozco` starts the removal. */
@Composable
fun ReviewCard(device: DeviceResponse, busy: Boolean, failed: Boolean, actions: DevicesActions, modifier: Modifier = Modifier) {
    val c = BentoTheme.colors
    val date = TrustDates.long(device.firstSeenAt ?: device.addedAt).orEmpty()
    Column(
        modifier.fillMaxWidth().clip(BentoShapes.lg).background(c.warningSoft).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            BentoIcon(BentoIcons.ShieldAlert, contentDescription = null, tint = c.warningInk)
            Text(
                stringResource(StringsR.string.devices_review_title, deviceDisplayName(device.name, device.platform)),
                color = c.ink,
                style = BentoTheme.typography.bodyStrong
            )
        }
        Text(stringResource(StringsR.string.devices_review_body, date), color = c.ink, style = BentoTheme.typography.body)
        if (failed) Text(stringResource(StringsR.string.devices_review_failed), color = c.dangerInk, style = BentoTheme.typography.metadata)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            BentoButton(stringResource(StringsR.string.devices_review_mine), {
                actions.onAcknowledge(device)
            }, variant = BentoButtonVariant.Primary, size = BentoButtonSize.Small, loading = busy)
            BentoButton(stringResource(StringsR.string.devices_review_unknown), {
                actions.onRemove(device)
            }, variant = BentoButtonVariant.DangerGhost, size = BentoButtonSize.Small, enabled = !busy)
        }
    }
}

@Composable
private fun RemovalNoticeCard(notice: RemovalNotice, onDismiss: () -> Unit) {
    val body = buildString {
        append(
            if (notice.alsoRemoved > 0) {
                pluralStringResource(StringsR.plurals.devices_removed_more, notice.alsoRemoved, notice.name, notice.alsoRemoved)
            } else {
                stringResource(StringsR.string.devices_removed, notice.name)
            }
        )
        if (notice.sessionOpen) append(' ').append(stringResource(StringsR.string.devices_session_open, notice.name))
        if (notice.excludedSessionsOpen) append(' ').append(stringResource(StringsR.string.devices_excluded_sessions_open))
    }
    Callout(
        tone = CalloutTone.Success,
        body = body,
        icon = BentoIcons.CircleCheck,
        announce = BentoAnnounce.Polite,
        action = {
            BentoButton(
                stringResource(StringsR.string.common_action_close),
                onDismiss,
                variant = BentoButtonVariant.Ghost,
                size = BentoButtonSize.Small
            )
        }
    )
}

@Composable
private fun DeviceMenu(device: DeviceResponse, onRename: () -> Unit, onRemove: () -> Unit, onDismiss: () -> Unit) {
    BentoSheet(onDismissRequest = onDismiss, title = deviceDisplayName(device.name, device.platform)) {
        Column(Modifier.padding(bottom = 16.dp)) {
            ListRow(
                headline = stringResource(StringsR.string.common_action_rename),
                leading = { BentoIcon(BentoIcons.PencilLine, contentDescription = null, tint = BentoTheme.colors.inkMuted) },
                onClick = onRename
            )
            if (!device.current) {
                ListRow(
                    headline = stringResource(StringsR.string.devices_remove_action),
                    leading = { BentoIcon(BentoIcons.Trash2, contentDescription = null, tint = BentoTheme.colors.dangerInk) },
                    onClick = onRemove
                )
            }
        }
    }
}

@Composable
private fun RenameSheet(device: DeviceResponse, busy: Boolean, failed: Boolean, actions: DevicesActions) {
    val name = remember(device.id) { TextFieldState(device.name) }
    BentoSheet(onDismissRequest = actions.onRenameCancel, title = stringResource(StringsR.string.devices_rename_title)) {
        Column(Modifier.padding(horizontal = 24.dp).padding(bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            BentoTextField(
                state = name,
                label = stringResource(StringsR.string.devices_rename_label),
                error = if (failed) stringResource(StringsR.string.devices_rename_failed) else null,
                onKeyboardAction = { actions.onRenameSave(name.text.toString()) }
            )
            BentoButton(
                stringResource(StringsR.string.common_action_save),
                { actions.onRenameSave(name.text.toString()) },
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Primary,
                enabled = name.text.isNotBlank(),
                loading = busy
            )
        }
    }
}

/**
 * Quitar dispositivo: the consequences in plain sentences, who keeps access (uncheck unknown ones to remove them
 * too), then the irreversible confirm. The new recovery kit follows immediately.
 */
@Composable
fun RemovalSheet(removal: RemovalState, actions: DevicesActions) {
    BentoSheet(
        onDismissRequest = actions.onCancelRemoval,
        title = stringResource(StringsR.string.devices_remove_title, removal.device.name)
    ) {
        RemovalSheetBody(removal, actions)
    }
}

@Suppress("LongMethod")
@Composable
fun RemovalSheetBody(removal: RemovalState, actions: DevicesActions) {
    ObscuredTouchGuard() // SEC-09: the sheet's own window drops touches through overlays
    val c = BentoTheme.colors
    Column(Modifier.padding(horizontal = 24.dp).padding(bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(
            stringResource(StringsR.string.devices_remove_title, deviceDisplayName(removal.device.name, removal.device.platform)),
            color = c.ink,
            style = BentoTheme.typography.sectionTitle
        )
        listOf(
            StringsR.string.devices_remove_consequence_sync,
            StringsR.string.devices_remove_consequence_local,
            StringsR.string.devices_remove_consequence_kit
        ).forEach {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                BentoIcon(BentoIcons.Info, contentDescription = null, tint = c.inkMuted, modifier = Modifier.padding(top = 2.dp))
                Text(stringResource(it), color = c.ink, style = BentoTheme.typography.body)
            }
        }
        Spacer(Modifier.height(4.dp))
        Text(stringResource(StringsR.string.devices_remove_keep_title), color = c.ink, style = BentoTheme.typography.labelStrong)
        when {
            removal.loadingPreview -> Text(
                stringResource(StringsR.string.devices_remove_keep_loading),
                color = c.inkMuted,
                style = BentoTheme.typography.body
            )

            removal.previewFailed -> Callout(tone = CalloutTone.Warning, body = stringResource(StringsR.string.devices_remove_keep_failed))

            else -> {
                Text(stringResource(StringsR.string.devices_remove_keep_body), color = c.inkMuted, style = BentoTheme.typography.metadata)
                removal.recipients.forEach { recipient ->
                    if (recipient.current) {
                        ListRow(
                            headline = deviceDisplayName(recipient.name, recipient.platform),
                            supporting = stringResource(StringsR.string.devices_remove_this_keeps),
                            leading = { BentoIcon(BentoIcons.Smartphone, contentDescription = null, tint = c.inkMuted) }
                        )
                    } else {
                        dev.bento.designsystem.component.SwitchRow(
                            title = deviceDisplayName(recipient.name, recipient.platform),
                            summary = if (recipient.needsReview) stringResource(StringsR.string.devices_remove_unreviewed) else null,
                            checked = recipient.id !in removal.excluded,
                            onCheckedChange = { keep -> actions.onToggleKeep(recipient.id, keep) },
                            icon = DeviceLabels.icon(recipient.platform)
                        )
                    }
                }
            }
        }
        if (removal.excluded.isNotEmpty()) {
            Callout(
                tone = CalloutTone.Warning,
                title = pluralStringResource(StringsR.plurals.devices_remove_excluded, removal.excluded.size, removal.excluded.size),
                body = stringResource(StringsR.string.devices_remove_excluded_body)
            )
        }
        removal.failed?.let {
            Callout(
                tone = CalloutTone.Danger,
                body = stringResource(
                    if (it ==
                        RemovalFailure.ExclusionInvalid
                    ) {
                        StringsR.string.devices_remove_exclusion_invalid
                    } else {
                        StringsR.string.devices_remove_failed
                    }
                ),
                announce = BentoAnnounce.Assertive
            )
        }
        val count = 1 + removal.excluded.size
        BentoButton(
            text = if (count >
                1
            ) {
                pluralStringResource(StringsR.plurals.devices_remove_confirm_many, count, count)
            } else {
                stringResource(StringsR.string.devices_remove_confirm)
            },
            onClick = actions.onConfirmRemoval,
            modifier = Modifier.fillMaxWidth(),
            variant = BentoButtonVariant.Danger,
            size = BentoButtonSize.Large,
            enabled = !removal.loadingPreview,
            loading = removal.removing
        )
        BentoButton(
            stringResource(StringsR.string.common_action_cancel),
            actions.onCancelRemoval,
            Modifier.fillMaxWidth(),
            variant = BentoButtonVariant.Ghost,
            enabled = !removal.removing
        )
    }
}
