package dev.bento.designsystem.component

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.Text
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.material3.ripple
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import dev.bento.designsystem.theme.BentoColors
import dev.bento.designsystem.theme.BentoElevation
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.designsystem.theme.bentoShadow
import dev.bento.strings.R as StringsR

/** One `Primary` per zone. Destructive actions use `Danger` and a sheet or dialog that states the consequence. */
public enum class BentoButtonVariant { Primary, Secondary, Ghost, Danger, DangerGhost }

/** Visual heights; every size keeps a 48 dp touch target. */
public enum class BentoButtonSize(internal val height: Dp, internal val padding: Dp, internal val icon: Dp) {
    Small(40.dp, 14.dp, 18.dp),
    Medium(48.dp, 18.dp, 20.dp),
    Large(56.dp, 24.dp, 20.dp),
}

internal data class ButtonColors(val container: Color, val content: Color, val border: Color?)

/**
 * Pressed fills use the `-hover` tokens only in light mode, where they darken. In dark mode they lighten and white text
 * would drop below 4.5:1 (accent-hover 4.1:1, danger-hover 3.8:1), so the ripple alone marks the press.
 */
internal fun buttonColors(variant: BentoButtonVariant, c: BentoColors, pressed: Boolean, dark: Boolean): ButtonColors = when (variant) {
    BentoButtonVariant.Primary -> ButtonColors(if (pressed && !dark) c.accentHover else c.accent, c.onAccent, null)
    BentoButtonVariant.Secondary -> ButtonColors(if (pressed) c.subtle else c.raised, c.ink, if (pressed) c.lineStrong else c.line)
    BentoButtonVariant.Ghost -> ButtonColors(Color.Transparent, if (pressed) c.ink else c.inkMuted, null)
    BentoButtonVariant.Danger -> ButtonColors(if (pressed && !dark) c.dangerHover else c.danger, c.onDanger, null)
    BentoButtonVariant.DangerGhost -> ButtonColors(if (pressed) c.dangerSoft else Color.Transparent, c.dangerInk, null)
}

/**
 * Bento button. Labels are verbs ("Subir archivos"), never "OK". While [loading] the button is busy: it keeps its
 * label, shows a ring instead of the leading icon, ignores taps and announces [loadingLabel].
 */
@Composable
public fun BentoButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    variant: BentoButtonVariant = BentoButtonVariant.Secondary,
    size: BentoButtonSize = BentoButtonSize.Medium,
    leadingIcon: ImageVector? = null,
    trailingIcon: ImageVector? = null,
    enabled: Boolean = true,
    loading: Boolean = false,
    loadingLabel: String = stringResource(StringsR.string.ds_loading),
) {
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val motion = BentoTheme.motion
    val target = buttonColors(variant, BentoTheme.colors, pressed, BentoTheme.isDark)
    val container by animateColorAsState(target.container, motion.color(), label = "button-container")
    val content by animateColorAsState(target.content, motion.color(), label = "button-content")
    val pressScale by animateFloatAsState(if (pressed && !motion.reduced) 0.98f else 1f, motion.color(), label = "button-press")
    val shape = if (size == BentoButtonSize.Small) BentoShapes.md else BentoShapes.control
    val active = enabled && !loading
    val elevation = when (variant) {
        BentoButtonVariant.Secondary -> BentoElevation.Xs
        BentoButtonVariant.Primary, BentoButtonVariant.Danger -> BentoElevation.Sm
        else -> BentoElevation.None
    }

    Box(
        modifier
            .minimumInteractiveComponentSize()
            .semantics { if (loading) stateDescription = loadingLabel }
            .graphicsLayer { scaleX = pressScale; scaleY = pressScale }
            .alpha(if (enabled) 1f else DISABLED_ALPHA)
            .then(if (enabled && elevation != BentoElevation.None) Modifier.bentoShadow(elevation, shape) else Modifier)
            .clip(shape)
            .background(container)
            .then(target.border?.let { Modifier.border(BorderStroke(1.dp, it), shape) } ?: Modifier)
            .clickable(
                interactionSource = interaction,
                indication = ripple(),
                enabled = active,
                role = Role.Button,
                onClick = onClick,
            )
            .bentoFocusRing(interaction, shape)
            .heightIn(min = size.height)
            .defaultMinSize(minWidth = size.height)
            .padding(PaddingValues(horizontal = size.padding)),
        contentAlignment = Alignment.Center,
    ) {
        CompositionLocalProvider(LocalContentColor provides content) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                when {
                    loading -> ProgressRing(progress = null, size = size.icon, strokeWidth = 2.dp, color = content, label = null)
                    leadingIcon != null -> BentoIcon(leadingIcon, contentDescription = null, size = size.icon)
                }
                Text(
                    text,
                    style = if (size == BentoButtonSize.Large) BentoTheme.typography.bodyStrong else BentoTheme.typography.label,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(vertical = 4.dp),
                )
                if (trailingIcon != null) BentoIcon(trailingIcon, contentDescription = null, size = size.icon)
            }
        }
    }
}

