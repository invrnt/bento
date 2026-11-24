package dev.bento.feature.photos

import androidx.compose.runtime.Immutable
import androidx.compose.runtime.Stable
import androidx.paging.PagingData
import androidx.paging.compose.LazyPagingItems
import androidx.paging.filter
import androidx.paging.insertSeparators
import androidx.paging.map
import dev.bento.api.generated.AssetResponse
import dev.bento.data.TimelineEntry

/** One row item of a media grid: month header, day sub-header, or a photo/video tile. Keys are stable across pages. */
@Immutable
sealed interface GridCell {
    val key: String
    val month: String

    data class Month(override val month: String) : GridCell {
        override val key: String get() = "month:$month"
    }

    data class Day(val date: String) : GridCell {
        override val key: String get() = "day:$date"
        override val month: String get() = date.take(7)
    }

    data class Media(val asset: AssetResponse, val date: String) : GridCell {
        override val key: String get() = "asset:${asset.id}"
        override val month: String get() = date.take(7)
    }
}

/** Timeline entries → grid cells with month headers (and day sub-headers unless the month view hides them). */
fun PagingData<TimelineEntry>.toGridCells(dayHeaders: Boolean): PagingData<GridCell> = filter { dayHeaders || it !is TimelineEntry.Day }
    .map { entry ->
        when (entry) {
            is TimelineEntry.Day -> GridCell.Day(entry.date)
            is TimelineEntry.Photo -> GridCell.Media(entry.asset, entry.date)
        }
    }
    .insertSeparators { before, after ->
        if (after == null || after is GridCell.Month) return@insertSeparators null
        if (before == null || before.month != after.month) GridCell.Month(after.month) else null
    }

/** Static cells (cached first screen, previews, tests): the same headers as the live grid. */
fun cellsOf(assets: List<AssetResponse>, dayHeaders: Boolean = true): List<GridCell> = buildList {
    var month: String? = null
    var day: String? = null
    assets.forEach { asset ->
        val date = MediaFormat.dayOf(asset)
        if (date.take(7) != month) {
            month = date.take(7)
            add(GridCell.Month(date.take(7)))
        }
        if (dayHeaders && date != day) add(GridCell.Day(date))
        day = date
        add(GridCell.Media(asset, date))
    }
}

/**
 * What a media grid renders. [get] may trigger a page load (Paging); [peek] never does. A null cell is a placeholder
 * (a photo not loaded yet): it renders as a `sunken` tile.
 */
@Stable
interface MediaCells {
    val count: Int

    fun peek(index: Int): GridCell?

    operator fun get(index: Int): GridCell?

    /** Photo positions ↔ grid indices for the current snapshot (fast scroller, sticky header). */
    fun positions(): PositionMap

    /** A loaded asset by id (O(loaded)); used once per viewer open. */
    fun peekAsset(id: String): dev.bento.api.generated.AssetResponse? =
        (0 until count).firstNotNullOfOrNull { (peek(it) as? GridCell.Media)?.asset?.takeIf { asset -> asset.id == id } }
}

class ListMediaCells(private val cells: List<GridCell>) : MediaCells {
    private val map by lazy { PositionMap(0, cells, 0) }
    override val count: Int get() = cells.size

    override fun peek(index: Int): GridCell? = cells.getOrNull(index)

    override fun get(index: Int): GridCell? = cells.getOrNull(index)

    override fun positions(): PositionMap = map
}

class PagingMediaCells(private val items: LazyPagingItems<GridCell>) : MediaCells {
    override val count: Int get() = items.itemCount

    override fun peek(index: Int): GridCell? = if (index in 0 until items.itemCount) items.peek(index) else null

    override fun get(index: Int): GridCell? = if (index in 0 until items.itemCount) items[index] else null

    override fun positions(): PositionMap {
        val snapshot = items.itemSnapshotList
        return PositionMap(snapshot.placeholdersBefore, snapshot.items, snapshot.placeholdersAfter)
    }
}

/**
 * Maps between grid indices and photo positions for one Paging snapshot: placeholders stand for photos only
 * (headers exist only inside the loaded block), so the mapping is exact. O(loaded) to build, O(log n) per lookup.
 */
class PositionMap(private val placeholdersBefore: Int, private val loaded: List<GridCell>, private val placeholdersAfter: Int) {
    /** Grid index (in [loaded]) of each loaded photo, in order. */
    private val photoIndices: IntArray = loaded.indices.filter { loaded[it] is GridCell.Media }.toIntArray()

    val totalPhotos: Int get() = placeholdersBefore + photoIndices.size + placeholdersAfter
    val gridCount: Int get() = placeholdersBefore + loaded.size + placeholdersAfter

    /** Photo position at grid [index] (a header maps to the photo right after it). */
    fun photoAt(index: Int): Int {
        if (index < placeholdersBefore) return index
        val local = index - placeholdersBefore
        if (local < loaded.size) {
            val insertion = photoIndices.binarySearch(local).let { if (it >= 0) it else -it - 1 }
            return placeholdersBefore + insertion
        }
        return placeholdersBefore + photoIndices.size + (local - loaded.size)
    }

    /** Grid index showing photo [position]. */
    fun indexOf(position: Int): Int {
        val p = position.coerceIn(0, (totalPhotos - 1).coerceAtLeast(0))
        if (p < placeholdersBefore) return p
        val local = p - placeholdersBefore
        if (local < photoIndices.size) return placeholdersBefore + photoIndices[local]
        return placeholdersBefore + loaded.size + (local - photoIndices.size)
    }

    /** True when photo [position] is loaded (not a placeholder). */
    fun isLoaded(position: Int): Boolean = position - placeholdersBefore in photoIndices.indices

    private fun IntArray.binarySearch(value: Int): Int = java.util.Arrays.binarySearch(this, value)
}
