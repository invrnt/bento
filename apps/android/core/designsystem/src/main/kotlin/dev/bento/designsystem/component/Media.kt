package dev.bento.designsystem.component

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.snap
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Text
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.material3.ripple
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.generated.BentoTokens
import dev.bento.designsystem.theme.BentoElevation
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.designsystem.theme.bentoShadow
import dev.bento.strings.R as StringsR

/** Test tags exposed for feature tests. */
public object BentoTestTags {
    public const val ThumbnailImage: String = "bento:thumbnail-image"
    public const val ThumbnailPlaceholder: String = "bento:thumbnail-placeholder"
    public const val FloatingActionBar: String = "bento:floating-action-bar"
}

/**
 * Square, borderless media tile (brand.md §12). `painter == null` shows the `sunken` placeholder; when the image
 * arrives it fades in (180 ms; 120 ms with reduced motion). An image already present on first composition (cache)
 * appears without a fade. [selected] insets the image 8 dp with a 12 dp radius: it settles into its compartment,
 * drawn with a transform so the grid item never changes size. Interaction and TalkBack actions belong to the grid.
 */
@Composable
public fun Thumbnail(
    painter: Painter?,
    contentDescription: String?,
    modifier: Modifier = Modifier,
    selected: Boolean = false,
    selectionMode: Boolean = false,
    aspectRatio: Float = 1f,
    placeholder: @Composable BoxScope.() -> Unit = {},
    overlays: @Composable BoxScope.() -> Unit = {},
) {
    val c = BentoTheme.colors
    val motion = BentoTheme.motion
    val alpha = remember { Animatable(if (painter != null) 1f else 0f) }
    val hasImage = painter != null
    LaunchedEffect(hasImage) {
        if (hasImage) {
            alpha.animateTo(1f, tween(if (motion.reduced) BentoTokens.Duration.fast else BentoTokens.Duration.base, easing = BentoTokens.Easing.easeOut))
        } else {
            alpha.snapTo(0f)
        }
    }
    val inset by animateFloatAsState(if (selected) 1f else 0f, if (motion.reduced) snap() else motion.state(), label = "thumb-select")
    val insetPx = 8.dp
    val radius = 12.dp

    Box(
        modifier
            .aspectRatio(aspectRatio)
            .background(if (selected) c.accentSoft else c.sunken)
            .semantics { if (contentDescription != null) this.contentDescription = contentDescription },
    ) {
        Box(
            Modifier
                .fillMaxSize()
                .graphicsLayer {
                    val px = insetPx.toPx() * 2f * inset
                    val scale = if (size.width > 0f) (size.width - px) / size.width else 1f
                    scaleX = scale
                    scaleY = if (size.height > 0f) (size.height - px) / size.height else 1f
                    shape = RoundedCornerShape(radius * inset)
                    clip = inset > 0f
                }
                .background(c.sunken),
        ) {
            if (painter == null || alpha.value < 1f) {
                Box(Modifier.fillMaxSize().testTag(BentoTestTags.ThumbnailPlaceholder), contentAlignment = Alignment.Center, content = placeholder)
            }
            if (painter != null) {
                Image(
                    painter = painter,
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier
                        .fillMaxSize()
                        .testTag(BentoTestTags.ThumbnailImage)
                        .graphicsLayer { this.alpha = alpha.value },
                )
            }
        }
        overlays()
        if (selectionMode) SelectionCheck(selected, Modifier.align(Alignment.TopStart).padding(8.dp))
    }
}

/** Round selection mark for tiles: filled `accent` with a check when selected, a light ring otherwise. */
@Composable
public fun SelectionCheck(selected: Boolean, modifier: Modifier = Modifier) {
    val c = BentoTheme.colors
    Box(
        modifier
            .size(22.dp)
            .clip(BentoShapes.full)
            .background(if (selected) c.accent else c.black.copy(alpha = 0.18f))
            .border(1.5.dp, if (selected) c.raised else c.white.copy(alpha = 0.9f), BentoShapes.full)
            .clearAndSetSemantics {},
        contentAlignment = Alignment.Center,
    ) {
        if (selected) BentoIcon(BentoIcons.Check, contentDescription = null, tint = c.onAccent, size = 14.dp)
    }
}

