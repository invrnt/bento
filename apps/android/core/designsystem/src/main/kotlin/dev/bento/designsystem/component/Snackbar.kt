package dev.bento.designsystem.component

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalAccessibilityManager
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoElevation
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.designsystem.theme.bentoShadow
import kotlinx.coroutines.CancellableContinuation
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlin.coroutines.resume
import dev.bento.strings.R as StringsR

public enum class BentoSnackbarResult { Dismissed, ActionPerformed }

public enum class BentoSnackbarTone { Neutral, Success, Danger }

/** One visible message. Resolve it with [performAction] or [dismiss]. */
@Stable
public class BentoSnackbarData internal constructor(
    public val message: String,
    public val actionLabel: String?,
    public val durationMillis: Long,
    public val tone: BentoSnackbarTone,
    private val continuation: CancellableContinuation<BentoSnackbarResult>,
) {
    public fun performAction() {
        if (continuation.isActive) continuation.resume(BentoSnackbarResult.ActionPerformed)
    }

    public fun dismiss() {
        if (continuation.isActive) continuation.resume(BentoSnackbarResult.Dismissed)
    }
}

/**
 * Queue of snackbars, one at a time. Undo messages stay [UNDO_DURATION_MS] (6 s, product/android.md §1.5); others
 * [DEFAULT_DURATION_MS]. Both are stretched by the system's accessibility timeout when the user asked for more time.
 */
@Stable
public class BentoSnackbarHostState {
    private val mutex = Mutex()

    public var current: BentoSnackbarData? by mutableStateOf(null)
        private set

    public suspend fun show(
        message: String,
        actionLabel: String? = null,
        durationMillis: Long = if (actionLabel != null) UNDO_DURATION_MS else DEFAULT_DURATION_MS,
        tone: BentoSnackbarTone = BentoSnackbarTone.Neutral,
    ): BentoSnackbarResult = mutex.withLock {
        try {
            suspendCancellableCoroutine { cont -> current = BentoSnackbarData(message, actionLabel, durationMillis, tone, cont) }
        } finally {
            current = null
        }
    }

    /** "Se movió a la Papelera · Deshacer". Returns true when the person tapped the undo action. */
    public suspend fun showUndo(message: String, undoLabel: String): Boolean =
        show(message, actionLabel = undoLabel) == BentoSnackbarResult.ActionPerformed

    public companion object {
        public const val UNDO_DURATION_MS: Long = 6_000
        public const val DEFAULT_DURATION_MS: Long = 4_000
    }
}

@Composable
internal fun BentoSnackbar(data: BentoSnackbarData, modifier: Modifier = Modifier) {
    val c = BentoTheme.colors
    val (icon, tint) = when (data.tone) {
        BentoSnackbarTone.Neutral -> null to c.inkMuted
        BentoSnackbarTone.Success -> BentoIcons.CircleCheck to c.successInk
        BentoSnackbarTone.Danger -> BentoIcons.CircleAlert to c.dangerInk
    }
    Row(
        modifier
            .widthIn(max = 560.dp)
            .fillMaxWidth()
            .heightIn(min = 56.dp)
            .bentoShadow(BentoElevation.Lg, BentoShapes.lg)
            .clip(BentoShapes.lg)
            .background(c.raised)
            .border(1.dp, c.line, BentoShapes.lg)
            .semantics { liveRegion = if (data.tone == BentoSnackbarTone.Danger) LiveRegionMode.Assertive else LiveRegionMode.Polite }
            .padding(start = 16.dp, end = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (icon != null) BentoIcon(icon, contentDescription = null, tint = tint)
        Text(data.message, color = c.ink, style = BentoTheme.typography.body, modifier = Modifier.weight(1f).padding(vertical = 14.dp))
        if (data.actionLabel != null) {
            BentoTextAction(data.actionLabel, onClick = data::performAction)
        }
        BentoIconButton(BentoIcons.X, stringResource(StringsR.string.ds_dismiss), onClick = data::dismiss, dense = true)
    }
}

/** Accent text action used inside snackbars and section headers. */
@Composable
public fun BentoTextAction(text: String, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val c = BentoTheme.colors
    Box(
        modifier
            .heightIn(min = 48.dp)
            .clip(BentoShapes.md)
            .clickable(role = Role.Button, onClick = onClick)
            .padding(horizontal = 12.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, color = c.accentInk, style = BentoTheme.typography.labelStrong)
    }
}

/**
 * Hosts [BentoSnackbarHostState] above the navigation bar / FAB. Slides up (fade with reduced motion) and
 * dismisses itself after the duration, extended by the accessibility timeout.
 */
@Composable
public fun BentoSnackbarHost(hostState: BentoSnackbarHostState, modifier: Modifier = Modifier) {
    val current = hostState.current
    val accessibility = LocalAccessibilityManager.current
    // Keeps the last message on screen while it animates out.
    val lastShown = remember { mutableStateOf<BentoSnackbarData?>(null) }
    SideEffect { if (current != null) lastShown.value = current }
    val shown = current ?: lastShown.value
    LaunchedEffect(current) {
        if (current != null) {
            val timeout = accessibility?.calculateRecommendedTimeoutMillis(
                current.durationMillis,
                containsIcons = true,
                containsText = true,
                containsControls = current.actionLabel != null,
            ) ?: current.durationMillis
            delay(timeout)
            current.dismiss()
        }
    }
    val motion = BentoTheme.motion
    Box(modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), contentAlignment = Alignment.BottomCenter) {
        AnimatedVisibility(visible = current != null, enter = motion.slideUpIn, exit = motion.slideDownOut) {
            shown?.let { BentoSnackbar(it) }
        }
    }
}
