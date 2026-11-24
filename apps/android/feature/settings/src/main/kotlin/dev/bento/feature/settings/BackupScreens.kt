package dev.bento.feature.settings

import android.content.Intent
import android.net.Uri
import android.provider.Settings
import android.text.format.DateUtils
import android.text.format.Formatter
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.painter.BitmapPainter
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.bento.designsystem.component.AttentionCard
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonSize
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.BentoSheet
import dev.bento.designsystem.component.BentoSwitch
import dev.bento.designsystem.component.BrandMark
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.ErrorState
import dev.bento.designsystem.component.ListRow
import dev.bento.designsystem.component.LoadingState
import dev.bento.designsystem.component.SettingsRow
import dev.bento.designsystem.component.SwitchRow
import dev.bento.designsystem.component.Thumbnail
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.recovery.findActivity
import dev.bento.strings.R as StringsR

/** Everything the backup screens can do; defaults are no-ops so previews and screenshots pass only what they show. */
data class BackupActions(
    val onTurnOn: () -> Unit = {},
    val onTurnOff: () -> Unit = {},
    val onRationaleAccept: () -> Unit = {},
    val onRationaleDismiss: () -> Unit = {},
    val onBucket: (BucketRow, Boolean) -> Unit = { _, _ -> },
    val onWifiOnly: (Boolean) -> Unit = {},
    val onVideosWifiOnly: (Boolean) -> Unit = {},
    val onOnlyCharging: (Boolean) -> Unit = {},
    val onPause: (Boolean) -> Unit = {},
    val onRunNow: () -> Unit = {},
    val onFreeUp: () -> Unit = {},
    val onFreeUpConfirm: () -> Unit = {},
    val onFreeUpClose: () -> Unit = {},
    val onAllowAll: () -> Unit = {},
    val onChooseMore: () -> Unit = {},
    val onOpenSettings: () -> Unit = {},
    val onDismissLocation: () -> Unit = {},
    val onStallHelp: () -> Unit = {},
    val onStallDismiss: () -> Unit = {},
    val onRetry: () -> Unit = {},
    val onNotNow: () -> Unit = {},
    val onContinueWithout: () -> Unit = {}
)

/**
 * Wires a [BackupViewModel] to the system: media/location permission launchers, app settings, the system delete
 * request (Android 11+) or per-item consent (Android 10), and refreshes on every resume (permission revoked later).
 */
