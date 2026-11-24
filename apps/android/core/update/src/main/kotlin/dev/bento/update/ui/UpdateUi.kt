package dev.bento.update.ui

import android.content.Context
import android.text.format.Formatter
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import dev.bento.designsystem.component.BentoAnnounce
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonSize
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.ProgressBar
import dev.bento.designsystem.component.SettingsRow
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.update.UpdateChecker
import dev.bento.update.UpdateFailure
import dev.bento.update.UpdateState
import java.text.NumberFormat
import javax.inject.Inject
import dev.bento.strings.R as StringsR

/** Callbacks of the card and the row; the stateful [UpdateCard]/[UpdateRow] bind them to [UpdateChecker]. */
data class UpdateActions(
    val onCheck: () -> Unit = {},
    val onDownload: () -> Unit = {},
    val onCancel: () -> Unit = {},
    val onInstall: () -> Unit = {},
    val onOpenSettings: () -> Unit = {},
    val onDismiss: () -> Unit = {},
    val onRetry: () -> Unit = {}
)

@HiltViewModel
class UpdateViewModel @Inject constructor(
    private val checker: UpdateChecker,
    @ApplicationContext context: Context
) : ViewModel() {
    val state = checker.state
    val showCard = checker.showCard
    val installedVersion: String = runCatching {
        context.packageManager.getPackageInfo(context.packageName, 0).versionName
    }.getOrNull().orEmpty()

    fun actions(context: Context) = UpdateActions(
        onCheck = checker::checkInBackground,
        onDownload = checker::download,
        onCancel = checker::cancelDownload,
        onInstall = checker::install,
        onOpenSettings = { checker.openUnknownSourcesSettings(context) },
        onDismiss = checker::dismiss,
        onRetry = checker::retry
    )

    fun onResume() = checker.refreshPermission()
}

/** The calm "Hay una versión nueva" card; renders nothing when there is no update to show. */
@Composable
fun UpdateCard(modifier: Modifier = Modifier, viewModel: UpdateViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val visible by viewModel.showCard.collectAsStateWithLifecycle()
    val context = LocalContext.current
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { viewModel.onResume() }
    if (visible) UpdateCardContent(state, viewModel.actions(context), modifier)
}

/** Ajustes › Acerca de: "Actualizaciones" with the installed version and the current step. */
@Composable
fun UpdateRow(modifier: Modifier = Modifier, viewModel: UpdateViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { viewModel.onResume() }
    UpdateRowContent(state, viewModel.installedVersion, viewModel.actions(context), modifier)
}

@Composable
fun UpdateCardContent(state: UpdateState, actions: UpdateActions, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    when (state) {
        is UpdateState.Available -> Card(
            modifier,
            CalloutTone.Info,
            stringResource(StringsR.string.update_available_title),
            stringResource(StringsR.string.update_available_body, state.release.version, size(context, state.release.sizeBytes))
        ) {
            Primary(StringsR.string.update_download, actions.onDownload)
            Ghost(StringsR.string.update_not_now, actions.onDismiss)
        }
        is UpdateState.Downloading -> Card(
            modifier,
            CalloutTone.Info,
            stringResource(StringsR.string.update_downloading_title, state.release.version),
            stringResource(StringsR.string.update_downloading_body)
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                ProgressBar(state.progress, label = stringResource(StringsR.string.update_downloading_label))
                Ghost(StringsR.string.update_cancel, actions.onCancel)
            }
        }
        is UpdateState.Ready -> if (state.needsPermission) {
            Card(
                modifier,
                CalloutTone.Warning,
                stringResource(StringsR.string.update_permission_title),
                stringResource(StringsR.string.update_permission_body)
            ) {
                Primary(StringsR.string.update_permission_action, actions.onOpenSettings)
                Ghost(StringsR.string.update_not_now, actions.onDismiss)
            }
        } else {
            Card(
                modifier,
                CalloutTone.Success,
                stringResource(StringsR.string.update_ready_title),
                stringResource(
                    if (state.cancelled) StringsR.string.update_cancelled_body else StringsR.string.update_ready_body,
                    state.release.version
                )
            ) {
                Primary(StringsR.string.update_install, actions.onInstall)
                Ghost(StringsR.string.update_not_now, actions.onDismiss)
            }
        }
        is UpdateState.Installing -> Card(
            modifier,
            CalloutTone.Info,
            stringResource(StringsR.string.update_installing_title, state.release.version),
            stringResource(StringsR.string.update_installing_body),
            action = null
        )
        is UpdateState.Failed -> Card(
            modifier,
            CalloutTone.Warning,
            stringResource(StringsR.string.update_failed_title),
            stringResource(failureText(state.reason)),
            announce = BentoAnnounce.Polite
        ) {
            if (state.reason != UpdateFailure.Incompatible) Primary(StringsR.string.update_retry, actions.onRetry)
            Ghost(StringsR.string.update_not_now, actions.onDismiss)
        }
        UpdateState.Unavailable, UpdateState.Checking, is UpdateState.Idle -> Unit
    }
}

