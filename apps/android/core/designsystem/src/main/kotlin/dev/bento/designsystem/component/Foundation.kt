package dev.bento.designsystem.component

import androidx.compose.foundation.border
import androidx.compose.foundation.interaction.InteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.size
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.PlainTooltip
import androidx.compose.material3.Text
import androidx.compose.material3.TooltipAnchorPosition
import androidx.compose.material3.TooltipBox
import androidx.compose.material3.TooltipDefaults
import androidx.compose.material3.rememberTooltipState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme

/** Icon sizes for touch (brand.md §8 mobile step-up). */
public object BentoIconSize {
    public val Dense: Dp = 16.dp
    public val Standard: Dp = 20.dp
    public val Large: Dp = 24.dp
}

/** A Lucide icon tinted with a Bento color. Pass `contentDescription = null` when a visible label names it. */
@Composable
public fun BentoIcon(
    icon: ImageVector,
    contentDescription: String?,
    modifier: Modifier = Modifier,
    tint: Color = LocalContentColor.current,
    size: Dp = BentoIconSize.Standard,
) {
    Icon(imageVector = icon, contentDescription = contentDescription, modifier = modifier.size(size), tint = tint)
}

/** Shows [label] on long-press (touch) and hover (mouse/ChromeOS). Every icon-only control uses it. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
public fun BentoTooltip(label: String, modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    val colors = BentoTheme.colors
    TooltipBox(
        positionProvider = TooltipDefaults.rememberTooltipPositionProvider(TooltipAnchorPosition.Above),
        tooltip = {
            PlainTooltip(
                shape = BentoShapes.sm,
                containerColor = colors.tooltip,
                contentColor = colors.inkInverse,
            ) { Text(label, style = BentoTheme.typography.metadata) }
        },
        state = rememberTooltipState(),
        modifier = modifier,
        content = content,
    )
}

/** 2 dp ring in `focus` while focused from a keyboard, switch access or D-pad (brand.md §13). */
public fun Modifier.bentoFocusRing(interactionSource: InteractionSource, shape: Shape): Modifier = composed {
    val focused by interactionSource.collectIsFocusedAsState()
    if (focused) border(2.dp, BentoTheme.colors.focus, shape) else this
}
