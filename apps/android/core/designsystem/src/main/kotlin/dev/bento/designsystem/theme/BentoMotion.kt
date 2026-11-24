package dev.bento.designsystem.theme

import android.animation.ValueAnimator
import android.database.ContentObserver
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.animation.core.FiniteAnimationSpec
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.unit.IntOffset
import dev.bento.designsystem.generated.BentoTokens

/**
 * Motion specs from brand.md §9 / android.md §6. With [reduced] every transform becomes a 120 ms fade.
 * Only opacity and transforms are animated; never the size of virtualized items.
 */
@Immutable
public class BentoMotion(public val reduced: Boolean) {
    private val easeOut = BentoTokens.Easing.easeOut

    /** 120 ms: color and hover changes. */
    public fun <T> color(): FiniteAnimationSpec<T> = tween(BentoTokens.Duration.fast, easing = easeOut)

    /** 180 ms: state changes (selected, expanded, checked). */
    public fun <T> state(): FiniteAnimationSpec<T> =
        if (reduced) tween(BentoTokens.Duration.fast) else tween(BentoTokens.Duration.base, easing = easeOut)

    /** 260 ms: layer entrances. */
    public fun <T> layer(): FiniteAnimationSpec<T> =
        if (reduced) tween(BentoTokens.Duration.fast) else tween(BentoTokens.Duration.slow, easing = easeOut)

    /** Finger-following surfaces (sheets, viewer dismiss): spring dampingRatio 0.9, stiffness 600. */
    public fun <T> follow(): FiniteAnimationSpec<T> =
        if (reduced) tween(BentoTokens.Duration.fast) else spring(dampingRatio = 0.9f, stiffness = 600f)

    /** Fade used where reduced motion replaces a transform. */
    public val fadeIn: EnterTransition get() = fadeIn(tween(BentoTokens.Duration.fast))
    public val fadeOut: ExitTransition get() = fadeOut(tween(BentoTokens.Duration.fast))

    /** `animate-slide-up`: floating bars, upload cards, snackbars. */
    public val slideUpIn: EnterTransition
        get() = if (reduced) fadeIn else {
            fadeIn(tween(BentoTokens.Duration.slideUp, easing = easeOut)) +
                slideInVertically(tween(BentoTokens.Duration.slideUp, easing = easeOut)) { it / 2 }
        }

    public val slideDownOut: ExitTransition
        get() = if (reduced) fadeOut else {
            fadeOut(tween(BentoTokens.Duration.base, easing = easeOut)) +
                slideOutVertically(tween(BentoTokens.Duration.base, easing = easeOut)) { it / 2 }
        }

    /** `animate-pop-in`: menus, dialogs (opacity + 3 % scale). */
    public val popIn: EnterTransition
        get() = if (reduced) fadeIn else {
            fadeIn(tween(BentoTokens.Duration.popIn, easing = easeOut)) +
                scaleIn(tween(BentoTokens.Duration.popIn, easing = easeOut), initialScale = 0.97f)
        }

    public val popOut: ExitTransition
        get() = if (reduced) fadeOut else {
            fadeOut(tween(BentoTokens.Duration.fast, easing = easeOut)) +
                scaleOut(tween(BentoTokens.Duration.fast, easing = easeOut), targetScale = 0.97f)
        }

    internal fun offsetSpring(): FiniteAnimationSpec<IntOffset> =
        if (reduced) tween(BentoTokens.Duration.fast) else spring(stiffness = Spring.StiffnessMediumLow)
}

internal val LocalBentoMotion = staticCompositionLocalOf { BentoMotion(reduced = false) }

/** True when the system removes animations (animator duration scale 0). Updates live. */
@Composable
internal fun rememberSystemReducedMotion(): Boolean {
    if (LocalInspectionMode.current) return false
    val context = LocalContext.current
    val resolver = context.contentResolver
    var reduced by remember { mutableStateOf(isAnimationDisabled(resolver)) }
    DisposableEffect(resolver) {
        val observer = object : ContentObserver(Handler(Looper.getMainLooper())) {
            override fun onChange(selfChange: Boolean) {
                reduced = isAnimationDisabled(resolver)
            }
        }
        resolver.registerContentObserver(Settings.Global.getUriFor(Settings.Global.ANIMATOR_DURATION_SCALE), false, observer)
        onDispose { resolver.unregisterContentObserver(observer) }
    }
    return reduced
}

private fun isAnimationDisabled(resolver: android.content.ContentResolver): Boolean {
    val scale = Settings.Global.getFloat(resolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f)
    return scale == 0f || !ValueAnimator.areAnimatorsEnabled()
}
