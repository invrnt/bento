package dev.bento.designsystem.component

import android.icu.text.NumberFormat
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoColors
import dev.bento.designsystem.theme.BentoElevation
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.designsystem.theme.bentoShadow
import dev.bento.strings.R as StringsR
import java.util.Locale

/** Tones shared by Badge, StatusDot and progress (brand.md §11). `Shu` is reserved for the brand moments. */
public enum class BentoTone { Neutral, Accent, Success, Warning, Danger, Shu }

/** Callout tones: Badge tones plus `Info` (uses accent). */
public enum class CalloutTone { Neutral, Info, Success, Warning, Danger }

/** How a message is announced by TalkBack. Pass it explicitly (brand.md §11: "the role is passed explicitly"). */
public enum class BentoAnnounce { None, Polite, Assertive }

internal fun Modifier.announce(mode: BentoAnnounce): Modifier = when (mode) {
    BentoAnnounce.None -> this
    BentoAnnounce.Polite -> semantics { liveRegion = LiveRegionMode.Polite }
    BentoAnnounce.Assertive -> semantics { liveRegion = LiveRegionMode.Assertive }
}

internal data class ToneColors(val solid: Color, val soft: Color, val ink: Color)

internal fun BentoColors.tone(tone: BentoTone): ToneColors = when (tone) {
    BentoTone.Neutral -> ToneColors(inkSubtle, sunken, inkMuted)
    BentoTone.Accent -> ToneColors(accent, accentSoft, accentInk)
    BentoTone.Success -> ToneColors(success, successSoft, successInk)
    BentoTone.Warning -> ToneColors(warning, warningSoft, warningInk)
    BentoTone.Danger -> ToneColors(danger, dangerSoft, dangerInk)
    BentoTone.Shu -> ToneColors(shu, shuSoft, shuInk)
}

internal fun CalloutTone.asTone(): BentoTone = when (this) {
    CalloutTone.Neutral -> BentoTone.Neutral
    CalloutTone.Info -> BentoTone.Accent
    CalloutTone.Success -> BentoTone.Success
    CalloutTone.Warning -> BentoTone.Warning
    CalloutTone.Danger -> BentoTone.Danger
}

internal fun CalloutTone.icon(): ImageVector = when (this) {
    CalloutTone.Neutral, CalloutTone.Info -> BentoIcons.Info
    CalloutTone.Success -> BentoIcons.CircleCheck
    CalloutTone.Warning -> BentoIcons.TriangleAlert
    CalloutTone.Danger -> BentoIcons.CircleAlert
}

/** Locale-aware percent ("42 %" in Spanish) through android.icu. */
@Composable
public fun formatPercent(fraction: Float): String {
    val locale: Locale = LocalConfiguration.current.locales[0]
    return NumberFormat.getPercentInstance(locale).format(fraction.coerceIn(0f, 1f).toDouble())
}

/** Small status dot. Decorative: the adjacent text carries the meaning (color is never the only signal). */
@Composable
public fun StatusDot(modifier: Modifier = Modifier, tone: BentoTone = BentoTone.Neutral, pulse: Boolean = false, size: Dp = 8.dp) {
    val colors = BentoTheme.colors.tone(tone)
    val animate = pulse && !BentoTheme.motion.reduced
    val ring = if (animate) {
        val t = rememberInfiniteTransition(label = "dot")
        t.animateFloat(0f, 1f, infiniteRepeatable(tween(1400, easing = LinearEasing), RepeatMode.Restart), label = "dot-pulse").value
    } else {
        0f
    }
    Canvas(modifier.size(size).clearAndSetSemantics {}) {
        if (animate) {
            drawCircle(colors.solid, radius = this.size.minDimension / 2f * (1f + ring), alpha = 0.6f * (1f - ring))
        }
        drawCircle(colors.solid)
    }
}

public enum class BadgeSize { Small, Medium }

