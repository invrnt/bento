package dev.bento.designsystem.component

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.text.BasicText
import androidx.compose.foundation.text.TextAutoSize
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.material3.ripple
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.generated.BentoTokens
import dev.bento.designsystem.theme.BentoElevation
import dev.bento.designsystem.theme.BentoHaptic
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.designsystem.theme.bentoHaptics
import dev.bento.designsystem.theme.bentoShadow

/** One option of [SegmentedButtons]. With `iconOnly`, [label] becomes the content description and tooltip. */
@Immutable
public data class SegmentOption<T>(val value: T, val label: String, val icon: ImageVector? = null)

/**
 * Radio group of 2–4 options on a sunken track; the selected segment is `raised` with `shadow-sm` and slides
 * (180 ms, instant with reduced motion). [tickHaptic] plays `SEGMENT_TICK` on change (grid density steps).
 */
@Composable
public fun <T> SegmentedButtons(
    options: List<SegmentOption<T>>,
    selected: T,
    onSelect: (T) -> Unit,
    modifier: Modifier = Modifier,
    iconOnly: Boolean = false,
    tickHaptic: Boolean = false
) {
    require(options.size in 2..5) { "SegmentedButtons needs 2–5 options" }
    val c = BentoTheme.colors
    val motion = BentoTheme.motion
    val haptics = bentoHaptics()
    val index = options.indexOfFirst { it.value == selected }.coerceAtLeast(0)
    BoxWithConstraints(
        modifier
            .heightIn(min = 48.dp)
            .clip(BentoShapes.control)
            .background(c.sunken)
            .padding(4.dp)
    ) {
        val segment = maxWidth / options.size
        val offset by animateDpAsState(
            segment * index,
            if (motion.reduced) androidx.compose.animation.core.snap() else motion.state(),
            label = "segment"
        )
        val shadow = BentoTheme.shadows.sm.first().color
        // The indicator is drawn behind the row so it always matches its height (labels may wrap at 200 %).
        Row(
            Modifier
                .selectableGroup()
                .drawBehind {
                    val radius = CornerRadius(BentoTokens.Radius.md.toPx())
                    val x = offset.toPx()
                    val w = segment.toPx()
                    drawRoundRect(shadow, Offset(x, 1.dp.toPx()), Size(w, size.height), radius)
                    drawRoundRect(c.raised, Offset(x, 0f), Size(w, size.height), radius)
                }
        ) {
            options.forEachIndexed { i, option ->
                val isSelected = i == index
                val content by animateColorAsState(if (isSelected) c.ink else c.inkMuted, motion.color(), label = "segment-content")
                val segmentModifier = Modifier
                    .width(segment)
                    .heightIn(min = 40.dp)
                    .clip(BentoShapes.md)
                    .selectable(
                        selected = isSelected,
                        onClick = {
                            if (!isSelected) {
                                if (tickHaptic) haptics.perform(BentoHaptic.SegmentTick)
                                onSelect(option.value)
                            }
                        },
                        role = Role.RadioButton,
                        interactionSource = remember { MutableInteractionSource() },
                        indication = ripple()
                    )
                    .then(if (iconOnly) Modifier.semantics { contentDescription = option.label } else Modifier)
                val body: @Composable () -> Unit = {
                    Row(
                        Modifier.padding(horizontal = 8.dp),
                        horizontalArrangement = Arrangement.spacedBy(6.dp, Alignment.CenterHorizontally),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        if (option.icon != null) {
                            BentoIcon(option.icon, contentDescription = null, tint = if (isSelected) c.accentInk else content)
                        }
                        if (!iconOnly) {
                            // One line that shrinks (down to 12 sp) rather than breaking a word at large font scales.
                            BasicText(
                                option.label,
                                style = BentoTheme.typography.label.copy(color = content, textAlign = TextAlign.Center),
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                autoSize = TextAutoSize.StepBased(minFontSize = 12.sp, maxFontSize = BentoTheme.typography.label.fontSize)
                            )
                        }
                    }
                }
                if (iconOnly) {
                    BentoTooltip(option.label) { Box(segmentModifier, contentAlignment = Alignment.Center) { body() } }
                } else {
                    Box(segmentModifier, contentAlignment = Alignment.Center) { body() }
                }
            }
        }
    }
}

