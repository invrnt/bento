package dev.bento.designsystem.component

import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.Text
import androidx.compose.material3.ripple
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme

/**
 * A list row: optional leading slot (KindIcon, avatar, icon), headline, supporting line, trailing slot. Merges its
 * semantics into one TalkBack node; [onLongClick] enters selection in lists. Height ≥ 56 dp (72 with supporting text).
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
public fun ListRow(
    headline: String,
    modifier: Modifier = Modifier,
    supporting: String? = null,
    leading: (@Composable () -> Unit)? = null,
    trailing: (@Composable () -> Unit)? = null,
    onClick: (() -> Unit)? = null,
    onLongClick: (() -> Unit)? = null,
    onClickLabel: String? = null,
    selected: Boolean = false,
    enabled: Boolean = true
) {
    val c = BentoTheme.colors
    val container by animateColorAsState(if (selected) c.accentSoft else Color.Transparent, BentoTheme.motion.color(), label = "row")
    val interaction = remember { MutableInteractionSource() }
    Row(
        modifier
            .fillMaxWidth()
            .heightIn(min = if (supporting != null) 72.dp else 56.dp)
            .alpha(if (enabled) 1f else DISABLED_ALPHA)
            .background(container)
            .then(
                if (onClick != null || onLongClick != null) {
                    Modifier.combinedClickable(
                        interactionSource = interaction,
                        indication = ripple(),
                        enabled = enabled,
                        onClickLabel = onClickLabel,
                        role = Role.Button,
                        onLongClick = onLongClick,
                        onClick = onClick ?: {}
                    )
                } else {
                    Modifier
                }
            )
            .semantics(mergeDescendants = true) { if (selected) this.selected = true }
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        if (leading != null) leading()
        Column(Modifier.weight(1f)) {
            Text(headline, color = c.ink, style = BentoTheme.typography.body, maxLines = 2, overflow = TextOverflow.Ellipsis)
            if (supporting != null) {
                Text(supporting, color = c.inkMuted, style = BentoTheme.typography.metadata, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
        }
        if (trailing != null) trailing()
    }
}

/** Section title marked as a heading, with an optional text action ("Ver todo"). */
@Composable
public fun SectionHeader(
    title: String,
    modifier: Modifier = Modifier,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null
) {
    val c = BentoTheme.colors
    Row(
        modifier.fillMaxWidth().heightIn(min = 48.dp).padding(start = 16.dp, end = if (actionLabel != null) 4.dp else 16.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            title,
            color = c.inkMuted,
            style = BentoTheme.typography.labelStrong,
            modifier = Modifier.weight(1f).semantics { heading() }
        )
        if (actionLabel != null && onAction != null) BentoTextAction(actionLabel, onAction)
    }
}

@Composable
private fun RowIcon(icon: ImageVector) {
    val c = BentoTheme.colors
    Box(Modifier.size(36.dp).clip(BentoShapes.md).background(c.subtle), contentAlignment = Alignment.Center) {
        BentoIcon(icon, contentDescription = null, tint = c.inkMuted)
    }
}

/** Settings entry: icon, title, summary, current value and a chevron when it navigates. */
@Composable
public fun SettingsRow(
    title: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    summary: String? = null,
    icon: ImageVector? = null,
    value: String? = null,
    showChevron: Boolean = true,
    enabled: Boolean = true
) {
    val c = BentoTheme.colors
    ListRow(
        headline = title,
        modifier = modifier,
        supporting = summary,
        leading = icon?.let { { RowIcon(it) } },
        trailing = {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                if (value != null) Text(value, color = c.inkMuted, style = BentoTheme.typography.label, maxLines = 1)
                if (showChevron) BentoIcon(BentoIcons.ChevronRight, contentDescription = null, tint = c.inkSubtle)
            }
        },
        onClick = onClick,
        enabled = enabled
    )
}

/** A row that is one switch: the whole row toggles (Role.Switch), so the target is the full row height. */
@Composable
public fun SwitchRow(
    title: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
    summary: String? = null,
    icon: ImageVector? = null,
    enabled: Boolean = true
) {
    val c = BentoTheme.colors
    val interaction = remember { MutableInteractionSource() }
    Row(
        modifier
            .fillMaxWidth()
            .heightIn(min = if (summary != null) 72.dp else 56.dp)
            .alpha(if (enabled) 1f else DISABLED_ALPHA)
            .toggleable(checked, interaction, ripple(), enabled, Role.Switch, onCheckedChange)
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        if (icon != null) RowIcon(icon)
        Column(Modifier.weight(1f)) {
            Text(title, color = c.ink, style = BentoTheme.typography.body)
            if (summary != null) Text(summary, color = c.inkMuted, style = BentoTheme.typography.metadata)
        }
        BentoSwitch(checked = checked, onCheckedChange = null, enabled = enabled)
    }
}
