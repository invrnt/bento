package dev.bento.app.navigation

import androidx.navigation3.runtime.NavKey
import kotlinx.serialization.Serializable

/**
 * Every navigation destination (Navigation 3 keys, saved across process death). Feature agents add their
 * keys here and register the screen in [BentoNavGraph] — one line each (execution/android-program.md).
 */
sealed interface Route : NavKey {
    // Top-level (navigation bar / rail): product/android.md §3.
    @Serializable data object Photos : Route

    @Serializable data class Files(val folderId: String? = null) : Route

    @Serializable data object Collections : Route

    // Full-screen destinations.
    @Serializable data class Search(val query: String = "") : Route

    @Serializable data class Viewer(val assetId: String) : Route

    @Serializable data class Album(val albumId: String) : Route

    @Serializable data object Trash : Route

    @Serializable data object Activity : Route

    @Serializable data object Settings : Route

    @Serializable data object Devices : Route

    @Serializable data object Onboarding : Route

    /** Join by pairing code (from `bento://join` / App Links, or typed). */
    @Serializable data class Join(val code: String? = null) : Route

    @Serializable data object Recovery : Route
}

/** The three tabs, in order; [Route.Photos] is the start destination. */
enum class TopLevel(val route: Route, val labelRes: Int, val glyph: String) {
    PHOTOS(Route.Photos, dev.bento.app.R.string.nav_photos, "▣"),
    FILES(Route.Files(), dev.bento.app.R.string.nav_files, "▢"),
    COLLECTIONS(Route.Collections, dev.bento.app.R.string.nav_collections, "◫"),
    ;

    companion object {
        fun of(route: Route): TopLevel? = entries.firstOrNull { it.route::class == route::class && (route !is Route.Files || route.folderId == null) }
    }
}