@Composable
private fun ChipFrame(
    label: String,
    selected: Boolean,
    leadingIcon: ImageVector?,
    trailingIcon: ImageVector?,
    enabled: Boolean,
    modifier: Modifier,
    interaction: Modifier
) {
    val c = BentoTheme.colors
    val motion = BentoTheme.motion
    val container by animateColorAsState(if (selected) c.accentSoft else c.raised, motion.color(), label = "chip")
    val border by animateColorAsState(if (selected) c.accent.copy(alpha = 0.35f) else c.line, motion.color(), label = "chip-border")
    val content = if (selected) c.accentInk else c.ink
    Box(
        modifier
            .minimumInteractiveComponentSize()
            .alpha(if (enabled) 1f else DISABLED_ALPHA)
            .clip(BentoShapes.full)
            .background(container)
            .border(1.dp, border, BentoShapes.full)
            .then(interaction)
            .heightIn(min = 36.dp)
            .padding(horizontal = 14.dp),
        contentAlignment = Alignment.Center
    ) {
        CompositionLocalProvider(LocalContentColor provides content) {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                val lead = if (selected) BentoIcons.Check else leadingIcon
                if (lead != null) BentoIcon(lead, contentDescription = null, size = BentoIconSize.Dense)
                Text(label, style = BentoTheme.typography.label, maxLines = 1)
                if (trailingIcon != null) BentoIcon(trailingIcon, contentDescription = null, size = BentoIconSize.Dense)
            }
        }
    }
}

/** Action chip (e.g. a suggestion or a filter menu trigger). */
@Composable
public fun BentoChip(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    leadingIcon: ImageVector? = null,
    trailingIcon: ImageVector? = null,
    enabled: Boolean = true
) {
    val interaction = remember { MutableInteractionSource() }
    ChipFrame(
        label,
        selected = false,
        leadingIcon,
        trailingIcon,
        enabled,
        modifier,
        Modifier
            .clickable(interaction, ripple(), enabled = enabled, role = Role.Button, onClick = onClick)
            .bentoFocusRing(interaction, BentoShapes.full)
    )
}

/** Filter chip: a checkbox in chip form; selected shows a check, `accent-soft` and `accent-ink`. */
@Composable
public fun BentoFilterChip(
    label: String,
    selected: Boolean,
    onSelectedChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
    leadingIcon: ImageVector? = null,
    enabled: Boolean = true
) {
    val interaction = remember { MutableInteractionSource() }
    ChipFrame(
        label,
        selected,
        leadingIcon,
        trailingIcon = null,
        enabled,
        modifier,
        Modifier
            .toggleable(selected, interaction, ripple(), enabled, Role.Checkbox, onSelectedChange)
            .bentoFocusRing(interaction, BentoShapes.full)
    )
}

/** Bento-colored switch: `accent` track when on, `line-strong` outline when off. Use inside [SwitchRow]. */
@Composable
public fun BentoSwitch(checked: Boolean, onCheckedChange: ((Boolean) -> Unit)?, modifier: Modifier = Modifier, enabled: Boolean = true) {
    val c = BentoTheme.colors
    Switch(
        checked = checked,
        onCheckedChange = onCheckedChange,
        modifier = modifier,
        enabled = enabled,
        colors = SwitchDefaults.colors(
            checkedThumbColor = c.onAccent,
            checkedTrackColor = c.accent,
            checkedBorderColor = Color.Transparent,
            checkedIconColor = c.accent,
            uncheckedThumbColor = c.inkSubtle,
            uncheckedTrackColor = c.sunken,
            uncheckedBorderColor = c.lineStrong,
            uncheckedIconColor = c.sunken,
            disabledCheckedThumbColor = c.raised,
            disabledCheckedTrackColor = c.accent.copy(alpha = DISABLED_ALPHA),
            disabledCheckedBorderColor = Color.Transparent,
            disabledUncheckedThumbColor = c.inkSubtle.copy(alpha = DISABLED_ALPHA),
            disabledUncheckedTrackColor = c.sunken,
            disabledUncheckedBorderColor = c.line
        )
    )
}
