package dev.bento.designsystem.component

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.material3.Text
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.material3.ripple
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.platform.LocalDensity
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.strings.R as StringsR

/**
 * Top bar: search pill (opens full-screen search) + avatar slot. Top bars hold search and status only
 * (product/android.md §1.3). Applies status-bar insets by default.
 */
@Composable
public fun BentoTopBar(
    searchLabel: String,
    onSearchClick: () -> Unit,
    modifier: Modifier = Modifier,
    windowInsets: WindowInsets = WindowInsets.statusBars,
    avatar: @Composable () -> Unit = {},
) {
    val c = BentoTheme.colors
    val interaction = remember { MutableInteractionSource() }
    Row(
        modifier
            .fillMaxWidth()
            .windowInsetsPadding(windowInsets)
            .padding(start = 16.dp, end = 8.dp, top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(
            Modifier
                .weight(1f)
                .heightIn(min = 48.dp)
                .clip(BentoShapes.full)
                .background(c.raised)
                .border(1.dp, c.line, BentoShapes.full)
                .clickable(interaction, ripple(), role = Role.Button, onClick = onSearchClick)
                .bentoFocusRing(interaction, BentoShapes.full)
                .semantics(mergeDescendants = true) {}
                .padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            BentoIcon(BentoIcons.Search, contentDescription = null, tint = c.inkSubtle)
            Text(searchLabel, color = c.inkMuted, style = BentoTheme.typography.body, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        avatar()
    }
}

/** Global status shown as the avatar ring (product/android.md §7). */
public enum class AvatarStatus { Idle, Syncing, Attention, Offline, Paused }

/**
 * Account avatar with the global status ring: none = all synced; accent arc = syncing (determinate with [progress]);
 * warning dot = attention; dimmed + CloudOff = offline; pause glyph = backup paused. TalkBack reads name and status.
 */
@Composable
public fun StatusAvatar(
    name: String,
    status: AvatarStatus,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    progress: Float? = null,
    image: Painter? = null,
    size: Dp = 36.dp,
) {
    val c = BentoTheme.colors
    val motion = BentoTheme.motion
    val statusText = when (status) {
        AvatarStatus.Idle -> stringResource(StringsR.string.ds_avatar_idle)
        AvatarStatus.Syncing -> progress?.let { stringResource(StringsR.string.ds_avatar_syncing_progress, formatPercent(it)) }
            ?: stringResource(StringsR.string.ds_avatar_syncing)
        AvatarStatus.Attention -> stringResource(StringsR.string.ds_avatar_attention)
        AvatarStatus.Offline -> stringResource(StringsR.string.ds_avatar_offline)
        AvatarStatus.Paused -> stringResource(StringsR.string.ds_avatar_paused)
    }
    val description = stringResource(StringsR.string.ds_avatar_label, name, statusText)
    val spin = if (status == AvatarStatus.Syncing && progress == null && !motion.reduced) {
        val t = rememberInfiniteTransition(label = "avatar-ring")
        t.animateFloat(0f, 360f, infiniteRepeatable(tween(1400, easing = LinearEasing)), label = "avatar-spin").value
    } else {
        0f
    }
    val ringSize = size + 10.dp
    Box(
        modifier
            .minimumInteractiveComponentSize()
            .size(maxOf(48.dp, ringSize))
            .clip(BentoShapes.full)
            .clickable(role = Role.Button, onClick = onClick)
            .clearAndSetSemantics {
                contentDescription = description
                role = Role.Button
                onClick { onClick(); true }
            },
        contentAlignment = Alignment.Center,
    ) {
        if (status == AvatarStatus.Syncing) {
            Canvas(Modifier.size(ringSize)) {
                val stroke = 2.5.dp.toPx()
                val inset = stroke / 2f
                val arc = Size(this.size.width - stroke, this.size.height - stroke)
                drawArc(c.accentSoft, 0f, 360f, false, Offset(inset, inset), arc, style = Stroke(stroke))
                val sweep = progress?.let { 360f * it.coerceIn(0f, 1f) } ?: 110f
                drawArc(c.accent, (if (progress == null) spin else 0f) - 90f, sweep, false, Offset(inset, inset), arc, style = Stroke(stroke, cap = StrokeCap.Round))
            }
        }
        Box(
            Modifier
                .size(size)
                .alpha(if (status == AvatarStatus.Offline) 0.5f else 1f)
                .clip(BentoShapes.full)
                .background(c.accentSoft),
            contentAlignment = Alignment.Center,
        ) {
            if (image != null) {
                Image(image, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            } else {
                // Initials are decorative (TalkBack reads the name), so they scale with the circle, not the font scale.
                val fontScale = LocalDensity.current.fontScale
                Text(
                    initials(name),
                    color = c.accentInk,
                    style = BentoTheme.typography.labelStrong.copy(fontSize = (size.value * 0.38f / fontScale).sp, lineHeight = (size.value * 0.5f / fontScale).sp),
                )
            }
        }
        val badge: (@Composable () -> Unit)? = when (status) {
            AvatarStatus.Attention -> { { Box(Modifier.size(10.dp).clip(BentoShapes.full).background(c.warning)) } }
            AvatarStatus.Offline -> { { BentoIcon(BentoIcons.CloudOff, contentDescription = null, tint = c.inkMuted, size = 12.dp) } }
            AvatarStatus.Paused -> { { BentoIcon(BentoIcons.Pause, contentDescription = null, tint = c.inkMuted, size = 10.dp) } }
            else -> null
        }
        if (badge != null) {
            Box(
                Modifier
                    .align(Alignment.Center)
                    .padding(start = size * 0.72f, top = size * 0.72f)
                    .size(if (status == AvatarStatus.Attention) 14.dp else 18.dp)
                    .clip(BentoShapes.full)
                    .background(c.raised)
                    .border(1.dp, if (status == AvatarStatus.Attention) c.raised else c.line, BentoShapes.full),
                contentAlignment = Alignment.Center,
            ) { badge() }
        }
    }
}

internal fun initials(name: String): String =
    name.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }.take(2).joinToString("") { it.first().uppercase() }.ifEmpty { "·" }

/** A top-level destination. [icon] should come from `BentoNavIcons` (stroke 1.75). */
@Immutable
public data class BentoNavItem(val key: String, val label: String, val icon: ImageVector, val badge: String? = null)

public enum class NavigationLayout { Bar, Rail }

/**
 * Navigation bar on compact widths, rail on medium/expanded (≥ 600 dp), chosen from the available width unless
 * [layout] forces one. Destinations swap instantly (no shared axis); reselecting calls [onReselect].
 */
@Composable
public fun BentoNavigationSuite(
    items: List<BentoNavItem>,
    selectedKey: String,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
    onReselect: (String) -> Unit = {},
    layout: NavigationLayout? = null,
    railHeader: (@Composable () -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    val c = BentoTheme.colors
    BoxWithConstraints(modifier.fillMaxSize().background(c.tray)) {
        val resolved = layout ?: if (maxWidth >= 600.dp) NavigationLayout.Rail else NavigationLayout.Bar
        val choose: (String) -> Unit = { key -> if (key == selectedKey) onReselect(key) else onSelect(key) }
        when (resolved) {
            NavigationLayout.Bar -> Column(Modifier.fillMaxSize()) {
                Box(Modifier.weight(1f).fillMaxWidth()) { content() }
                BentoNavigationBar(items, selectedKey, choose)
            }
            NavigationLayout.Rail -> Row(Modifier.fillMaxSize()) {
                BentoNavigationRail(items, selectedKey, choose, railHeader)
                Box(Modifier.weight(1f).fillMaxHeight()) { content() }
            }
        }
    }
}

@Composable
internal fun BentoNavigationBar(items: List<BentoNavItem>, selectedKey: String, onChoose: (String) -> Unit) {
    val c = BentoTheme.colors
    Column(Modifier.fillMaxWidth().background(c.tray).testTag(BentoTestTags.NavigationBar)) {
        Spacer(Modifier.fillMaxWidth().height(1.dp).background(c.line))
        Row(
            Modifier
                .fillMaxWidth()
                .windowInsetsPadding(WindowInsets.navigationBars)
                .heightIn(min = 72.dp)
                .selectableGroup(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            items.forEach { item ->
                NavDestination(item, item.key == selectedKey, { onChoose(item.key) }, Modifier.weight(1f))
            }
        }
    }
}

@Composable
internal fun BentoNavigationRail(items: List<BentoNavItem>, selectedKey: String, onChoose: (String) -> Unit, header: (@Composable () -> Unit)?) {
    Column(
        Modifier
            .fillMaxHeight()
            .width(96.dp)
            .testTag(BentoTestTags.NavigationRail)
            .windowInsetsPadding(WindowInsets.statusBars)
            .padding(vertical = 16.dp)
            .selectableGroup(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (header != null) {
            header()
            Spacer(Modifier.height(16.dp))
        }
        items.forEach { item -> NavDestination(item, item.key == selectedKey, { onChoose(item.key) }, Modifier) }
    }
}

@Composable
private fun NavDestination(item: BentoNavItem, selected: Boolean, onClick: () -> Unit, modifier: Modifier) {
    val c = BentoTheme.colors
    val motion = BentoTheme.motion
    val indicator by animateColorAsState(if (selected) c.accentSoft else c.accentSoft.copy(alpha = 0f), motion.color(), label = "nav-indicator")
    val iconTint by animateColorAsState(if (selected) c.accentInk else c.inkSubtle, motion.color(), label = "nav-icon")
    Column(
        modifier
            .heightIn(min = 64.dp)
            .selectable(
                selected = selected,
                onClick = onClick,
                role = Role.Tab,
                interactionSource = remember { MutableInteractionSource() },
                indication = ripple(bounded = false, radius = 36.dp),
            )
            .padding(vertical = 6.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Box(
            Modifier
                .size(width = 64.dp, height = 32.dp)
                .clip(BentoShapes.full)
                .background(indicator),
            contentAlignment = Alignment.Center,
        ) {
            BentoIcon(item.icon, contentDescription = null, tint = iconTint, size = BentoIconSize.Large)
            if (item.badge != null) {
                Box(Modifier.align(Alignment.TopEnd).padding(end = 12.dp)) { Badge(item.badge, tone = BentoTone.Accent) }
            }
        }
        Text(
            item.label,
            color = if (selected) c.ink else c.inkMuted,
            style = if (selected) BentoTheme.typography.metadata.copy(fontWeight = FontWeight.SemiBold) else BentoTheme.typography.metadata.copy(fontWeight = FontWeight.Medium),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}