@Composable
fun UpdateRowContent(state: UpdateState, installedVersion: String, actions: UpdateActions, modifier: Modifier = Modifier) {
    val (summary, onClick) = when (state) {
        UpdateState.Unavailable -> stringResource(StringsR.string.update_row_unavailable) to null
        is UpdateState.Idle -> stringResource(if (state.upToDate) StringsR.string.update_row_up_to_date else StringsR.string.update_row_check) to
            actions.onCheck
        UpdateState.Checking -> stringResource(StringsR.string.update_row_checking) to null
        is UpdateState.Available -> stringResource(StringsR.string.update_row_available, state.release.version) to actions.onDownload
        is UpdateState.Downloading -> state.progress?.let {
            stringResource(StringsR.string.update_row_downloading, state.release.version, percent(it))
        }.orEmpty().ifEmpty { stringResource(StringsR.string.update_row_downloading_unknown, state.release.version) } to null
        is UpdateState.Ready -> if (state.needsPermission) {
            stringResource(StringsR.string.update_permission_title) to actions.onOpenSettings
        } else {
            stringResource(StringsR.string.update_row_ready, state.release.version) to actions.onInstall
        }
        is UpdateState.Installing -> stringResource(StringsR.string.update_row_installing) to null
        is UpdateState.Failed -> stringResource(failureText(state.reason)) to actions.onRetry
    }
    SettingsRow(
        title = stringResource(StringsR.string.update_row_title),
        onClick = onClick ?: {},
        modifier = modifier,
        summary = summary,
        icon = BentoIcons.Download,
        value = installedVersion.takeIf { it.isNotEmpty() }?.let { stringResource(StringsR.string.update_row_version, it) },
        showChevron = false,
        enabled = onClick != null
    )
}

@Composable
private fun Card(
    modifier: Modifier,
    tone: CalloutTone,
    title: String,
    body: String,
    announce: BentoAnnounce = BentoAnnounce.None,
    action: (@Composable () -> Unit)? = null
) {
    Callout(
        modifier = modifier,
        tone = tone,
        title = title,
        body = body,
        icon = if (tone == CalloutTone.Warning) null else BentoIcons.Download,
        announce = announce,
        action = action?.let { content ->
            { FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) { content() } }
        }
    )
}

@Composable
private fun Primary(label: Int, onClick: () -> Unit) =
    BentoButton(stringResource(label), onClick, variant = BentoButtonVariant.Primary, size = BentoButtonSize.Small)

@Composable
private fun Ghost(label: Int, onClick: () -> Unit) =
    BentoButton(stringResource(label), onClick, variant = BentoButtonVariant.Ghost, size = BentoButtonSize.Small)

private fun failureText(reason: UpdateFailure): Int = when (reason) {
    UpdateFailure.Network -> StringsR.string.update_failed_network
    UpdateFailure.Signature -> StringsR.string.update_failed_signature
    UpdateFailure.Manifest -> StringsR.string.update_failed_manifest
    UpdateFailure.Incompatible -> StringsR.string.update_failed_incompatible
    UpdateFailure.Checksum -> StringsR.string.update_failed_checksum
    UpdateFailure.Signer -> StringsR.string.update_failed_signer
    UpdateFailure.Storage -> StringsR.string.update_failed_storage
    UpdateFailure.Install -> StringsR.string.update_failed_install
}

private fun size(context: Context, bytes: Long): String = Formatter.formatShortFileSize(context, bytes)

private fun percent(progress: Float): String = NumberFormat.getPercentInstance().format(progress.coerceIn(0f, 1f).toDouble())