/** Pill label with tone; `dot` (optionally pulsing) for live processes, or an icon. */
@Composable
public fun Badge(
    text: String,
    modifier: Modifier = Modifier,
    tone: BentoTone = BentoTone.Neutral,
    dot: Boolean = false,
    pulse: Boolean = false,
    icon: ImageVector? = null,
    size: BadgeSize = BadgeSize.Small
) {
    val colors = BentoTheme.colors.tone(tone)
    Row(
        modifier
            .heightIn(min = if (size == BadgeSize.Small) 24.dp else 28.dp)
            .clip(BentoShapes.full)
            .background(colors.soft)
            .padding(horizontal = if (size == BadgeSize.Small) 8.dp else 10.dp, vertical = 2.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        when {
            dot -> StatusDot(tone = tone, pulse = pulse, size = 6.dp)
            icon != null -> BentoIcon(icon, contentDescription = null, tint = colors.ink, size = 14.dp)
        }
        Text(text, color = colors.ink, style = BentoTheme.typography.badge, maxLines = 1)
    }
}

/**
 * Linear progress. With [label] it is an accessible progress bar ("Subiendo 3 archivos, 42 %"); without it, decorative.
 * `progress = null` is indeterminate (a sliding segment; a gentle fade with reduced motion).
 */
@Composable
public fun ProgressBar(
    progress: Float?,
    modifier: Modifier = Modifier,
    label: String? = null,
    tone: BentoTone = BentoTone.Accent,
    height: Dp = 6.dp
) {
    val colors = BentoTheme.colors
    val fill = colors.tone(tone).solid
    val motion = BentoTheme.motion
    val animated by animateFloatAsState((progress ?: 0f).coerceIn(0f, 1f), motion.state(), label = "progress")
    val phase = if (progress == null) {
        val t = rememberInfiniteTransition(label = "progress-indeterminate")
        t.animateFloat(0f, 1f, infiniteRepeatable(tween(1400, easing = LinearEasing)), label = "phase").value
    } else {
        0f
    }
    val percent = progress?.let { formatPercent(it) }
    val semanticsModifier = if (label == null) {
        Modifier.clearAndSetSemantics {}
    } else {
        Modifier.semantics(mergeDescendants = true) {
            contentDescription = label
            progressBarRangeInfo =
                if (progress == null) ProgressBarRangeInfo.Indeterminate else ProgressBarRangeInfo(progress.coerceIn(0f, 1f), 0f..1f)
            if (percent != null) stateDescription = percent
        }
    }
    Canvas(
        modifier
            .fillMaxWidth()
            .height(height)
            .then(semanticsModifier)
    ) {
        val radius = CornerRadius(this.size.height / 2f)
        drawRoundRect(colors.sunken, cornerRadius = radius)
        if (progress != null) {
            drawRoundRect(fill, size = Size(this.size.width * animated, this.size.height), cornerRadius = radius)
        } else if (motion.reduced) {
            drawRoundRect(fill, cornerRadius = radius, alpha = 0.35f + 0.35f * kotlin.math.sin(phase * Math.PI.toFloat()))
        } else {
            val segment = this.size.width * 0.32f
            val x = (this.size.width + segment) * phase - segment
            drawRoundRect(
                fill,
                topLeft = Offset(x.coerceAtLeast(0f), 0f),
                size = Size((segment + x.coerceAtMost(0f)).coerceAtMost(this.size.width - x.coerceAtLeast(0f)), this.size.height),
                cornerRadius = radius
            )
        }
    }
}

/** Circular progress (avatar ring, upload card, button loading). Same semantics rules as [ProgressBar]. */
@Composable
public fun ProgressRing(
    progress: Float?,
    modifier: Modifier = Modifier,
    size: Dp = 24.dp,
    strokeWidth: Dp = 3.dp,
    color: Color = BentoTheme.colors.accent,
    trackColor: Color = Color.Transparent,
    label: String? = null
) {
    val motion = BentoTheme.motion
    val animated by animateFloatAsState((progress ?: 0f).coerceIn(0f, 1f), motion.state(), label = "ring")
    val rotation = if (progress == null && !motion.reduced) {
        val t = rememberInfiniteTransition(label = "ring-spin")
        t.animateFloat(0f, 360f, infiniteRepeatable(tween(1100, easing = LinearEasing)), label = "spin").value
    } else {
        0f
    }
    val percent = progress?.let { formatPercent(it) }
    Canvas(
        modifier.size(size).then(
            if (label == null) {
                Modifier.clearAndSetSemantics {}
            } else {
                Modifier.semantics {
                    contentDescription = label
                    progressBarRangeInfo =
                        if (progress ==
                            null
                        ) {
                            ProgressBarRangeInfo.Indeterminate
                        } else {
                            ProgressBarRangeInfo(progress.coerceIn(0f, 1f), 0f..1f)
                        }
                    if (percent != null) stateDescription = percent
                }
            }
        )
    ) {
        val stroke = strokeWidth.toPx()
        val inset = stroke / 2f
        val arcSize = Size(this.size.width - stroke, this.size.height - stroke)
        if (trackColor != Color.Transparent) {
            drawArc(trackColor, 0f, 360f, false, Offset(inset, inset), arcSize, style = Stroke(stroke))
        }
        val sweep = if (progress == null) 90f else 360f * animated
        val start = if (progress == null) rotation - 90f else -90f
        drawArc(color, start, sweep, false, Offset(inset, inset), arcSize, style = Stroke(stroke, cap = StrokeCap.Round))
    }
}

/**
 * Inline, non-blocking message (brand.md §11 `Callout`). Pass [announce] when it must be read out.
 * The action sits below the text on compact widths and at the end on wide ones.
 */
@Composable
public fun Callout(
    modifier: Modifier = Modifier,
    tone: CalloutTone = CalloutTone.Neutral,
    title: String? = null,
    body: String? = null,
    icon: ImageVector? = null,
    announce: BentoAnnounce = BentoAnnounce.None,
    action: (@Composable () -> Unit)? = null
) {
    val c = BentoTheme.colors
    val tc = c.tone(tone.asTone())
    val container = if (tone == CalloutTone.Neutral) c.subtle else tc.soft
    val border = when (tone) {
        CalloutTone.Neutral -> c.line
        CalloutTone.Info -> c.accent.copy(alpha = 0.2f)
        CalloutTone.Warning -> c.warning.copy(alpha = 0.35f)
        else -> tc.solid.copy(alpha = 0.25f)
    }
    BoxWithConstraints(
        modifier
            .fillMaxWidth()
            .clip(BentoShapes.lg)
            .background(container)
            .border(1.dp, border, BentoShapes.lg)
            .announce(announce)
            .padding(14.dp)
    ) {
        val wide = maxWidth >= 520.dp
        val text: @Composable () -> Unit = {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                BentoIcon(
                    icon ?: tone.icon(),
                    contentDescription = null,
                    tint = if (tone ==
                        CalloutTone.Neutral
                    ) {
                        c.inkMuted
                    } else {
                        tc.ink
                    },
                    size = BentoIconSize.Standard
                )
                Column(Modifier.semantics(mergeDescendants = true) {}, verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    if (title != null) Text(title, color = c.ink, style = BentoTheme.typography.bodyStrong)
                    if (body != null) Text(body, color = c.inkMuted, style = BentoTheme.typography.body)
                }
            }
        }
        if (wide && action != null) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                Box(Modifier.weight(1f)) { text() }
                action()
            }
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                text()
                if (action != null) Box(Modifier.padding(start = 32.dp)) { action() }
            }
        }
    }
}

