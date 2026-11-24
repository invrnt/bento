package dev.bento.feature.photos

import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.calculateCentroid
import androidx.compose.foundation.gestures.calculateZoom
import androidx.compose.foundation.lazy.grid.LazyGridState
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChanged

/** Grid index of the item under [offset] (viewport coordinates), or null over a gap. */
fun LazyGridState.itemIndexAt(offset: Offset): Int? = layoutInfo.visibleItemsInfo.firstOrNull { item ->
    offset.x >= item.offset.x && offset.x < item.offset.x + item.size.width &&
        offset.y >= item.offset.y && offset.y < item.offset.y + item.size.height
}?.index

/**
 * Two-finger pinch → density steps. Runs in the Initial pass and consumes moves only while two fingers are down, so a
 * one-finger scroll is never affected and the grid does not scroll during a pinch.
 */
fun Modifier.pinchToDensity(enabled: Boolean, onStep: (direction: Int, centroid: Offset) -> Unit): Modifier = if (!enabled) {
    this
} else {
    pointerInput(Unit) {
        val stepper = PinchStepper()
        awaitEachGesture {
            awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
            stepper.reset()
            do {
                val event = awaitPointerEvent(PointerEventPass.Initial)
                if (event.changes.count { it.pressed } >= 2) {
                    val step = stepper.feed(event.calculateZoom())
                    if (step != 0) onStep(step, event.calculateCentroid(useCurrent = true))
                    event.changes.forEach { if (it.positionChanged()) it.consume() }
                }
            } while (event.changes.any { it.pressed })
        }
    }
}

/**
 * Long-press then drag (the Google-Photos-class range gesture). Detection runs in the Initial pass: once the long
 * press fires, every later change is consumed, so the tile underneath never also receives a click and the grid does not
 * scroll; edge auto-scroll is driven by the caller from [onDrag] positions.
 */
fun Modifier.longPressDragSelect(
    enabled: Boolean,
    onStart: (Offset) -> Boolean,
    onDrag: (Offset) -> Unit,
    onEnd: () -> Unit
): Modifier = if (!enabled) {
    this
} else {
    pointerInput(Unit) {
        awaitEachGesture {
            val down = awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
            val slop = viewConfiguration.touchSlop
            val cancelled = withTimeoutOrNull(viewConfiguration.longPressTimeoutMillis) {
                while (true) {
                    val event = awaitPointerEvent(PointerEventPass.Initial)
                    val change = event.changes.firstOrNull { it.id == down.id } ?: return@withTimeoutOrNull true
                    if (!change.pressed || event.changes.size > 1 || change.isConsumed) return@withTimeoutOrNull true
                    if ((change.position - down.position).getDistance() > slop) return@withTimeoutOrNull true
                }
                @Suppress("UNREACHABLE_CODE")
                true
            }
            if (cancelled == true) return@awaitEachGesture
            if (!onStart(down.position)) return@awaitEachGesture
            try {
                while (true) {
                    val event = awaitPointerEvent(PointerEventPass.Initial)
                    val change = event.changes.firstOrNull { it.id == down.id } ?: break
                    event.changes.forEach { it.consume() }
                    if (!change.pressed) break
                    onDrag(change.position)
                }
            } finally {
                onEnd()
            }
        }
    }
}
