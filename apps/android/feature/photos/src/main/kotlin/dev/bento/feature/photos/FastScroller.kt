package dev.bento.feature.photos

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.grid.LazyGridState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.setProgress
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import dev.bento.data.TimelineLayout
import dev.bento.designsystem.theme.BentoElevation
import dev.bento.designsystem.theme.BentoHaptic
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.designsystem.theme.bentoHaptics
import dev.bento.designsystem.theme.bentoShadow
import dev.bento.strings.R as StringsR
import kotlin.math.roundToInt
import kotlinx.coroutines.delay

/** Fraction ↔ photo position for the fast scroller (pure; JVM tested). */
object FastScrollMath {
    fun positionFor(fraction: Float, total: Int): Int = if (total <= 1) 0 else (fraction.coerceIn(0f, 1f) * (total - 1)).roundToInt()

    fun fractionFor(position: Int, total: Int): Float = if (total <= 1) 0f else (position.toFloat() / (total - 1)).coerceIn(0f, 1f)

    /** Index of each year's first month (newest first), for the ticks. */
    fun yearStarts(layout: TimelineLayout): List<Pair<String, Int>> = buildList {
        var year: String? = null
        layout.months.forEachIndexed { i, month ->
            val y = month.month.take(4)
            if (y != year && month.count > 0) {
                add(y to layout.starts[i])
                year = y
            }
        }
    }
}

/**
 * Right-edge fast scroller (product/android.md §4.3): appears while scrolling, the thumb drags through the whole
 * library by index (never by layout; placeholders keep the height exact), a bubble shows the month, year ticks show
 * while dragging with a haptic tick at each year boundary. When the finger rests over photos that are not loaded, the
 * page at that spot loads directly ([onJump]). TalkBack can set the position (adjustable, like a slider).
 */
