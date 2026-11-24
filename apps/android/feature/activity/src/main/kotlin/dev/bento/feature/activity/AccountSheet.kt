package dev.bento.feature.activity

import android.text.format.Formatter
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonSize
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.BentoSheet
import dev.bento.designsystem.component.ListRow
import dev.bento.designsystem.component.ProgressBar
import dev.bento.designsystem.component.SettingsRow
import dev.bento.designsystem.component.StatusAvatar
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.files.ImportFailureLog
import dev.bento.feature.settings.BackupCopy
import dev.bento.feature.settings.BackupHeader
import dev.bento.feature.settings.MediaAccess
import dev.bento.feature.settings.StallCard
import dev.bento.strings.R as StringsR

/** Where the sheet's rows and attention actions lead (the shell decides the routes). */
data class ActivityNavigation(
    val onDevices: () -> Unit = {},
    val onTrash: () -> Unit = {},
    val onSettings: () -> Unit = {},
    val onBackupSettings: () -> Unit = {},
    val onRecovery: () -> Unit = {},
    val onReconnect: () -> Unit = {},
    val onDeviceReview: (String) -> Unit = {},
    val onDeviceRemoved: () -> Unit = {},
    val onStallHelp: () -> Unit = {}
)

/** What the sheet does locally (pause, retry, dismiss). */
data class ActivityActions(
    val onPause: (Boolean) -> Unit = {},
    val onRetry: (String) -> Unit = {},
    val onRetrySync: () -> Unit = {},
    val onDismissImport: (dev.bento.feature.files.ImportFailure) -> Unit = {},
    val onDismissStall: () -> Unit = {}
)

/**
 * The account/status avatar for every top bar (product/android.md §3, §7): its ring is the global status, a tap opens
 * the Cuenta y actividad sheet. TalkBack reads the name and the status.
 */
@Composable
fun AccountAvatar(navigation: ActivityNavigation, modifier: Modifier = Modifier, viewModel: ActivityViewModel = hiltViewModel()) {
    val overview by viewModel.overview.collectAsStateWithLifecycle()
    val busy by viewModel.busy.collectAsStateWithLifecycle()
    var open by rememberSaveable { mutableStateOf(false) }
    val name = overview.accountName ?: stringResource(StringsR.string.activity_account_fallback)
    StatusAvatar(name = name, status = overview.avatar, onClick = { open = true }, modifier = modifier, progress = overview.progress)
    if (open) {
        val close = { open = false }
        val closing = navigation.closingWith(close)
        BentoSheet(onDismissRequest = close, title = stringResource(StringsR.string.activity_sheet_title)) {
            // Many attention items can exceed the full-height sheet: the body scrolls (nested with the sheet drag).
            Column(Modifier.verticalScroll(rememberScrollState())) { AccountSheetBody(overview, actions(viewModel), closing, busy) }
        }
    }
}

internal fun actions(viewModel: ActivityViewModel) = ActivityActions(
    onPause = viewModel::setPaused,
    onRetry = viewModel::retry,
    onRetrySync = viewModel::retrySync,
    onDismissImport = viewModel::dismiss,
    onDismissStall = viewModel::dismissStall
)

/** Every navigation from the sheet closes it first. */
private fun ActivityNavigation.closingWith(close: () -> Unit) = ActivityNavigation(
    onDevices = {
        close()
        onDevices()
    },
    onTrash = {
        close()
        onTrash()
    },
    onSettings = {
        close()
        onSettings()
    },
    onBackupSettings = {
        close()
        onBackupSettings()
    },
    onRecovery = {
        close()
        onRecovery()
    },
    onReconnect = {
        close()
        onReconnect()
    },
    onDeviceReview = {
        close()
        onDeviceReview(it)
    },
    onDeviceRemoved = {
        close()
        onDeviceRemoved()
    },
    onStallHelp = onStallHelp
)

