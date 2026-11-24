package dev.bento.designsystem.theme

import android.os.Build
import android.view.HapticFeedbackConstants
import android.view.View
import androidx.compose.runtime.Composable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.platform.LocalView

/** The only haptic moments in Bento (design-system/android.md §7). No haptics on scroll or routine taps. */
public enum class BentoHaptic {
    /** Entering selection mode. */
    LongPress,

    /** Grid density steps and fast-scroller year ticks. */
    SegmentTick,

    /** Successful pairing or QR detection. */
    Confirm,

    /** Invalid code. */
    Reject,
}

public fun interface BentoHaptics {
    public fun perform(haptic: BentoHaptic)
}

/** Uses [View.performHapticFeedback], which honors the system haptics setting (no ignore flags). */
internal class ViewHaptics(private val view: View) : BentoHaptics {
    override fun perform(haptic: BentoHaptic) {
        val constant = when (haptic) {
            BentoHaptic.LongPress -> HapticFeedbackConstants.LONG_PRESS
            BentoHaptic.SegmentTick ->
                if (Build.VERSION.SDK_INT >= 34) HapticFeedbackConstants.SEGMENT_TICK else HapticFeedbackConstants.CLOCK_TICK
            BentoHaptic.Confirm ->
                if (Build.VERSION.SDK_INT >= 30) HapticFeedbackConstants.CONFIRM else HapticFeedbackConstants.VIRTUAL_KEY
            BentoHaptic.Reject ->
                if (Build.VERSION.SDK_INT >= 30) HapticFeedbackConstants.REJECT else HapticFeedbackConstants.LONG_PRESS
        }
        view.performHapticFeedback(constant)
    }
}

/** Override in tests to record haptics. `null` means: use the current view. */
public val LocalBentoHaptics: androidx.compose.runtime.ProvidableCompositionLocal<BentoHaptics?> =
    staticCompositionLocalOf { null }

@Composable
@ReadOnlyComposable
public fun bentoHaptics(): BentoHaptics = LocalBentoHaptics.current ?: ViewHaptics(LocalView.current)
