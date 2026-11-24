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

    @Serializable data class Viewer(val assetId: String) : Route

    @Serializable data class Album(val albumId: String) : Route

    @Serializable data object Trash : Route

    @Serializable data object Activity : Route

    @Serializable data object Settings : Route

    @Serializable data object Devices : Route

    /** First run (Bienvenida → Telegram → nube → respaldo → avisos → kit → Listo). */
    @Serializable data object Onboarding : Route

    /**
     * Join by pairing code (from `bento://join` / App Links, typed or scanned). [choose] starts at the join choice
     * (signed in, the account has a cloud: ask other devices or use the recovery kit). Never holds secrets beyond the
     * short-lived pairing code the link already carried.
     */
    @Serializable data class Join(val code: String? = null, val choose: Boolean = false) : Route

    /** Kit de recuperación (Ajustes › Cuenta y nube): status, generate a new code, verify. */
    @Serializable data object Recovery : Route

    /** Ajustes › Dispositivos › Añadir dispositivo: this phone as pairing host (QR, code, countdown, share link). */
    @Serializable data object AddDevice : Route

    /** Review of a Sync-channel join request ("Un dispositivo nuevo quiere unirse"). */
    @Serializable data class PairingRequest(val requestId: String) : Route

    /** New-device review ("Se añadió «X» a tu nube"), e.g. from the `Dispositivos` notification. */
    @Serializable data class DeviceReview(val deviceId: String) : Route

    /** This phone was removed from the cloud: read-only library, `Volver a unirme`. */
    @Serializable data object DeviceRemoved : Route

    /** The Telegram session of this phone was closed: reconnect, the library stays visible behind. */
    @Serializable data object Reconnect : Route

    /** Phone-backup setup (feature/settings, agent 41); onboarding hands off here and continues on return. */
    @Serializable data object BackupSetup : Route
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
