package dev.bento.app.navigation

import androidx.compose.ui.graphics.vector.ImageVector
import androidx.navigation3.runtime.NavKey
import dev.bento.designsystem.generated.BentoNavIcons
import dev.bento.strings.R as StringsR
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

    /**
     * Visor. [position] is the item's position in its source (the timeline when [session] is null); [session] is a
     * grid's `ViewerSessions` token (favorites, videos, album). From elsewhere, just the asset.
     */
    @Serializable data class Viewer(val assetId: String, val position: Int = -1, val session: String? = null) : Route

    @Serializable data class Album(val albumId: String) : Route

    /** Library picker: a new album (null) or `Añadir fotos` to [albumId]. */
    @Serializable data class AlbumPicker(val albumId: String? = null, val albumTitle: String? = null) : Route

    @Serializable data object Favorites : Route

    @Serializable data object Videos : Route

    @Serializable data object Documents : Route

    /** Del teléfono: backed-up phone folders. */
    @Serializable data object PhoneFolders : Route

    /** Importado de Telegram, then its chat picker and one chat's media. */
    @Serializable data object TelegramImports : Route

    @Serializable data object TelegramChats : Route

    @Serializable data class TelegramChat(val chatId: Long, val title: String) : Route

    /** Cuenta y actividad (avatar); PLACEHOLDER until agent 41 lands the sheet. */
    @Serializable data object Account : Route

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
enum class TopLevel(val route: Route, val labelRes: Int, val icon: ImageVector) {
    PHOTOS(Route.Photos, StringsR.string.shell_nav_photos, BentoNavIcons.Images),
    FILES(Route.Files(), StringsR.string.shell_nav_files, BentoNavIcons.FolderClosed),
    COLLECTIONS(Route.Collections, StringsR.string.shell_nav_collections, BentoNavIcons.SquareLibrary)
    ;

    companion object {
        fun of(route: Route): TopLevel? = entries.firstOrNull {
            it.route::class == route::class &&
                (route !is Route.Files || route.folderId == null)
        }
    }
}