/** Overlay pill for video tiles: ▶ + duration, white on a dark veil (readable over any photo). */
@Composable
public fun VideoBadge(duration: String?, modifier: Modifier = Modifier) {
    val c = BentoTheme.colors
    Row(
        modifier
            .clip(BentoShapes.full)
            .background(c.black.copy(alpha = 0.5f))
            .padding(horizontal = 6.dp, vertical = 2.dp),
        horizontalArrangement = Arrangement.spacedBy(3.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        BentoIcon(BentoIcons.Play, contentDescription = null, tint = c.white, size = 12.dp)
        if (duration != null) Text(duration, color = c.white, style = BentoTheme.typography.badge.copy(fontFeatureSettings = "tnum"))
    }
}

/**
 * The favorite heart: the only shu element outside the logo (brand.md §4.3). Filled shu when favorite; an outline
 * in the current content color otherwise.
 */
@Composable
public fun BentoFavorite(favorite: Boolean, modifier: Modifier = Modifier, size: Dp = BentoIconSize.Standard, onMedia: Boolean = false) {
    val c = BentoTheme.colors
    BentoIcon(
        icon = if (favorite) BentoIcons.HeartFilled else BentoIcons.Heart,
        contentDescription = null,
        tint = when {
            favorite -> c.shu
            onMedia -> c.white
            else -> c.inkMuted
        },
        size = size,
        modifier = modifier,
    )
}

/** Toggle button for favorites with the correct TalkBack state ("Añadir a favoritos" / "Quitar de favoritos"). */
@Composable
public fun BentoFavoriteButton(favorite: Boolean, onFavoriteChange: (Boolean) -> Unit, modifier: Modifier = Modifier, onMedia: Boolean = false) {
    val label = stringResource(if (favorite) StringsR.string.ds_favorite_remove else StringsR.string.ds_favorite_add)
    BentoTooltip(label, modifier) {
        Box(
            Modifier
                .minimumInteractiveComponentSize()
                .size(48.dp)
                .clip(BentoShapes.full)
                .toggleable(favorite, remember { androidx.compose.foundation.interaction.MutableInteractionSource() }, ripple(), role = Role.Switch, onValueChange = onFavoriteChange)
                .semantics { contentDescription = label },
            contentAlignment = Alignment.Center,
        ) {
            BentoFavorite(favorite, size = BentoIconSize.Large, onMedia = onMedia)
        }
    }
}

/** One action of [FloatingActionBar]. Destructive actions are tinted `danger-ink`. */
@Immutable
public data class FloatingAction(
    val icon: ImageVector,
    val label: String,
    val onClick: () -> Unit,
    val destructive: Boolean = false,
)

/**
 * Selection reveals this bar instead of shifting the layout (motion-interaction.md). It slides up (fades with reduced
 * motion), floats with `shadow-lg`, shows up to four icon actions with tooltips and puts the rest in an overflow menu.
 */
@Composable
public fun FloatingActionBar(
    visible: Boolean,
    actions: List<FloatingAction>,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
    title: String? = null,
    overflow: List<FloatingAction> = emptyList(),
    closeLabel: String = stringResource(StringsR.string.ds_clear_selection),
) {
    val motion = BentoTheme.motion
    AnimatedVisibility(visible, modifier, enter = motion.slideUpIn, exit = motion.slideDownOut) {
        FloatingActionBarContent(actions, onClose, title, overflow, closeLabel)
    }
}

@Composable
internal fun FloatingActionBarContent(
    actions: List<FloatingAction>,
    onClose: () -> Unit,
    title: String?,
    overflow: List<FloatingAction>,
    closeLabel: String,
) {
    val c = BentoTheme.colors
    var menu by remember { mutableStateOf(false) }
    Row(
        Modifier
            .padding(horizontal = 16.dp, vertical = 12.dp)
            .widthIn(max = 560.dp)
            .fillMaxWidth()
            .heightIn(min = 64.dp)
            .bentoShadow(BentoElevation.Lg, BentoShapes.xl)
            .clip(BentoShapes.xl)
            .background(c.raised)
            .border(1.dp, c.line, BentoShapes.xl)
            .testTag(BentoTestTags.FloatingActionBar)
            .padding(horizontal = 6.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        BentoIconButton(BentoIcons.X, closeLabel, onClose)
        if (title != null) {
            Text(title, color = c.ink, style = BentoTheme.typography.labelStrong.copy(fontFeatureSettings = "tnum"), maxLines = 1, modifier = Modifier.padding(start = 4.dp).weight(1f))
        } else {
            Box(Modifier.weight(1f))
        }
        actions.take(4).forEach { action ->
            BentoIconButton(action.icon, action.label, action.onClick, tint = if (action.destructive) c.dangerInk else c.ink)
        }
        if (overflow.isNotEmpty()) {
            Box {
                BentoIconButton(BentoIcons.EllipsisVertical, stringResource(StringsR.string.ds_more_options), { menu = true })
                DropdownMenu(
                    expanded = menu,
                    onDismissRequest = { menu = false },
                    shape = BentoShapes.lg,
                    containerColor = c.raised,
                    tonalElevation = 0.dp,
                    shadowElevation = 8.dp,
                ) {
                    overflow.forEach { action ->
                        val tint = if (action.destructive) c.dangerInk else c.ink
                        DropdownMenuItem(
                            text = { Text(action.label, color = tint, style = BentoTheme.typography.body) },
                            leadingIcon = { BentoIcon(action.icon, contentDescription = null, tint = tint) },
                            onClick = {
                                menu = false
                                action.onClick()
                            },
                            modifier = Modifier.heightIn(min = 48.dp),
                        )
                    }
                }
            }
        }
    }
}