/** Sheet content: avatar + name + usage, status line, transfers, attention items, then pause/devices/trash/settings. */
@Composable
fun AccountSheetBody(overview: ActivityOverview, actions: ActivityActions, navigation: ActivityNavigation, busy: Boolean = false) {
    Column(Modifier.fillMaxWidth().padding(bottom = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        AccountHeader(overview)
        ActivityDetails(overview, actions, navigation, busy)
        Column(Modifier.padding(horizontal = 8.dp)) {
            if (overview.backupOn) {
                SettingsRow(
                    stringResource(
                        if (overview.paused) StringsR.string.common_action_resume else StringsR.string.common_action_pause_backup
                    ),
                    onClick = { actions.onPause(!overview.paused) },
                    icon = if (overview.paused) BentoIcons.Play else BentoIcons.Pause,
                    showChevron = false,
                    enabled = !busy
                )
            }
            SettingsRow(
                stringResource(StringsR.string.settings_section_devices),
                onClick = navigation.onDevices,
                icon = BentoIcons.MonitorSmartphone
            )
            SettingsRow(stringResource(StringsR.string.activity_trash), onClick = navigation.onTrash, icon = BentoIcons.Trash2)
            SettingsRow(stringResource(StringsR.string.settings_title), onClick = navigation.onSettings, icon = BentoIcons.Settings2)
        }
    }
}

@Composable
private fun AccountHeader(overview: ActivityOverview) {
    val context = LocalContext.current
    val c = BentoTheme.colors
    val name = overview.accountName ?: stringResource(StringsR.string.activity_account_fallback)
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        StatusAvatar(name = name, status = overview.avatar, onClick = {}, progress = overview.progress, size = 44.dp)
        Column(Modifier.weight(1f)) {
            Text(name, color = c.ink, style = BentoTheme.typography.sectionTitle)
            val usage = overview.usageBytes
            val devices = overview.devices
            if (usage != null && devices != null) {
                Text(
                    stringResource(
                        StringsR.string.settings_account_usage,
                        Formatter.formatShortFileSize(context, usage),
                        pluralStringResource(StringsR.plurals.common_count_devices, devices, devices)
                    ),
                    color = c.inkMuted,
                    style = BentoTheme.typography.metadata
                )
            }
        }
    }
}

/** Status line, transfers, stall card and attention items; shared by the sheet and the Activity screen. */
@Composable
fun ColumnScope.ActivityDetails(overview: ActivityOverview, actions: ActivityActions, navigation: ActivityNavigation, busy: Boolean) {
    val c = BentoTheme.colors
    Text(
        statusLineText(overview.status),
        color = c.ink,
        style = BentoTheme.typography.bodyStrong,
        modifier = Modifier.padding(horizontal = 24.dp).semantics { liveRegion = LiveRegionMode.Polite }
    )
    Transfers(overview)
    if (overview.stalled) {
        StallCard(navigation.onStallHelp, actions.onDismissStall, Modifier.padding(horizontal = 16.dp))
    }
    val attention = overview.attention
    if (attention.isNotEmpty()) {
        Text(
            stringResource(StringsR.string.activity_attention_title),
            color = c.inkMuted,
            style = BentoTheme.typography.labelStrong,
            modifier = Modifier.padding(start = 24.dp, top = 8.dp)
        )
        Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            attention.forEach { entry -> AttentionRow(entry, actions, navigation, busy) }
        }
    }
}

@Composable
private fun Transfers(overview: ActivityOverview) {
    val context = LocalContext.current
    val a = overview.activity
    var expanded by rememberSaveable { mutableStateOf(false) }
    val rows = buildList {
        if (a.uploads.count > 0) add(Triple(BentoIcons.Upload, a.uploads, StringsR.plurals.activity_transfer_uploads))
        if (a.downloads.count > 0) add(Triple(BentoIcons.Download, a.downloads, StringsR.plurals.activity_transfer_downloads))
    }
    val backup = overview.backup?.takeIf { it.pending > 0 && overview.backupOn }
    if (rows.isEmpty() && backup == null) return
    Column(
        Modifier.padding(
            horizontal = 16.dp
        ).fillMaxWidth().clip(BentoShapes.lg).background(BentoTheme.colors.subtle).padding(vertical = 4.dp)
    ) {
        rows.forEach { (icon, stats, plural) ->
            val title = pluralStringResource(plural, stats.count, stats.count)
            val bytes = if (stats.bytesTotal > 0) {
                stringResource(
                    StringsR.string.common_unit_progress_of,
                    Formatter.formatShortFileSize(context, stats.bytesDone),
                    Formatter.formatShortFileSize(context, stats.bytesTotal)
                )
            } else {
                null
            }
            ListRow(
                headline = title,
                supporting = bytes,
                leading = { BentoIcon(icon, contentDescription = null, tint = BentoTheme.colors.accent) },
                onClick = { expanded = !expanded },
                onClickLabel = stringResource(if (expanded) StringsR.string.activity_collapse else StringsR.string.activity_expand)
            )
            if (expanded || stats.fraction != null) {
                ProgressBar(
                    progress = stats.fraction,
                    modifier = Modifier.padding(start = 66.dp, end = 16.dp, bottom = 8.dp),
                    label = listOfNotNull(title, bytes).joinToString(", ")
                )
            }
        }
        if (backup != null) {
            val header = BackupHeader.of(true, MediaAccess.Full, backup, overview.policy)
            ListRow(
                headline = stringResource(StringsR.string.activity_backup_row),
                supporting = BackupCopy.header(context, header, System.currentTimeMillis()),
                leading = { BentoIcon(BentoIcons.CloudUpload, contentDescription = null, tint = BentoTheme.colors.inkMuted) }
            )
        }
    }
}

