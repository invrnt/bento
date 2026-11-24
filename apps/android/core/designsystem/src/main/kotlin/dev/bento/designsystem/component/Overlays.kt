package dev.bento.designsystem.component

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.BasicAlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.ModalBottomSheetProperties
import androidx.compose.material3.SheetState
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Stable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.paneTitle
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.window.SecureFlagPolicy
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoElevation
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.designsystem.theme.bentoShadow
import dev.bento.strings.R as StringsR

/**
 * State of a [BentoSheet]: opens half-expanded and can be dragged to full height (product/android.md §7).
 * Wraps Material's experimental SheetState so features need no opt-in.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Stable
public class BentoSheetState internal constructor(internal val material: SheetState) {
    public val isVisible: Boolean get() = material.isVisible

    /** Animates the sheet away; call `onDismissRequest`'s state change after it returns. */
    public suspend fun hide(): Unit = material.hide()

    public suspend fun expand(): Unit = material.expand()
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
public fun rememberBentoSheetState(): BentoSheetState {
    val material = rememberModalBottomSheetState(skipPartiallyExpanded = false)
    return remember(material) { BentoSheetState(material) }
}

/** Drag handle: 36×4 dp in `line-strong`, inside a 48 dp touch row. */
@Composable
public fun BentoSheetHandle(modifier: Modifier = Modifier) {
    val label = stringResource(StringsR.string.ds_sheet_handle)
    Box(
        modifier
            .fillMaxWidth()
            .padding(top = 10.dp, bottom = 6.dp)
            .semantics { contentDescription = label },
        contentAlignment = Alignment.Center,
    ) {
        Box(Modifier.size(width = 36.dp, height = 4.dp).clip(BentoShapes.full).background(BentoTheme.colors.lineStrong))
    }
}

/** Sheet body shared by [BentoSheet] and its screenshots: optional title, then content with 16/24 dp gutters. */
@Composable
internal fun BentoSheetBody(title: String?, content: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, bottom = 24.dp)) {
        if (title != null) {
            Text(
                title,
                color = BentoTheme.colors.ink,
                style = BentoTheme.typography.sectionTitle,
                modifier = Modifier.padding(top = 4.dp, bottom = 12.dp).semantics { heading() },
            )
        }
        content()
    }
}

/**
 * Modal bottom sheet (half → full) on `raised` with 18 dp top corners, Bento handle and scrim. Material 3 provides
 * drag, the scale-on-predictive-back animation and back dismissal; the sheet spring follows the finger.
 * [secure] sets FLAG_SECURE for codes and recovery content (product/android.md §10).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
public fun BentoSheet(
    onDismissRequest: () -> Unit,
    modifier: Modifier = Modifier,
    sheetState: BentoSheetState = rememberBentoSheetState(),
    title: String? = null,
    secure: Boolean = false,
    content: @Composable ColumnScope.() -> Unit,
) {
    val c = BentoTheme.colors
    ModalBottomSheet(
        onDismissRequest = onDismissRequest,
        modifier = modifier.semantics { if (title != null) paneTitle = title },
        sheetState = sheetState.material,
        sheetMaxWidth = 640.dp,
        shape = BentoShapes.sheet,
        containerColor = c.raised,
        contentColor = c.ink,
        tonalElevation = 0.dp,
        scrimColor = c.scrim,
        dragHandle = { BentoSheetHandle() },
        properties = ModalBottomSheetProperties(securePolicy = if (secure) SecureFlagPolicy.SecureOn else SecureFlagPolicy.Inherit),
    ) {
        BentoSheetBody(title, content)
    }
}

/** Card of [BentoDialog]; internal so screenshots can render it without a window. */
@Composable
internal fun BentoDialogCard(
    title: String,
    consequence: String,
    confirmLabel: String,
    onConfirm: () -> Unit,
    dismissLabel: String,
    onDismiss: () -> Unit,
    icon: ImageVector,
) {
    val c = BentoTheme.colors
    Column(
        Modifier
            .widthIn(max = 440.dp)
            .bentoShadow(BentoElevation.Xl, BentoShapes.xl)
            .clip(BentoShapes.xl)
            .background(c.raised)
            .padding(24.dp)
            .semantics { paneTitle = title },
    ) {
        Box(Modifier.size(44.dp).clip(BentoShapes.lg).background(c.dangerSoft), contentAlignment = Alignment.Center) {
            BentoIcon(icon, contentDescription = null, tint = c.dangerInk)
        }
        Text(title, color = c.ink, style = BentoTheme.typography.sectionTitle, modifier = Modifier.padding(top = 16.dp).semantics { heading() })
        Text(consequence, color = c.inkMuted, style = BentoTheme.typography.body, modifier = Modifier.padding(top = 6.dp))
        BoxWithConstraints(Modifier.fillMaxWidth().padding(top = 24.dp)) {
            if (maxWidth < 340.dp) {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    BentoButton(confirmLabel, onConfirm, Modifier.fillMaxWidth(), variant = BentoButtonVariant.Danger)
                    BentoButton(dismissLabel, onDismiss, Modifier.fillMaxWidth(), variant = BentoButtonVariant.Ghost)
                }
            } else {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End)) {
                    BentoButton(dismissLabel, onDismiss, variant = BentoButtonVariant.Secondary)
                    BentoButton(confirmLabel, onConfirm, variant = BentoButtonVariant.Danger)
                }
            }
        }
    }
}

/**
 * Only for destructive confirmations ("Eliminar para siempre", "Quitar dispositivo"). [consequence] explains, in one
 * sentence, what will happen; never "¿Estás seguro?". Back and outside taps dismiss.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
public fun BentoDialog(
    title: String,
    consequence: String,
    confirmLabel: String,
    onConfirm: () -> Unit,
    onDismissRequest: () -> Unit,
    dismissLabel: String = stringResource(StringsR.string.common_action_cancel),
    icon: ImageVector = BentoIcons.Trash2,
) {
    BasicAlertDialog(onDismissRequest = onDismissRequest, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Box(Modifier.padding(horizontal = 24.dp), contentAlignment = Alignment.Center) {
            BentoDialogCard(title, consequence, confirmLabel, onConfirm, dismissLabel, onDismissRequest, icon)
        }
    }
}
