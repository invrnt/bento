package dev.bento.designsystem.theme

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.dropShadow
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.shadow.Shadow
import androidx.compose.ui.unit.DpOffset
import dev.bento.designsystem.generated.BentoShadowLayer

/** Ink-tinted shadow levels (brand.md §7). Tonal surfaces come first; shadows only for floating layers. */
public enum class BentoElevation { None, Xs, Sm, Md, Lg, Xl }

@Composable
internal fun layersFor(level: BentoElevation): List<BentoShadowLayer> {
    val s = BentoTheme.shadows
    return when (level) {
        BentoElevation.None -> emptyList()
        BentoElevation.Xs -> s.xs
        BentoElevation.Sm -> s.sm
        BentoElevation.Md -> s.md
        BentoElevation.Lg -> s.lg
        BentoElevation.Xl -> s.xl
    }
}

/** Draws the token shadow layers behind [shape]; no Material tonal tint is involved. */
public fun Modifier.bentoShadow(level: BentoElevation, shape: Shape): Modifier = composed {
    var result: Modifier = Modifier
    for (layer in layersFor(level).filterNot { it.inset }) {
        result = result.dropShadow(
            shape,
            Shadow(radius = layer.blur, color = layer.color, spread = layer.spread, offset = DpOffset(layer.x, layer.y))
        )
    }
    this.then(result)
}