@Composable
internal fun rememberBackupActions(viewModel: BackupViewModel, onFinished: () -> Unit = {}): BackupActions {
    val context = LocalContext.current
    val activity = context.findActivity()
    val finished by rememberUpdatedState(onFinished)
    val mediaLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { _ ->
        val canAsk = activity != null && MediaPermissions.media().any { activity.shouldShowRequestPermissionRationale(it) }
        viewModel.onMediaResult(canAskAgain = canAsk)
    }
    val locationLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { viewModel.onLocationResult() }
    val deleteLauncher = rememberMediaDeleteLauncher(viewModel::onDeleteResult)
    val openSettings = {
        context.startActivity(
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", context.packageName, null))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        )
    }
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { viewModel.refresh() }
    LaunchedEffect(viewModel) {
        viewModel.effects.collect { effect ->
            when (effect) {
                is BackupEffect.RequestMedia -> mediaLauncher.launch(effect.permissions.toTypedArray())
                BackupEffect.RequestLocation -> locationLauncher.launch(MediaPermissions.LOCATION)
                BackupEffect.OpenAppSettings -> openSettings()
                is BackupEffect.DeleteRequest -> deleteLauncher(effect.uris)
                BackupEffect.Finished -> finished()
            }
        }
    }
    return BackupActions(
        onTurnOn = viewModel::turnOn,
        onTurnOff = viewModel::turnOff,
        onRationaleAccept = viewModel::rationaleAccepted,
        onRationaleDismiss = viewModel::rationaleDismissed,
        onBucket = viewModel::setBucket,
        onWifiOnly = viewModel::setWifiOnly,
        onVideosWifiOnly = viewModel::setVideosWifiOnly,
        onOnlyCharging = viewModel::setOnlyCharging,
        onPause = viewModel::setPaused,
        onRunNow = viewModel::runNow,
        onFreeUp = viewModel::openFreeUp,
        onFreeUpConfirm = viewModel::confirmFreeUp,
        onFreeUpClose = viewModel::closeFreeUp,
        // Android 14+ re-asking shows "Permitir todas" / "Seleccionar más fotos" in the system dialog itself.
        onAllowAll = { mediaLauncher.launch(MediaPermissions.media().toTypedArray()) },
        onChooseMore = { mediaLauncher.launch(MediaPermissions.media().toTypedArray()) },
        onOpenSettings = openSettings,
        onDismissLocation = viewModel::dismissLocationNotice,
        onStallHelp = {
            context.startActivity(
                Intent(
                    Intent.ACTION_VIEW,
                    Uri.parse(StallDetector.helpUrl(android.os.Build.MANUFACTURER))
                ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
        },
        onStallDismiss = viewModel::dismissStall,
        onRetry = viewModel::refresh,
        onNotNow = viewModel::notNow,
        onContinueWithout = viewModel::continueWithoutBackup
    )
}

/** Onboarding step 4 "Respalda este teléfono" (product/android.md §4.1), also reached from Fotos' backup card. */
@Composable
fun BackupSetupScreen(onDone: () -> Unit, modifier: Modifier = Modifier, viewModel: BackupViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val actions = rememberBackupActions(viewModel, onFinished = onDone)
    BackupSetupContent(state, actions, modifier)
}

/** Ajustes › Respaldo del teléfono (product/android.md §5, §9). */
@Composable
fun BackupSettingsScreen(onBack: (() -> Unit)?, modifier: Modifier = Modifier, viewModel: BackupViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val actions = rememberBackupActions(viewModel)
    BackupSettingsContent(state, actions, System.currentTimeMillis(), onBack, modifier)
}

@Composable
fun BackupSetupContent(state: BackupUiState, actions: BackupActions, modifier: Modifier = Modifier) {
    val settings = state.settings
    SettingsPage(stringResource(StringsR.string.backup_setup_title), onBack = null, modifier = modifier) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Box(Modifier.fillMaxWidth().padding(vertical = 8.dp), contentAlignment = Alignment.Center) {
                BrandMark(size = 96.dp)
            }
            Text(stringResource(StringsR.string.backup_setup_body), color = BentoTheme.colors.inkMuted, style = BentoTheme.typography.body)
        }
        SettingsGroup {
            SwitchRow(
                stringResource(StringsR.string.backup_policy_wifi),
                checked = settings?.wifiOnly ?: true,
                onCheckedChange = actions.onWifiOnly,
                icon = BentoIcons.Wifi
            )
            SwitchRow(
                stringResource(StringsR.string.backup_policy_charging),
                checked = settings?.onlyCharging ?: false,
                onCheckedChange = actions.onOnlyCharging,
                icon = BentoIcons.Plug
            )
        }
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            when {
                state.access == MediaAccess.Denied && state.deniedThisSession -> {
                    DeniedCallout(state, actions)
                    BentoButton(
                        stringResource(StringsR.string.common_action_continue),
                        actions.onContinueWithout,
                        Modifier.fillMaxWidth(),
                        variant = BentoButtonVariant.Primary,
                        size = BentoButtonSize.Large
                    )
                }

                else -> {
                    if (state.failed) Callout(tone = CalloutTone.Danger, body = stringResource(StringsR.string.common_error_generic))
                    BentoButton(
                        stringResource(StringsR.string.backup_setup_start),
                        actions.onTurnOn,
                        Modifier.fillMaxWidth(),
                        variant = BentoButtonVariant.Primary,
                        size = BentoButtonSize.Large,
                        leadingIcon = BentoIcons.CloudUpload,
                        loading = state.saving
                    )
                    BentoButton(
                        stringResource(StringsR.string.backup_setup_not_now),
                        actions.onNotNow,
                        Modifier.fillMaxWidth(),
                        variant = BentoButtonVariant.Ghost
                    )
                }
            }
        }
    }
    if (state.showRationale) RationaleSheet(actions)
}

