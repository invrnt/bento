package dev.bento.data

import androidx.paging.PagingSource
import androidx.paging.PagingState
import dev.bento.api.ApiException
import java.util.TreeMap
import java.util.concurrent.atomic.AtomicReference

/**
 * Photo positions of the whole library from the month index (`GET /photos/timeline/index`): month `i` covers
 * `[starts[i], starts[i] + months[i].count)`. Newest month first, like the timeline. Pure (JVM tested).
 */
class TimelineLayout(val months: List<MonthIndexEntry>) {
    val starts: IntArray = IntArray(months.size).also { array ->
        var sum = 0
        months.forEachIndexed { i, month ->
            array[i] = sum
            sum += month.count
        }
    }
    val total: Int = months.sumOf { it.count }

    /** Month index containing photo [position] (binary search, O(log months)); -1 for an empty library. */
    fun monthAt(position: Int): Int {
        if (months.isEmpty()) return -1
        var low = 0
        var high = months.lastIndex
        val target = position.coerceIn(0, (total - 1).coerceAtLeast(0))
        while (low < high) {
            val mid = (low + high + 1) ushr 1
            if (starts[mid] <= target) low = mid else high = mid - 1
        }
        return low
    }

    companion object {
        val EMPTY = TimelineLayout(emptyList())
    }
}

/**
 * Timeline [PagingSource] keyed by photo position, with placeholders for the whole library so the grid and the fast
 * scroller know the full height up front. Any position loads without walking the pages before it: the nearest known
 * cursor (month starts from the index, page ends seen so far) is followed forward at most `offset / 200` requests.
 *
 * [jumps] lets the UI request an exact refresh position (fast-scroller release, fling landing in placeholders): the
 * refresh page then starts exactly at that photo, so nothing above the viewport shifts when it arrives.
 */
class TimelinePositionalSource(
    private val fetchPage: suspend (cursor: String?, limit: Int) -> CursorPage<TimelineEntry.Photo>,
    private val fetchIndex: suspend () -> List<MonthIndexEntry>,
    private val onLayout: (TimelineLayout) -> Unit,
    private val jumps: AtomicReference<Int?>
) : PagingSource<Int, TimelineEntry.Photo>() {
    override val jumpingSupported: Boolean = true

    private var layout: TimelineLayout? = null
    private val cursors = TreeMap<Int, String?>()

    override fun getRefreshKey(state: PagingState<Int, TimelineEntry.Photo>): Int? = jumps.getAndSet(null) ?: state.anchorPosition

    override suspend fun load(params: LoadParams<Int>): LoadResult<Int, TimelineEntry.Photo> = try {
        val layout = layout ?: TimelineLayout(fetchIndex()).also { built ->
            layout = built
            synchronized(cursors) {
                cursors[0] = null
                built.months.forEachIndexed { i, month -> if (month.firstCursor != null) cursors.putIfAbsent(built.starts[i], month.firstCursor) }
            }
            onLayout(built)
        }
        val (start, count) = range(params, layout.total)
        val fetched = fetchRange(start, count)
        val end = start + fetched.items.size
        val total = maxOf(layout.total, end)
        LoadResult.Page(
            data = fetched.items,
            prevKey = start.takeIf { it > 0 },
            nextKey = if (fetched.reachedEnd || fetched.items.isEmpty()) null else end,
            itemsBefore = start,
            itemsAfter = if (fetched.reachedEnd) 0 else (total - end).coerceAtLeast(0)
        )
    } catch (error: ApiException) {
        LoadResult.Error(error)
    }

    private fun range(params: LoadParams<Int>, total: Int): Pair<Int, Int> = when (params) {
        is LoadParams.Refresh -> (params.key ?: 0).coerceIn(0, (total - 1).coerceAtLeast(0)) to params.loadSize
        is LoadParams.Append -> params.key to params.loadSize
        is LoadParams.Prepend -> {
            val start = (params.key - params.loadSize).coerceAtLeast(0)
            start to (params.key - start)
        }
    }

    private class Fetched(val items: List<TimelineEntry.Photo>, val reachedEnd: Boolean)

    /** Photos `[start, start + count)`: skips forward from the nearest known cursor, remembering every page end. */
    private suspend fun fetchRange(start: Int, count: Int): Fetched {
        val known = synchronized(cursors) { cursors.floorEntry(start) } ?: return Fetched(emptyList(), true)
        var position = known.key
        var cursor = known.value
        val out = ArrayList<TimelineEntry.Photo>(count)
        while (position < start + count) {
            val want = if (position < start) start - position else start + count - position
            val page = fetchPage(cursor, want.coerceAtMost(MAX_REQUEST))
            if (position >= start) out += page.items
            position += page.items.size
            cursor = page.nextCursor
            if (cursor == null || page.items.isEmpty()) return Fetched(out, true)
            synchronized(cursors) { cursors[position] = cursor }
        }
        return Fetched(out, false)
    }

    private companion object {
        /** The backend clamps `limit` to 200 (`routes._safe_limit`). */
        const val MAX_REQUEST = 200
    }
}

/**
 * A filtered collection over the timeline (Favoritos, Videos) until the backend can filter: each load scans forward
 * until it has [minMatches] items or has read [maxScan] photos, so sparse filters never stall the pager.
 */
class FilteredTimelineSource(
    private val fetchPage: suspend (cursor: String?, limit: Int) -> CursorPage<TimelineEntry.Photo>,
    private val predicate: (TimelineEntry.Photo) -> Boolean,
    private val minMatches: Int = 60,
    private val maxScan: Int = 2_000
) : PagingSource<String, TimelineEntry.Photo>() {
    override suspend fun load(params: LoadParams<String>): LoadResult<String, TimelineEntry.Photo> = try {
        var cursor = params.key
        var scanned = 0
        val out = ArrayList<TimelineEntry.Photo>()
        var next: String? = cursor
        while (out.size < minMatches && scanned < maxScan) {
            val page = fetchPage(cursor, 200)
            out += page.items.filter(predicate)
            scanned += page.items.size
            next = page.nextCursor
            if (next == null || page.items.isEmpty()) break
            cursor = next
        }
        LoadResult.Page(out, prevKey = null, nextKey = next?.takeIf { it != params.key })
    } catch (error: ApiException) {
        LoadResult.Error(error)
    }

    override fun getRefreshKey(state: PagingState<String, TimelineEntry.Photo>): String? = null
}