/**
 * A calm card for one item that needs attention ("Hay una versión nueva", "El teléfono no tiene espacio"):
 * tone tile, title, one sentence, exactly one action, optional dismiss.
 */
@Composable
public fun AttentionCard(
    title: String,
    body: String,
    actionLabel: String,
    onAction: () -> Unit,
    modifier: Modifier = Modifier,
    tone: CalloutTone = CalloutTone.Info,
    icon: ImageVector? = null,
    onDismiss: (() -> Unit)? = null,
    dismissLabel: String = stringResource(StringsR.string.ds_dismiss)
) {
    val c = BentoTheme.colors
    val tc = c.tone(tone.asTone())
    Row(
        modifier
            .fillMaxWidth()
            .bentoShadow(BentoElevation.Xs, BentoShapes.lg)
            .clip(BentoShapes.lg)
            .background(c.raised)
            .border(1.dp, c.line, BentoShapes.lg)
            .padding(start = 16.dp, top = 16.dp, bottom = 16.dp, end = if (onDismiss != null) 4.dp else 16.dp),
        horizontalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        Box(Modifier.size(40.dp).clip(BentoShapes.md).background(tc.soft), contentAlignment = Alignment.Center) {
            BentoIcon(icon ?: tone.icon(), contentDescription = null, tint = tc.ink)
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Column(Modifier.semantics(mergeDescendants = true) {}) {
                Text(title, color = c.ink, style = BentoTheme.typography.bodyStrong)
                Text(body, color = c.inkMuted, style = BentoTheme.typography.body, modifier = Modifier.padding(top = 2.dp))
            }
            BentoButton(actionLabel, onAction, size = BentoButtonSize.Small, modifier = Modifier.padding(top = 8.dp))
        }
        if (onDismiss != null) {
            BentoIconButton(BentoIcons.X, dismissLabel, onDismiss, dense = true, modifier = Modifier.padding(top = 0.dp))
        }
    }
}