public enum class BentoIconButtonVariant { Ghost, Secondary, Accent, Overlay }

/**
 * Icon-only control: always has [contentDescription] and a long-press/hover tooltip with the same text.
 * [dense] draws a 40 dp visual inside the 48 dp touch target.
 */
@Composable
public fun BentoIconButton(
    icon: ImageVector,
    contentDescription: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    variant: BentoIconButtonVariant = BentoIconButtonVariant.Ghost,
    dense: Boolean = false,
    enabled: Boolean = true,
    selected: Boolean = false,
    tint: Color = Color.Unspecified,
) {
    val c = BentoTheme.colors
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val (container, content) = when (variant) {
        BentoIconButtonVariant.Ghost -> (if (selected) c.accentSoft else if (pressed) c.pressed else Color.Transparent) to
            (if (selected) c.accentInk else if (pressed) c.ink else c.inkMuted)
        BentoIconButtonVariant.Secondary -> (if (pressed) c.subtle else c.raised) to c.ink
        BentoIconButtonVariant.Accent -> (if (pressed) c.accentSoftHover else c.accentSoft) to c.accentInk
        BentoIconButtonVariant.Overlay -> c.black.copy(alpha = if (pressed) 0.55f else 0.4f) to c.white
    }
    val animatedContainer by animateColorAsState(container, BentoTheme.motion.color(), label = "icon-button")
    val visual = if (dense) 40.dp else 48.dp
    BentoTooltip(contentDescription, modifier) {
        Box(
            Modifier
                .minimumInteractiveComponentSize()
                .size(visual)
                .alpha(if (enabled) 1f else DISABLED_ALPHA)
                .clip(BentoShapes.full)
                .background(animatedContainer)
                .then(if (variant == BentoIconButtonVariant.Secondary) Modifier.border(1.dp, c.line, BentoShapes.full) else Modifier)
                .clickable(interaction, ripple(), enabled = enabled, role = Role.Button, onClickLabel = null, onClick = onClick)
                .semantics { if (selected) this.selected = true }
                .bentoFocusRing(interaction, BentoShapes.full),
            contentAlignment = Alignment.Center,
        ) {
            BentoIcon(
                icon,
                contentDescription = contentDescription,
                tint = if (tint != Color.Unspecified) tint else content,
                size = if (dense) BentoIconSize.Standard else BentoIconSize.Large,
            )
        }
    }
}

/** The extended floating action button (`+ Nuevo` in Archivos). Collapses to the icon when [expanded] is false. */
@Composable
public fun BentoFab(
    text: String,
    icon: ImageVector,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    expanded: Boolean = true,
) {
    val c = BentoTheme.colors
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val container by animateColorAsState(if (pressed && !BentoTheme.isDark) c.accentHover else c.accent, BentoTheme.motion.color(), label = "fab")
    Box(
        modifier
            .bentoShadow(BentoElevation.Lg, BentoShapes.lg)
            .clip(BentoShapes.lg)
            .background(container)
            .clickable(interaction, ripple(color = c.onAccent), role = Role.Button, onClick = onClick)
            .semantics { if (!expanded) contentDescription = text }
            .bentoFocusRing(interaction, BentoShapes.lg)
            .heightIn(min = 56.dp)
            .defaultMinSize(minWidth = 56.dp)
            .padding(horizontal = if (expanded) 20.dp else 16.dp),
        contentAlignment = Alignment.Center,
    ) {
        CompositionLocalProvider(LocalContentColor provides c.onAccent) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                BentoIcon(icon, contentDescription = null, size = BentoIconSize.Large)
                if (expanded) Text(text, style = BentoTheme.typography.bodyStrong, maxLines = 1)
            }
        }
    }
}

internal const val DISABLED_ALPHA = 0.45f
