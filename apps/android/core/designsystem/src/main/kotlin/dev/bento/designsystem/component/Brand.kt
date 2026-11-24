package dev.bento.designsystem.component

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.keyframes
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.graphics.ExperimentalAnimationGraphicsApi
import androidx.compose.animation.graphics.res.animatedVectorResource
import androidx.compose.animation.graphics.vector.AnimatedImageVector
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import dev.bento.designsystem.R
import dev.bento.designsystem.generated.BentoTokens
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.strings.R as StringsR

/** Geometry of the mark on its 32×32 grid (brand.md §3). */
private object Mark {
    const val GRID = 32f
    const val OUTER_RADIUS = 9f
    const val CELL_RADIUS = 3.5f
    val tall = Rect(4.5f, 5f, 10.5f, 22f)
    val top = Rect(17f, 5f, 10.5f, 10f)
    val bottom = Rect(17f, 17f, 10.5f, 10f)
    val ume = Offset(22.25f, 22f)
    const val UME_RADIUS = 2.75f

    data class Rect(val x: Float, val y: Float, val w: Float, val h: Float)
}

private fun DrawScope.cell(rect: Mark.Rect, color: Color, alpha: Float = 1f) {
    drawRoundRect(
        color = color,
        topLeft = Offset(rect.x, rect.y),
        size = Size(rect.w, rect.h),
        cornerRadius = CornerRadius(Mark.CELL_RADIUS),
        alpha = alpha,
    )
}

private fun Modifier.markSemantics(contentDescription: String?): Modifier =
    if (contentDescription == null) this else semantics {
        this.contentDescription = contentDescription
        role = Role.Image
    }

/**
 * The Bento mark: lacquer box, three compartments, one ume. Colors come from tokens, so it inverts in dark mode.
 * Decorative by default; pass [contentDescription] when it stands alone. Minimum size 16 dp.
 */
@Composable
public fun BrandMark(modifier: Modifier = Modifier, size: Dp = 28.dp, contentDescription: String? = null) {
    val colors = BentoTheme.colors
    Canvas(modifier.size(size.coerceAtLeast(16.dp)).markSemantics(contentDescription)) {
        scale(this.size.width / Mark.GRID, pivot = Offset.Zero) {
            drawRoundRect(colors.ink, size = Size(Mark.GRID, Mark.GRID), cornerRadius = CornerRadius(Mark.OUTER_RADIUS))
            cell(Mark.tall, colors.tray)
            cell(Mark.top, colors.tray)
            cell(Mark.bottom, colors.tray)
            drawCircle(colors.shu, radius = Mark.UME_RADIUS, center = Mark.ume)
        }
    }
}

/** Mark + "Bento" in Geist 600, tracking −0.03 em. Below 24 dp the mark is shown alone (brand.md §3). */
@Composable
public fun BrandLogo(modifier: Modifier = Modifier, markSize: Dp = 28.dp, label: String = stringResource(StringsR.string.ds_brand_name)) {
    if (markSize < 24.dp) {
        BrandMark(modifier, size = markSize, contentDescription = label)
        return
    }
    Row(
        modifier.semantics(mergeDescendants = true) {},
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        BrandMark(size = markSize)
        Text(
            label,
            color = BentoTheme.colors.ink,
            style = BentoTheme.typography.sectionTitle.copy(fontWeight = FontWeight.SemiBold, letterSpacing = (-0.03).em, fontSize = (markSize.value * 0.64f).sp),
        )
    }
}

/**
 * The only page-loading indicator: compartments fill one after another and the ume lands last.
 * Drawn from tokens (correct under an in-app theme override); [bentoLoaderAnimatedVector] is the same animation as
 * an AnimatedImageVector for the splash screen. With reduced motion it is a still, half-filled box.
 */
@Composable
public fun BentoLoader(
    modifier: Modifier = Modifier,
    size: Dp = 32.dp,
    contentDescription: String? = stringResource(StringsR.string.ds_loading),
) {
    val colors = BentoTheme.colors
    val reduced = BentoTheme.motion.reduced
    val alphas = if (reduced) {
        remember { List(4) { StaticAlpha } }
    } else {
        val transition = rememberInfiniteTransition(label = "bento-loader")
        List(4) { index ->
            transition.animateFloat(
                initialValue = LOW,
                targetValue = LOW,
                animationSpec = infiniteRepeatable(
                    animation = keyframes {
                        durationMillis = BentoTokens.Duration.bento
                        LOW at 0 using BentoTokens.Easing.easeInOut
                        1f at (BentoTokens.Duration.bento * 0.35f).toInt() using BentoTokens.Easing.easeInOut
                        LOW at BentoTokens.Duration.bento
                    },
                    repeatMode = RepeatMode.Restart,
                    initialStartOffset = androidx.compose.animation.core.StartOffset(STAGGER_MS * index),
                ),
                label = "cell-$index",
            )
        }
    }
    Canvas(
        modifier.size(size).semantics {
            if (contentDescription != null) {
                this.contentDescription = contentDescription
                progressBarRangeInfo = ProgressBarRangeInfo.Indeterminate
            }
        },
    ) {
        scale(this.size.width / Mark.GRID, pivot = Offset.Zero) {
            drawRoundRect(
                colors.lineStrong,
                topLeft = Offset(1f, 1f),
                size = Size(30f, 30f),
                cornerRadius = CornerRadius(8.5f),
                style = Stroke(width = 1.5f),
            )
            cell(Mark.tall, colors.inkSubtle, alphas[0].value)
            cell(Mark.top, colors.inkSubtle, alphas[1].value)
            cell(Mark.bottom, colors.inkSubtle, alphas[2].value)
            drawCircle(colors.shu, radius = Mark.UME_RADIUS, center = Mark.ume, alpha = alphas[3].value)
        }
    }
}

private const val LOW = 0.25f
private const val STAGGER_MS = 180
private val StaticAlpha: State<Float> = object : State<Float> {
    override val value: Float = 0.6f
}

/** The loader as an AnimatedImageVector (`R.drawable.avd_bento_loader`), also used as the splash icon animation. */
@OptIn(ExperimentalAnimationGraphicsApi::class)
@Composable
public fun bentoLoaderAnimatedVector(): AnimatedImageVector = AnimatedImageVector.animatedVectorResource(R.drawable.avd_bento_loader)
