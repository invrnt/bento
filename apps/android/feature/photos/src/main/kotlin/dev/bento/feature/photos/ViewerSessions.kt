package dev.bento.feature.photos

import dev.bento.api.generated.AssetResponse
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

/** What the viewer pages through (product/android.md §4.4: "horizontal paging across the current collection"). */
sealed interface ViewerSource {
    /** The whole timeline (shared positional pager; [ViewerSessions] is not needed). */
    data object Timeline : ViewerSource

    /** A collection's loaded items at the moment it opened the viewer (favorites, videos, album). */
    data class Snapshot(val assets: List<AssetResponse>) : ViewerSource

    /** Album order by id (each page loads its asset). */
    data class Ids(val ids: List<String>) : ViewerSource
}

/**
 * Hand-off between a grid and the viewer: the grid registers its source under a token (the route carries only the
 * token, so nothing large is saved in the back stack), and the viewer reports where the person ended up so the grid
 * can scroll that tile into view before the shared element flies back. After process death the token is gone and
 * the viewer falls back to the single asset.
 */
@Singleton
class ViewerSessions @Inject constructor() {
    private val sources = object : LinkedHashMap<String, ViewerSource>(8, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, ViewerSource>?) = size > MAX_SESSIONS
    }

    data class Return(val assetId: String, val position: Int)

    @Volatile private var lastReturn: Return? = null

    @Volatile private var opening: AssetResponse? = null

    /** The tapped tile's asset: the viewer's very first frame renders it before its pages arrive. */
    fun open(asset: AssetResponse) {
        opening = asset
    }

    fun opening(assetId: String): AssetResponse? = opening?.takeIf { it.id == assetId }

    @Synchronized
    fun register(source: ViewerSource): String = UUID.randomUUID().toString().also { sources[it] = source }

    @Synchronized
    fun source(token: String?): ViewerSource? = token?.let { sources[it] }

    fun reportPosition(assetId: String, position: Int) {
        lastReturn = Return(assetId, position)
    }

    /** The viewer's last item, once (the grid scrolls it into view on its first frame back). */
    fun consumeReturn(): Return? = lastReturn.also { lastReturn = null }

    private companion object {
        const val MAX_SESSIONS = 6
    }
}
