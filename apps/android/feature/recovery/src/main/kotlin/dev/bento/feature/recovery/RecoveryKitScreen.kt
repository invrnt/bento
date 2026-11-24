package dev.bento.feature.recovery

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.input.TextFieldState
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
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
import dev.bento.designsystem.component.CodeField
import dev.bento.designsystem.component.QrMatrix
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.strings.R as StringsR
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Why the kit is shown: first run (with `Más tarde`), after removing a device or rotating (mandatory). */
enum class KitOccasion { FirstRun, NewAfterRemoval, Rotated }

/** Transient result of copy / save / print, shown under the actions and announced politely. */
enum class KitNotice { Copied, CopyFailed, PdfSaved, PdfFailed, PrintFailed }

/** Everything the stateless kit content renders. */
data class RecoveryKitUi(
    val code: String,
    val occasion: KitOccasion,
    val confirm: KitConfirmState = KitConfirmState(),
    val notice: KitNotice? = null
)

/**
 * Guarda tu kit de recuperación (product/android.md §4.1 step 5): the code in 9 groups (Geist Mono, FLAG_SECURE),
 * `Guardar PDF` (SAF), `Imprimir`, `Copiar` (sensitive, cleared after 60 s), confirmation by typing the last group.
 * The code stays in memory only; it is passed in by the flow that received it.
 */
@Composable
fun RecoveryKitScreen(
    code: String,
    qr: QrMatrix?,
    occasion: KitOccasion,
    onConfirmed: () -> Unit,
    modifier: Modifier = Modifier,
    accountName: String? = null,
    vaultCreatedAt: String? = null,
    onLater: (() -> Unit)? = null,
    onBack: (() -> Unit)? = null,
    viewModel: RecoveryKitViewModel = hiltViewModel()
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val confirm by viewModel.state.collectAsStateWithLifecycle()
    var notice by remember { mutableStateOf<KitNotice?>(null) }
    val document = remember(code, qr, accountName, vaultCreatedAt) { RecoveryKitDocument(code, qr, accountName, vaultCreatedAt) }
    val fileName = stringResource(StringsR.string.recovery_pdf_file_name)
    val jobName = stringResource(StringsR.string.recovery_sheet_title)
    val createPdf = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/pdf")) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        scope.launch {
            val saved = withContext(Dispatchers.IO) {
                runCatching {
                    context.contentResolver.openOutputStream(uri, "wt")!!.use { RecoveryKitPdf.write(context, document, it) }
                }.isSuccess
            }
            notice = if (saved) KitNotice.PdfSaved else KitNotice.PdfFailed
        }
    }
    LaunchedEffect(confirm.confirmed) { if (confirm.confirmed) onConfirmed() }

    SecureWindow()
    ObscuredTouchGuard()
    RecoveryKitContent(
        ui = RecoveryKitUi(code, occasion, confirm, notice),
        onCopy = { notice = if (SensitiveClipboard.copy(context, RecoveryCodes.format(code))) KitNotice.Copied else KitNotice.CopyFailed },
        onSavePdf = { createPdf.launch(fileName) },
        onPrint = { if (!RecoveryKitPrint.print(context, jobName, document)) notice = KitNotice.PrintFailed },
        onConfirm = { typed -> viewModel.confirm(code, typed) },
        onTypedChange = viewModel::clearError,
        onLater = onLater,
        onBack = onBack,
        modifier = modifier
    )
}