@Composable
fun BackupSettingsContent(
    state: BackupUiState,
    actions: BackupActions,
    now: Long,
    onBack: (() -> Unit)?,
    modifier: Modifier = Modifier
) {
    SettingsPage(stringResource(StringsR.string.settings_section_backup), onBack, modifier) {
        when {
            state.loading -> LoadingState(Modifier.padding(32.dp))

            state.loadFailed -> ErrorState(
                body = stringResource(StringsR.string.common_error_generic),
                modifier = Modifier.padding(16.dp),
                onRetry = actions.onRetry
            )

            else -> BackupSettingsBody(state, actions, now)
        }
    }
    if (state.showRationale) RationaleSheet(actions)
    state.freeUp?.let { FreeUpSheet(it, actions) }
}

@Composable
private fun BackupSettingsBody(state: BackupUiState, actions: BackupActions, now: Long) {
    val settings = state.settings
    BackupHeaderCard(state.header, now)
    BackupCards(state, actions)
    SettingsGroup {
        SwitchRow(
            stringResource(StringsR.string.backup_switch),
            checked = state.configuredOn && state.access != MediaAccess.Denied,
            onCheckedChange = { if (it) actions.onTurnOn() else actions.onTurnOff() },
            summary = stringResource(StringsR.string.backup_switch_summary),
            icon = BentoIcons.CloudUpload,
            enabled = !state.saving
        )
        if (state.configuredOn) {
            val paused = state.policy?.paused == true
            SettingsRow(
                stringResource(if (paused) StringsR.string.common_action_resume else StringsR.string.common_action_pause_backup),
                onClick = { actions.onPause(!paused) },
                icon = if (paused) BentoIcons.Play else BentoIcons.Pause,
                showChevron = false
            )
            SettingsRow(
                stringResource(StringsR.string.backup_run_now),
                onClick = actions.onRunNow,
                summary = stringResource(StringsR.string.backup_run_now_summary),
                icon = BentoIcons.RotateCw,
                showChevron = false,
                enabled = !state.runningNow && (state.status?.pending ?: 0) > 0
            )
        }
    }
    if (state.buckets.isNotEmpty()) {
        SettingsGroup(stringResource(StringsR.string.backup_folders)) {
            state.buckets.forEach { row -> BucketRowView(row, actions, enabled = !state.saving) }
        }
    }
    SettingsGroup(stringResource(StringsR.string.backup_policy_title)) {
        SwitchRow(
            stringResource(StringsR.string.backup_policy_wifi),
            checked = settings?.wifiOnly ?: true,
            onCheckedChange = actions.onWifiOnly,
            summary = stringResource(StringsR.string.backup_policy_wifi_summary),
            icon = BentoIcons.Wifi
        )
        SwitchRow(
            stringResource(StringsR.string.backup_policy_videos_wifi),
            checked = !(settings?.videosOnMetered ?: false),
            onCheckedChange = actions.onVideosWifiOnly,
            icon = BentoIcons.Film,
            enabled = settings?.wifiOnly != true
        )
        SwitchRow(
            stringResource(StringsR.string.backup_policy_charging),
            checked = settings?.onlyCharging ?: false,
            onCheckedChange = actions.onOnlyCharging,
            icon = BentoIcons.Plug
        )
    }
    SettingsNote(stringResource(StringsR.string.backup_policy_battery_note))
    SettingsGroup {
        SettingsRow(
            stringResource(StringsR.string.backup_free_up),
            onClick = actions.onFreeUp,
            summary = stringResource(StringsR.string.backup_free_up_summary),
            icon = BentoIcons.Eraser
        )
    }
}

