package dev.bento.feature.photos

import androidx.compose.runtime.Stable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import dev.bento.api.generated.AssetResponse

/**
 * Multi-selection for media grids, keyed by asset id so it survives paging and density changes.
 *
 * Range drag (long-press, then drag): every photo between the anchor and the finger takes the state the anchor
 * switched to, on top of the selection that existed when the drag began; moving back releases what left the range.
 */
@Stable
class SelectionState {
    var selected: Map<String, AssetResponse> by mutableStateOf(emptyMap())
        private set

    val active: Boolean by derivedStateOf { selected.isNotEmpty() }
    val count: Int get() = selected.size

    private var dragBaseline: Map<String, AssetResponse>? = null
    private var dragAnchor = -1
    private var dragSelects = true

    operator fun contains(id: String): Boolean = id in selected

    fun toggle(asset: AssetResponse) {
        selected = if (asset.id in selected) selected - asset.id else selected + (asset.id to asset)
    }

    fun set(assets: Collection<AssetResponse>, select: Boolean) {
        selected = if (select) selected + assets.associateBy { it.id } else selected - assets.map { it.id }.toSet()
    }

    fun clear() {
        selected = emptyMap()
        dragBaseline = null
    }

    /** Replace a selected asset's snapshot (after an optimistic edit such as favorite). */
    fun refresh(asset: AssetResponse) {
        if (asset.id in selected) selected = selected + (asset.id to asset)
    }

    /** Long-press at grid [anchorIndex] on a media cell: toggles it and starts a range drag. */
    fun beginDrag(anchorIndex: Int, cells: MediaCells): Boolean {
        val anchor = (cells.peek(anchorIndex) as? GridCell.Media)?.asset ?: return false
        dragBaseline = selected
        dragAnchor = anchorIndex
        dragSelects = anchor.id !in selected
        applyRange(anchorIndex, cells)
        return true
    }

    /** The finger is over grid [index] (or the edge auto-scroll moved content under it). */
    fun dragTo(index: Int, cells: MediaCells) {
        if (dragBaseline == null) return
        applyRange(index, cells)
    }

    fun endDrag() {
        dragBaseline = null
        dragAnchor = -1
    }

    val dragging: Boolean get() = dragBaseline != null

    private fun applyRange(index: Int, cells: MediaCells) {
        val baseline = dragBaseline ?: return
        val from = minOf(dragAnchor, index).coerceAtLeast(0)
        val to = maxOf(dragAnchor, index).coerceAtMost(cells.count - 1)
        val range = LinkedHashMap<String, AssetResponse>()
        for (i in from..to) {
            val asset = (cells.peek(i) as? GridCell.Media)?.asset ?: continue
            range[asset.id] = asset
        }
        selected = if (dragSelects) baseline + range else baseline - range.keys
    }
}

/** Grid densities, from largest tiles to the month view's micro tiles (product/android.md §4.3). */
enum class GridDensity(private val tileDp: Int, private val minColumns: Int, private val maxColumns: Int, val dayHeaders: Boolean) {
    Large(180, 2, 5, true),
    Comfortable(110, 3, 7, true),
    Dense(75, 5, 10, true),
    Month(50, 8, 16, false)
    ;

    /** Columns for an available width in dp: 2/3/5/8 on a phone, more on wide windows. */
    fun columns(widthDp: Float): Int = (widthDp / tileDp).toInt().coerceIn(minColumns, maxColumns)

    /** Pinch out (spread) → bigger tiles. */
    fun larger(): GridDensity = entries.getOrElse(ordinal - 1) { this }

    /** Pinch in → more tiles. */
    fun smaller(): GridDensity = entries.getOrElse(ordinal + 1) { this }
}

/** Accumulates pinch zoom and reports one density step per threshold crossing (one haptic tick each). */
class PinchStepper(private val stepIn: Float = 1.3f, private val stepOut: Float = 0.77f) {
    private var accumulated = 1f

    fun reset() {
        accumulated = 1f
    }

    /** Returns +1 (bigger tiles), -1 (smaller tiles) or 0. */
    fun feed(zoom: Float): Int {
        accumulated *= zoom
        return when {
            accumulated >= stepIn -> 1.also { accumulated = 1f }
            accumulated <= stepOut -> (-1).also { accumulated = 1f }
            else -> 0
        }
    }
}