@Composable
fun RecoveryKitContent(
    ui: RecoveryKitUi,
    onCopy: () -> Unit,
    onSavePdf: () -> Unit,
    onPrint: () -> Unit,
    onConfirm: (String) -> Unit,
    onTypedChange: () -> Unit,
    modifier: Modifier = Modifier,
    onLater: (() -> Unit)? = null,
    onBack: (() -> Unit)? = null,
    typed: TextFieldState = rememberTextFieldState()
) {
    val title = when (ui.occasion) {
        KitOccasion.FirstRun -> StringsR.string.recovery_kit_title
        KitOccasion.NewAfterRemoval, KitOccasion.Rotated -> StringsR.string.recovery_kit_new_title
    }
    val body = when (ui.occasion) {
        KitOccasion.FirstRun -> StringsR.string.recovery_kit_why
        KitOccasion.NewAfterRemoval -> StringsR.string.recovery_kit_new_after_removal
        KitOccasion.Rotated -> StringsR.string.recovery_kit_new_body
    }
    LaunchedEffect(typed) { snapshotFlow { typed.text.toString() }.collect { onTypedChange() } }
    SetupScaffold(
        title = stringResource(title),
        body = stringResource(body),
        hero = Hero.Icon(BentoIcons.LifeBuoy),
        onBack = onBack,
        modifier = modifier,
        actions = {
            val ready = typed.text.length == RecoveryCodes.GROUP
            // At 200 % the field can sit below the fold: the disabled button says what it is waiting for.
            val waiting = stringResource(StringsR.string.recovery_confirm_hint)
            BentoButton(
                text = stringResource(StringsR.string.recovery_confirm_submit),
                onClick = { onConfirm(typed.text.toString()) },
                modifier = Modifier.fillMaxWidth().semantics { if (!ready) stateDescription = waiting },
                variant = BentoButtonVariant.Primary,
                size = BentoButtonSize.Large,
                enabled = ready,
                loading = ui.confirm.confirming
            )
            if (onLater != null) {
                BentoButton(
                    text = stringResource(StringsR.string.recovery_later),
                    onClick = onLater,
                    modifier = Modifier.fillMaxWidth(),
                    variant = BentoButtonVariant.Ghost
                )
            }
        }
    ) {
        RecoveryCodeGroups(ui.code)
        Spacer(Modifier.height(12.dp))
        KitActions(onSavePdf, onPrint, onCopy)
        KitNoticeLine(ui.notice)
        Spacer(Modifier.height(16.dp))
        Callout(tone = CalloutTone.Warning, body = stringResource(StringsR.string.recovery_keep_safe), icon = BentoIcons.ShieldAlert)
        Spacer(Modifier.height(20.dp))
        CodeField(
            state = typed,
            label = stringResource(StringsR.string.recovery_confirm_label),
            length = RecoveryCodes.GROUP,
            hint = stringResource(StringsR.string.recovery_confirm_hint),
            error = when (ui.confirm.error) {
                KitConfirmError.Mismatch -> stringResource(StringsR.string.recovery_confirm_mismatch)
                KitConfirmError.Failed -> stringResource(StringsR.string.recovery_confirm_failed)
                null -> null
            },
            onComplete = onConfirm
        )
    }
}

/** The 9 groups, 3 per row; TalkBack reads one sentence with the characters spaced so they are spelled out. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun RecoveryCodeGroups(code: String, modifier: Modifier = Modifier) {
    val c = BentoTheme.colors
    val groups = RecoveryCodes.groups(code)
    val spoken = groups.joinToString(", ") { it.toCharArray().joinToString(" ") }
    val description = stringResource(StringsR.string.recovery_code_spoken, spoken)
    Column(
        modifier
            .fillMaxWidth()
            .clip(BentoShapes.xl)
            .background(c.sunken)
            .border(1.dp, c.line, BentoShapes.xl)
            .padding(10.dp)
            .clearAndSetSemantics { contentDescription = description }
    ) {
        groups.chunked(3).forEach { row ->
            Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                row.forEach { group ->
                    Box(
                        Modifier
                            .weight(1f)
                            .clip(BentoShapes.md)
                            .background(c.raised)
                            .border(1.dp, c.line, BentoShapes.md)
                            .padding(vertical = 10.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        Text(group, color = c.ink, style = BentoTheme.typography.monoLarge, textAlign = TextAlign.Center, maxLines = 1)
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun KitActions(onSavePdf: () -> Unit, onPrint: () -> Unit, onCopy: () -> Unit) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        BentoButton(
            stringResource(StringsR.string.recovery_action_save_pdf),
            onSavePdf,
            leadingIcon = BentoIcons.FileDown,
            size = BentoButtonSize.Small
        )
        BentoButton(
            stringResource(StringsR.string.recovery_action_print),
            onPrint,
            leadingIcon = BentoIcons.Printer,
            size = BentoButtonSize.Small
        )
        BentoButton(
            stringResource(StringsR.string.recovery_action_copy),
            onCopy,
            leadingIcon = BentoIcons.Copy,
            size = BentoButtonSize.Small
        )
    }
}

@Composable
private fun KitNoticeLine(notice: KitNotice?) {
    if (notice == null) return
    val (tone, text) = when (notice) {
        KitNotice.Copied -> CalloutTone.Warning to StringsR.string.recovery_copied
        KitNotice.CopyFailed -> CalloutTone.Danger to StringsR.string.recovery_copy_failed
        KitNotice.PdfSaved -> CalloutTone.Success to StringsR.string.recovery_pdf_saved
        KitNotice.PdfFailed -> CalloutTone.Danger to StringsR.string.recovery_pdf_failed
        KitNotice.PrintFailed -> CalloutTone.Danger to StringsR.string.recovery_print_failed
    }
    Spacer(Modifier.height(12.dp))
    Callout(
        tone = tone,
        body = stringResource(text),
        announce = BentoAnnounce.Polite,
        modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }
    )
}