// Drag, bubble, ticks, haptics and TalkBack adjust share one position model; kept together on purpose.
@Suppress("LongMethod", "CyclomaticComplexMethod")
@Composable
internal fun FastScroller(
    gridState: LazyGridState,
    cells: MediaCells,
    layout: TimelineLayout,
    topOffset: Int,
    onJump: ((Int) -> Unit)?,
    modifier: Modifier = Modifier
) {
    val c = BentoTheme.colors
    val haptics = bentoHaptics()
    val locale = LocalConfiguration.current.locales[0]
    val px = LocalDensity.current
    val thumbHeight = 56.dp
    val thumbPx = with(px) { thumbHeight.toPx() }
    var dragging by remember { mutableStateOf(false) }
    var dragFraction by remember { mutableFloatStateOf(0f) }
    var target by remember { mutableIntStateOf(-1) }
    var visible by remember { mutableStateOf(false) }
    val scrolling = gridState.isScrollInProgress
    LaunchedEffect(scrolling, dragging) {
        if (scrolling || dragging) {
            visible = true
        } else {
            delay(1_500)
            visible = false
        }
    }
    val alpha by animateFloatAsState(if (visible) 1f else 0f, BentoTheme.motion.state(), label = "fast-scroller")
    val total = cells.positions().totalPhotos

    fun currentFraction(): Float {
        if (dragging) return dragFraction
        val first = gridState.firstVisibleItemIndex - topOffset
        return FastScrollMath.fractionFor(cells.positions().photoAt(first.coerceAtLeast(0)), total)
    }

    fun monthLabel(position: Int): String {
        val month = layout.months.getOrNull(layout.monthAt(position))?.month ?: return ""
        return MediaFormat.monthShort(month, locale)
    }

    fun scrollTo(fraction: Float) {
        dragFraction = fraction.coerceIn(0f, 1f)
        val position = FastScrollMath.positionFor(dragFraction, total)
        val previousYear = layout.months.getOrNull(layout.monthAt(target.coerceAtLeast(0)))?.month?.take(4)
        val year = layout.months.getOrNull(layout.monthAt(position))?.month?.take(4)
        if (target >= 0 && year != previousYear) haptics.perform(BentoHaptic.SegmentTick)
        target = position
        gridState.requestScrollToItem(cells.positions().indexOf(position) + topOffset)
    }

    // Resting over placeholders: load that page directly (one request from the month's cursor).
    LaunchedEffect(target, dragging) {
        val position = target
        if (!dragging || position < 0 || onJump == null) return@LaunchedEffect
        delay(120)
        if (!cells.positions().isLoaded(position)) onJump(position)
    }

    val label = stringResource(StringsR.string.photos_fast_scroller)
    BoxWithConstraints(modifier.fillMaxSize().graphicsLayer { this.alpha = alpha }) {
        val trackPx = (constraints.maxHeight - thumbPx).coerceAtLeast(1f)
        if (dragging) YearTicks(layout, total, trackPx, thumbPx)
        val draggableState = rememberDraggableState { delta -> scrollTo(dragFraction + delta / trackPx) }
        Box(
            Modifier
                .align(Alignment.TopEnd)
                .offset { IntOffset(0, (currentFraction() * trackPx).roundToInt()) }
                .size(width = 48.dp, height = thumbHeight)
                .testTag(MediaTestTags.FastScroller)
                .then(
                    if (alpha > 0f) {
                        Modifier.draggable(
                            draggableState,
                            Orientation.Vertical,
                            startDragImmediately = true,
                            onDragStarted = {
                                dragFraction = currentFraction()
                                target = FastScrollMath.positionFor(dragFraction, total)
                                dragging = true
                            },
                            onDragStopped = { dragging = false }
                        )
                    } else {
                        Modifier
                    }
                )
                .semantics {
                    contentDescription = label
                    stateDescription = monthLabel(FastScrollMath.positionFor(currentFraction(), total))
                    progressBarRangeInfo = ProgressBarRangeInfo(currentFraction(), 0f..1f)
                    setProgress { value ->
                        scrollTo(value)
                        target.takeIf { it >= 0 && !cells.positions().isLoaded(it) }?.let { onJump?.invoke(it) }
                        true
                    }
                },
            contentAlignment = Alignment.CenterEnd
        ) {
            Box(
                Modifier
                    .padding(end = 4.dp)
                    .size(width = if (dragging) 8.dp else 6.dp, height = 44.dp)
                    .bentoShadow(BentoElevation.Sm, BentoShapes.full)
                    .clip(BentoShapes.full)
                    .background(if (dragging) c.accent else c.inkMuted)
            )
        }
        if (dragging && target >= 0) {
            Box(
                Modifier
                    .align(Alignment.TopEnd)
                    .offset {
                        IntOffset(
                            -with(px) {
                                60.dp.roundToPx()
                            },
                            (dragFraction * trackPx + thumbPx / 2 - with(px) { 20.dp.toPx() }).roundToInt()
                        )
                    }
                    .bentoShadow(BentoElevation.Md, BentoShapes.full)
                    .clip(BentoShapes.full)
                    .background(c.raised)
                    .border(1.dp, c.line, BentoShapes.full)
                    .padding(horizontal = 16.dp, vertical = 10.dp)
                    .testTag(MediaTestTags.FastScrollerBubble)
                    .clearAndSetSemantics {}
            ) {
                Text(monthLabel(target), color = c.ink, style = BentoTheme.typography.labelStrong.copy(fontFeatureSettings = "tnum"))
            }
        }
    }
}

@Composable
private fun YearTicks(layout: TimelineLayout, total: Int, trackPx: Float, thumbPx: Float) {
    val px = LocalDensity.current
    val minGap = with(px) { 22.dp.toPx() }
    val c = BentoTheme.colors
    var lastY = -minGap
    FastScrollMath.yearStarts(layout).forEach { (year, start) ->
        val y = FastScrollMath.fractionFor(start, total) * trackPx + thumbPx / 2 - with(px) { 9.dp.toPx() }
        if (y - lastY < minGap) return@forEach
        lastY = y
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopEnd) {
            Text(
                year,
                color = c.inkMuted,
                style = BentoTheme.typography.caption.copy(fontFeatureSettings = "tnum"),
                modifier = Modifier
                    .offset { IntOffset(-with(px) { 20.dp.roundToPx() }, y.roundToInt()) }
                    .clip(BentoShapes.sm)
                    .background(c.raised.copy(alpha = 0.92f))
                    .padding(horizontal = 6.dp, vertical = 1.dp)
                    .clearAndSetSemantics {}
            )
        }
    }
}