/** "Todo respaldado ✓ · hace 3 min" / "Quedan 340 · esperando Wi-Fi" / "Pausado · batería baja" (product/android.md §5). */
@Composable
fun backupHeaderText(header: BackupHeader, now: Long): String {
    androidx.compose.ui.platform.LocalConfiguration.current
    return BackupCopy.header(LocalContext.current, header, now)
}

/** The status line as text; shared by Ajustes, Cuenta y actividad and the Quick Settings tile subtitle. */
object BackupCopy {
    fun header(context: android.content.Context, header: BackupHeader, now: Long): String {
        val res = context.resources
        return when (header) {
            BackupHeader.Off -> context.getString(StringsR.string.backup_header_off)

            BackupHeader.NoAccess -> context.getString(StringsR.string.backup_header_no_access)

            is BackupHeader.Done -> header.lastBackupAt?.let {
                context.getString(StringsR.string.backup_header_done_ago, relativeTime(context, it, now))
            } ?: context.getString(StringsR.string.backup_header_done)

            is BackupHeader.Paused -> context.getString(
                if (header.lowBattery) StringsR.string.backup_header_paused_battery else StringsR.string.backup_header_paused
            )

            is BackupHeader.Running -> res.getQuantityString(StringsR.plurals.backup_header_running, header.pending, header.pending)

            is BackupHeader.Waiting -> res.getQuantityString(
                StringsR.plurals.backup_header_waiting,
                header.pending,
                header.pending,
                context.getString(waitReasonText(header.reason))
            )
        }
    }

    fun waitReasonText(reason: WaitReason): Int = when (reason) {
        WaitReason.Wifi -> StringsR.string.backup_wait_wifi
        WaitReason.Charging -> StringsR.string.backup_wait_charging
        WaitReason.Battery -> StringsR.string.backup_wait_battery
        WaitReason.Thermal -> StringsR.string.backup_wait_thermal
        WaitReason.Offline -> StringsR.string.backup_wait_offline
    }
}

internal fun relativeTime(context: android.content.Context, epochMs: Long, now: Long): String =
    if (now - epochMs < DateUtils.MINUTE_IN_MILLIS) {
        context.getString(StringsR.string.backup_just_now)
    } else {
        DateUtils.getRelativeTimeSpanString(epochMs.coerceAtMost(now), now, DateUtils.MINUTE_IN_MILLIS).toString().lowercase()
    }

@Composable
private fun BackupHeaderCard(header: BackupHeader, now: Long) {
    val c = BentoTheme.colors
    val (icon, tint) = when (header) {
        is BackupHeader.Done -> BentoIcons.CircleCheck to c.successInk
        is BackupHeader.Waiting -> (if (header.reason == WaitReason.Wifi) BentoIcons.WifiOff else BentoIcons.Timer) to c.inkMuted
        is BackupHeader.Paused -> (if (header.lowBattery) BentoIcons.BatteryLow else BentoIcons.CirclePause) to c.warningInk
        is BackupHeader.Running -> BentoIcons.CloudUpload to c.accent
        BackupHeader.NoAccess -> BentoIcons.TriangleAlert to c.warningInk
        BackupHeader.Off -> BentoIcons.CloudOff to c.inkMuted
    }
    Row(
        Modifier
            .padding(horizontal = 16.dp)
            .fillMaxWidth()
            .semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite }
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        BentoIcon(icon, contentDescription = null, tint = tint)
        Text(backupHeaderText(header, now), color = c.ink, style = BentoTheme.typography.sectionTitle)
    }
}