/** Empty compartment: dashed border, icon tile, title, one sentence, optional action (brand.md §11). */
@Composable
public fun EmptyState(
    title: String,
    body: String,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    compact: Boolean = false,
    action: (@Composable () -> Unit)? = null
) {
    val c = BentoTheme.colors
    Box(
        modifier
            .fillMaxWidth()
            .heightIn(min = if (compact) 176.dp else 288.dp)
            .drawBehind {
                drawRoundRect(
                    c.lineStrong.copy(alpha = 0.8f),
                    cornerRadius = CornerRadius(18.dp.toPx()),
                    style = Stroke(1.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(6.dp.toPx(), 4.dp.toPx())))
                )
            }
            .padding(horizontal = 24.dp, vertical = if (compact) 32.dp else 48.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(Modifier.widthIn(max = 384.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Box(
                Modifier
                    .size(48.dp)
                    .bentoShadow(BentoElevation.Sm, BentoShapes.lg)
                    .clip(BentoShapes.lg)
                    .background(c.raised)
                    .border(1.dp, c.line, BentoShapes.lg),
                contentAlignment = Alignment.Center
            ) {
                if (icon != null) BentoIcon(icon, contentDescription = null, tint = c.inkMuted) else EmptyCompartments(c.inkMuted)
            }
            Text(
                title,
                color = c.ink,
                style = BentoTheme.typography.sectionTitle,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 16.dp).semantics { heading() }
            )
            Text(
                body,
                color = c.inkMuted,
                style = BentoTheme.typography.body,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 6.dp)
            )
            if (action != null) Box(Modifier.padding(top = 20.dp)) { action() }
        }
    }
}

@Composable
private fun EmptyCompartments(color: Color) {
    Canvas(Modifier.size(20.dp)) {
        scale(this.size.width / 24f, pivot = Offset.Zero) {
            val stroke = Stroke(1.5f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(2.5f, 2.5f)))
            drawRoundRect(color, Offset(3f, 4f), Size(7f, 16f), CornerRadius(2.5f), style = stroke)
            drawRoundRect(color, Offset(12f, 4f), Size(9f, 7f), CornerRadius(2.5f), style = stroke)
            drawRoundRect(color, Offset(12f, 13f), Size(9f, 7f), CornerRadius(2.5f), style = stroke)
        }
    }
}

/** Loading a screen with nothing cached: `BentoLoader` + label, announced politely. */
@Composable
public fun LoadingState(modifier: Modifier = Modifier, label: String = stringResource(StringsR.string.ds_loading)) {
    Column(
        modifier
            .fillMaxWidth()
            .heightIn(min = 160.dp)
            .semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite }
            .padding(vertical = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterVertically)
    ) {
        BentoLoader(contentDescription = null)
        Text(label, color = BentoTheme.colors.inkMuted, style = BentoTheme.typography.label)
    }
}

/** Error as a `danger` message, announced assertively, with an explicit retry. */
@Composable
public fun ErrorState(
    body: String,
    modifier: Modifier = Modifier,
    title: String = stringResource(StringsR.string.common_error_title),
    onRetry: (() -> Unit)? = null,
    retryLabel: String = stringResource(StringsR.string.common_action_retry)
) {
    val c = BentoTheme.colors
    Column(
        modifier
            .fillMaxWidth()
            .clip(BentoShapes.lg)
            .background(c.dangerSoft)
            .border(1.dp, c.danger.copy(alpha = 0.25f), BentoShapes.lg)
            .announce(BentoAnnounce.Assertive)
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            BentoIcon(BentoIcons.TriangleAlert, contentDescription = null, tint = c.dangerInk)
            Column(Modifier.semantics(mergeDescendants = true) {}) {
                Text(title, color = c.ink, style = BentoTheme.typography.bodyStrong, modifier = Modifier.semantics { heading() })
                Text(body, color = c.inkMuted, style = BentoTheme.typography.body, modifier = Modifier.padding(top = 2.dp))
            }
        }
        if (onRetry != null) {
            BentoButton(
                retryLabel,
                onRetry,
                size = BentoButtonSize.Small,
                leadingIcon = BentoIcons.RotateCw,
                modifier = Modifier.padding(start = 32.dp)
            )
        }
    }
}
