package dev.bento.designsystem.component

import androidx.compose.animation.AnimatedVisibilityScope
import androidx.compose.animation.BoundsTransform
import androidx.compose.animation.ExperimentalSharedTransitionApi
import androidx.compose.animation.SharedTransitionScope
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.runtime.Composable
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Rect
import dev.bento.designsystem.theme.BentoTheme

/**
 * The app's [SharedTransitionScope] (provided once by the shell around its navigation display). Media tiles and the
 * viewer use it for the tile → viewer transform (design-system/android.md §6). Null in previews and isolated tests,
 * where shared elements are simply not applied.
 */
public val LocalBentoSharedTransitionScope: androidx.compose.runtime.ProvidableCompositionLocal<SharedTransitionScope?> =
    compositionLocalOf { null }

/** Stable shared-element key for one media item, identical on the tile and in the viewer. */
public fun bentoMediaKey(id: String): String = "bento-media:$id"

/**
 * Shares this element's bounds between screens under [key] when the shell provides a shared-transition scope and the
 * caller has an [animatedScope] (the navigation entry's). Follows the finger with the sheet spring; under reduced motion
 * the bounds jump and the screens only crossfade.
 */
@OptIn(ExperimentalSharedTransitionApi::class)
@Composable
public fun Modifier.bentoSharedMedia(key: String, animatedScope: AnimatedVisibilityScope?, visible: Boolean = true): Modifier {
    val shared = LocalBentoSharedTransitionScope.current ?: return this
    if (animatedScope == null || !visible) return this
    val reduced = BentoTheme.motion.reduced
    val transform = BoundsTransform { _: Rect, _: Rect ->
        if (reduced) tween(0) else spring(dampingRatio = 0.9f, stiffness = 600f, visibilityThreshold = Rect.VisibilityThreshold)
    }
    return with(shared) {
        this@bentoSharedMedia.sharedElement(
            sharedContentState = rememberSharedContentState(key),
            animatedVisibilityScope = animatedScope,
            boundsTransform = transform
        )
    }
}

private val Rect.Companion.VisibilityThreshold: Rect get() = Rect(0.5f, 0.5f, 0.5f, 0.5f)