/** Calm cards for access and health states; at most one access card at a time (product/android.md §6, §11). */
@Composable
private fun BackupCards(state: BackupUiState, actions: BackupActions) {
    val padding = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
    when {
        state.revoked -> AttentionCard(
            title = stringResource(StringsR.string.backup_revoked_title),
            body = stringResource(StringsR.string.backup_revoked_body),
            actionLabel = stringResource(StringsR.string.backup_allow_access),
            onAction = if (state.permanentlyDenied) actions.onOpenSettings else actions.onTurnOn,
            tone = CalloutTone.Warning,
            modifier = padding
        )

        state.access == MediaAccess.Denied && state.deniedThisSession -> Box(padding) { DeniedCallout(state, actions) }

        state.access == MediaAccess.Partial && state.configuredOn -> PartialCard(state.visibleCount, actions, padding)
    }
    if (state.showLocationNotice) {
        AttentionCard(
            title = stringResource(StringsR.string.backup_location_title),
            body = stringResource(StringsR.string.backup_location_body),
            actionLabel = stringResource(StringsR.string.backup_location_ok),
            onAction = actions.onDismissLocation,
            tone = CalloutTone.Info,
            modifier = padding
        )
    }
    if (state.stalled) StallCard(actions.onStallHelp, actions.onStallDismiss, padding)
}

/** "Bento solo ve 12 fotos" with `Permitir todas` and `Elegir más` (never nagging: only here and in Fotos' card). */
@Composable
fun PartialCard(visible: Int, actions: BackupActions, modifier: Modifier = Modifier) {
    Callout(
        modifier = modifier,
        tone = CalloutTone.Info,
        title = pluralStringResource(StringsR.plurals.backup_partial_title, visible, visible),
        body = stringResource(StringsR.string.backup_partial_body),
        action = {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                BentoButton(stringResource(StringsR.string.backup_partial_allow_all), actions.onAllowAll, size = BentoButtonSize.Small)
                BentoButton(
                    stringResource(StringsR.string.backup_partial_choose_more),
                    actions.onChooseMore,
                    size = BentoButtonSize.Small,
                    variant = BentoButtonVariant.Ghost
                )
            }
        }
    )
}

/** OEM background killer card (product/android.md §11): vendor help page, never a battery-exemption request. */
@Composable
fun StallCard(onHelp: () -> Unit, onDismiss: () -> Unit, modifier: Modifier = Modifier) {
    AttentionCard(
        title = stringResource(StringsR.string.backup_stall_title),
        body = stringResource(StringsR.string.backup_stall_body),
        actionLabel = stringResource(StringsR.string.backup_stall_help),
        onAction = onHelp,
        onDismiss = onDismiss,
        tone = CalloutTone.Warning,
        icon = BentoIcons.TriangleAlert,
        modifier = modifier
    )
}

@Composable
private fun DeniedCallout(state: BackupUiState, actions: BackupActions) {
    Callout(
        tone = CalloutTone.Neutral,
        title = stringResource(StringsR.string.backup_denied_title),
        body = stringResource(StringsR.string.backup_denied_body),
        action = {
            BentoButton(
                stringResource(if (state.permanentlyDenied) StringsR.string.backup_open_settings else StringsR.string.backup_allow_access),
                if (state.permanentlyDenied) actions.onOpenSettings else actions.onRationaleAccept,
                size = BentoButtonSize.Small
            )
        }
    )
}

@Composable
private fun RationaleSheet(actions: BackupActions) {
    BentoSheet(onDismissRequest = actions.onRationaleDismiss, title = stringResource(StringsR.string.backup_rationale_title)) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Text(
                stringResource(StringsR.string.backup_rationale_body),
                color = BentoTheme.colors.inkMuted,
                style = BentoTheme.typography.body
            )
            BentoButton(
                stringResource(StringsR.string.common_action_continue),
                actions.onRationaleAccept,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Primary
            )
        }
    }
}

