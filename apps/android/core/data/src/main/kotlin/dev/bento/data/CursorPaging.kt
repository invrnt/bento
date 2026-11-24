package dev.bento.data

import androidx.paging.PagingSource
import androidx.paging.PagingState
import dev.bento.api.ApiException

/** One keyset page from the backend (`items` + `next_cursor`). */
data class CursorPage<T : Any>(val items: List<T>, val nextCursor: String?)

/**
 * Keyset-cursor [PagingSource] (architecture/android-runtime.md §8). Append-only: the backend's cursors are
 * opaque and forward-only, so a refresh restarts from the first page and Compose keeps stable item keys.
 */
class CursorPagingSource<T : Any>(
    private val fetch: suspend (cursor: String?, limit: Int) -> CursorPage<T>
) : PagingSource<String, T>() {
    override suspend fun load(params: LoadParams<String>): LoadResult<String, T> = try {
        val page = fetch(params.key, params.loadSize)
        LoadResult.Page(data = page.items, prevKey = null, nextKey = page.nextCursor?.takeIf { it != params.key })
    } catch (error: ApiException) {
        LoadResult.Error(error)
    }

    override fun getRefreshKey(state: PagingState<String, T>): String? = null
}

/** Default page sizes: first page fills a phone grid; later pages amortize the loopback round trip. */
object PageSizes {
    const val GRID = 120
    const val LIST = 50
    const val SEARCH = 50
}