@Composable
private fun AttentionRow(entry: AttentionEntry, actions: ActivityActions, navigation: ActivityNavigation, busy: Boolean) {
    val (title, body) = attentionText(entry)
    val action: Pair<String, () -> Unit>? = when (entry) {
        is AttentionEntry.ImportFailed -> stringResource(StringsR.string.activity_action_dismiss) to
            { actions.onDismissImport(entry.failure) }

        is AttentionEntry.Backend -> when (entry.action) {
            AttentionAction.Retry -> stringResource(StringsR.string.common_action_retry) to
                { entry.item.string("job_id")?.let(actions.onRetry) ?: Unit }

            AttentionAction.RetrySync -> stringResource(StringsR.string.common_action_retry) to actions.onRetrySync

            AttentionAction.Reconnect -> stringResource(StringsR.string.common_action_reconnect) to navigation.onReconnect

            AttentionAction.SaveKit -> stringResource(StringsR.string.activity_action_save_kit) to navigation.onRecovery

            AttentionAction.ReviewDevice -> stringResource(StringsR.string.common_action_review) to {
                entry.item.string("device_id")?.let(navigation.onDeviceReview) ?: Unit
            }

            AttentionAction.ReviewRemoved -> stringResource(StringsR.string.common_action_review) to navigation.onDeviceRemoved

            AttentionAction.Dismiss, AttentionAction.None -> null
        }
    }
    val c = BentoTheme.colors
    Row(
        Modifier.fillMaxWidth().clip(BentoShapes.lg).background(c.raised).padding(14.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Box(Modifier.size(32.dp).clip(BentoShapes.md).background(c.warningSoft), contentAlignment = Alignment.Center) {
            BentoIcon(BentoIcons.TriangleAlert, contentDescription = null, tint = c.warningInk)
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Column(Modifier.semantics(mergeDescendants = true) {}) {
                Text(title, color = c.ink, style = BentoTheme.typography.bodyStrong)
                if (body != null) Text(body, color = c.inkMuted, style = BentoTheme.typography.metadata)
            }
            if (action != null) {
                BentoButton(
                    action.first,
                    action.second,
                    size = BentoButtonSize.Small,
                    enabled = !busy,
                    modifier = Modifier.padding(top = 8.dp)
                )
            }
        }
    }
}

/** Title and one sentence per attention kind (backend `AttentionKind`) and for local import failures. */
// One branch per kind, kept together so the copy reads against product/android.md §7.
@Suppress("CyclomaticComplexMethod")
@Composable
internal fun attentionText(entry: AttentionEntry): Pair<String, String?> = when (entry) {
    is AttentionEntry.ImportFailed -> stringResource(StringsR.string.activity_import_failed_title, entry.failure.name) to stringResource(
        when (entry.failure.reason) {
            ImportFailureLog.REASON_UNREADABLE -> StringsR.string.activity_import_unreadable
            ImportFailureLog.REASON_INTERRUPTED -> StringsR.string.activity_import_interrupted
            else -> StringsR.string.activity_import_failed
        }
    )

    is AttentionEntry.Backend -> {
        val item = entry.item
        when (item.kind) {
            "upload_failed" -> {
                val count = item.int("count")
                val label = item.string("label")
                if (label != null && count != null) {
                    pluralStringResource(StringsR.plurals.activity_attention_backup_failed, count, count, label) to
                        stringResource(StringsR.string.activity_attention_upload_failed_body)
                } else {
                    stringResource(StringsR.string.activity_attention_upload_failed) to
                        stringResource(StringsR.string.activity_attention_upload_failed_body)
                }
            }

            "sync_error" -> if (entry.action == AttentionAction.Reconnect) {
                stringResource(StringsR.string.activity_notif_signin_title) to stringResource(StringsR.string.activity_notif_signin_text)
            } else {
                stringResource(StringsR.string.activity_attention_sync_error) to
                    stringResource(StringsR.string.activity_attention_sync_error_body)
            }

            "recovery_kit" -> stringResource(StringsR.string.activity_notif_kit_title) to stringResource(
                if (item.string("reason") ==
                    "stale"
                ) {
                    StringsR.string.activity_attention_kit_stale
                } else {
                    StringsR.string.activity_notif_kit_text
                }
            )

            "new_device" -> stringResource(StringsR.string.bento_device_added_title, item.string("name").orEmpty()) to
                stringResource(StringsR.string.activity_attention_new_device_body)

            "device_removed" -> stringResource(StringsR.string.activity_notif_removed_title) to
                stringResource(StringsR.string.activity_notif_removed_text)

            "inbox_failed" -> stringResource(StringsR.string.activity_attention_inbox_failed) to
                stringResource(StringsR.string.activity_attention_inbox_failed_body)

            "clock_skew" -> {
                val minutes = item.int("skew_minutes") ?: 1
                pluralStringResource(
                    if (item.string("direction") ==
                        "behind"
                    ) {
                        StringsR.plurals.activity_attention_clock_behind
                    } else {
                        StringsR.plurals.activity_attention_clock_ahead
                    },
                    minutes,
                    minutes
                ) to stringResource(StringsR.string.activity_attention_clock_body)
            }

            else -> stringResource(StringsR.string.bento_attention_title) to null
        }
    }
}

/** "Todo al día ✓", "Subiendo 12 archivos · 3 min", "Sin conexión — se reanudará solo", "Telegram pidió esperar 4 min". */
@Composable
fun statusLineText(line: StatusLine): String = when (line) {
    StatusLine.UpToDate -> stringResource(StringsR.string.activity_status_up_to_date)

    StatusLine.Starting -> stringResource(StringsR.string.activity_status_starting)

    StatusLine.Syncing -> stringResource(StringsR.string.activity_status_syncing)

    StatusLine.Offline -> stringResource(StringsR.string.activity_status_offline)

    is StatusLine.FloodWait -> pluralStringResource(
        StringsR.plurals.activity_status_flood_wait,
        line.minutes.coerceAtLeast(1),
        line.minutes.coerceAtLeast(1)
    )

    is StatusLine.Paused -> stringResource(
        if (line.lowBattery) StringsR.string.backup_header_paused_battery else StringsR.string.backup_header_paused
    )

    is StatusLine.Uploading -> {
        val files = pluralStringResource(StringsR.plurals.activity_status_uploading, line.count, line.count)
        line.etaSeconds?.takeIf { it > 0 }?.let { stringResource(StringsR.string.activity_status_with_eta, files, eta(it)) } ?: files
    }

    is StatusLine.Downloading -> pluralStringResource(StringsR.plurals.activity_status_downloading, line.count, line.count)

    is StatusLine.Waiting -> pluralStringResource(
        StringsR.plurals.backup_header_waiting,
        line.pending,
        line.pending,
        stringResource(BackupCopy.waitReasonText(line.reason))
    )

    is StatusLine.Attention -> pluralStringResource(StringsR.plurals.activity_status_attention, line.count, line.count)
}

@Composable
private fun eta(seconds: Long): String = if (seconds < MINUTE) {
    pluralStringResource(StringsR.plurals.common_duration_seconds, seconds.toInt(), seconds.toInt())
} else {
    val minutes = ((seconds + MINUTE - 1) / MINUTE).toInt()
    pluralStringResource(StringsR.plurals.common_duration_minutes, minutes, minutes)
}

private const val MINUTE = 60L