@Composable
private fun BucketRowView(row: BucketRow, actions: BackupActions, enabled: Boolean) {
    val countLabel = pluralStringResource(StringsR.plurals.backup_bucket_count, row.count, row.count)
    val supporting = if (row.enabled && row.pending > 0) {
        pluralStringResource(StringsR.plurals.backup_bucket_pending, row.pending, countLabel, row.pending)
    } else {
        countLabel
    }
    ListRow(
        headline = row.name,
        supporting = supporting,
        leading = { BucketThumbnail(row.thumbnail) },
        trailing = { BentoSwitch(checked = row.enabled, onCheckedChange = null, enabled = enabled) },
        onClick = { actions.onBucket(row, !row.enabled) },
        enabled = enabled
    )
}

/** The bucket's newest item via `ContentResolver.loadThumbnail` (system-sized, never the original). */
@Composable
private fun BucketThumbnail(uri: Uri?) {
    val context = LocalContext.current
    val px = with(LocalDensity.current) { 48.dp.roundToPx() }
    val bitmap by produceState<android.graphics.Bitmap?>(null, uri) {
        value = uri?.let { kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { CameraRoll.thumbnail(context, it, px) } }
    }
    Box(Modifier.size(48.dp).clip(BentoShapes.md)) {
        Thumbnail(painter = bitmap?.let { BitmapPainter(it.asImageBitmap()) }, contentDescription = null)
    }
}

// Liberar espacio ------------------------------------------------------------------------------------------------

@Composable
private fun FreeUpSheet(state: FreeUpState, actions: BackupActions) {
    BentoSheet(onDismissRequest = actions.onFreeUpClose, title = stringResource(StringsR.string.backup_free_up)) {
        FreeUpSheetBody(state, actions)
    }
}

@Composable
fun FreeUpSheetBody(state: FreeUpState, actions: BackupActions) {
    val context = LocalContext.current
    Column(Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        when (state) {
            FreeUpState.Loading, FreeUpState.Deleting -> LoadingState()

            is FreeUpState.Preview -> if (state.preview.count == 0) {
                Text(
                    stringResource(StringsR.string.backup_free_up_nothing),
                    color = BentoTheme.colors.inkMuted,
                    style = BentoTheme.typography.body
                )
                BentoButton(stringResource(StringsR.string.common_action_close), actions.onFreeUpClose, Modifier.fillMaxWidth())
            } else {
                val size = Formatter.formatShortFileSize(context, state.preview.totalBytes)
                Text(
                    pluralStringResource(StringsR.plurals.backup_free_up_preview, state.preview.count, state.preview.count, size),
                    color = BentoTheme.colors.ink,
                    style = BentoTheme.typography.bodyStrong
                )
                Text(
                    stringResource(StringsR.string.backup_free_up_explain),
                    color = BentoTheme.colors.inkMuted,
                    style = BentoTheme.typography.body
                )
                BentoButton(
                    stringResource(StringsR.string.backup_free_up_confirm, size),
                    actions.onFreeUpConfirm,
                    Modifier.fillMaxWidth(),
                    variant = BentoButtonVariant.Primary
                )
            }

            is FreeUpState.Done -> {
                Text(
                    pluralStringResource(
                        StringsR.plurals.backup_free_up_done,
                        state.count,
                        state.count,
                        Formatter.formatShortFileSize(context, state.bytes)
                    ),
                    color = BentoTheme.colors.ink,
                    style = BentoTheme.typography.bodyStrong,
                    modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }
                )
                BentoButton(stringResource(StringsR.string.common_action_close), actions.onFreeUpClose, Modifier.fillMaxWidth())
            }

            FreeUpState.Cancelled -> {
                Text(
                    stringResource(StringsR.string.backup_free_up_cancelled),
                    color = BentoTheme.colors.inkMuted,
                    style = BentoTheme.typography.body
                )
                BentoButton(stringResource(StringsR.string.common_action_close), actions.onFreeUpClose, Modifier.fillMaxWidth())
            }

            FreeUpState.Failed -> {
                Callout(tone = CalloutTone.Danger, body = stringResource(StringsR.string.common_error_generic))
                BentoButton(stringResource(StringsR.string.common_action_retry), actions.onFreeUp, Modifier.fillMaxWidth())
            }
        }
    }
}
