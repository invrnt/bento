package dev.bento.app.navigation

import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.navigation3.runtime.EntryProviderScope
import androidx.navigation3.ui.LocalNavAnimatedContentScope
import androidx.navigation3.ui.NavDisplay
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.collections.AlbumRoute
import dev.bento.feature.collections.CollectionsNavigation
import dev.bento.feature.collections.CollectionsRoute
import dev.bento.feature.collections.DocumentsRoute
import dev.bento.feature.collections.FilteredRoute
import dev.bento.feature.collections.LibraryPickerRoute
import dev.bento.feature.collections.MediaFilter
import dev.bento.feature.collections.PhoneFoldersRoute
import dev.bento.feature.collections.TelegramChatsRoute
import dev.bento.feature.collections.TelegramImportsContent
import dev.bento.feature.collections.TelegramMediaRoute
import dev.bento.feature.collections.TrashRoute
import dev.bento.feature.photos.PhotosNavigation
import dev.bento.feature.photos.PhotosRoute
import dev.bento.feature.viewer.ViewerArgs
import dev.bento.feature.viewer.ViewerNavigation
import dev.bento.feature.viewer.ViewerRoute
import dev.bento.strings.R as StringsR

/** Per-entry window-insets policy, read by the shell's insets decorator ([BentoApp]). Default: safe drawing. */
object EntryInsets {
    const val KEY = "bento.insets"
    const val TABS = "tabs"
    const val FULL_BLEED = "full-bleed"

    val Tabs: Map<String, Any> = mapOf(KEY to TABS)
    val FullBleed: Map<String, Any> = mapOf(KEY to FULL_BLEED)
}

/**
 * The viewer opens over the grid: the grid stays while the viewer's backdrop fades in and the tile's shared element
 * transforms (design-system/android.md §6). Pop and predictive back fade the backdrop out while the photo flies home.
 */
private val viewerMetadata: Map<String, Any> = EntryInsets.FullBleed +
    NavDisplay.transitionSpec { fadeIn(tween(220)) togetherWith ExitTransition.KeepUntilTransitionsFinished } +
    NavDisplay.popTransitionSpec { EnterTransition.None togetherWith fadeOut(tween(220)) } +
    NavDisplay.predictivePopTransitionSpec { EnterTransition.None togetherWith fadeOut(tween(220)) }

/**
 * Screen registration: one `entry<Route.X> { … }` line per destination. Entries still marked PLACEHOLDER are replaced
 * by their feature agent (Stage 21).
 */
fun EntryProviderScope<Route>.bentoEntries(navigator: Navigator) {
    entry<Route.Photos>(metadata = EntryInsets.Tabs) { PhotosRoute(photosNavigation(navigator), LocalNavAnimatedContentScope.current) }
    entry<Route.Files>(metadata = EntryInsets.Tabs) { key -> Placeholder("Archivos ${key.folderId.orEmpty()}") } // PLACEHOLDER (agent 40)
    entry<Route.Collections>(metadata = EntryInsets.Tabs) { CollectionsRoute(collectionsNavigation(navigator)) }
    entry<Route.Search> { Placeholder("Buscar") } // PLACEHOLDER (agent 40)
    entry<Route.Viewer>(metadata = viewerMetadata) { key ->
        ViewerRoute(ViewerArgs(key.assetId, key.position, key.session), viewerNavigation(navigator), LocalNavAnimatedContentScope.current)
    }
    entry<Route.Album> { key -> AlbumRoute(key.albumId, collectionsNavigation(navigator)) }
    entry<Route.AlbumPicker> { key ->
        LibraryPickerRoute(key.albumId, key.albumTitle, collectionsNavigation(navigator)) { navigator.back() }
    }
    entry<Route.Favorites> { FilteredRoute(MediaFilter.Favorites, collectionsNavigation(navigator)) }
    entry<Route.Videos> { FilteredRoute(MediaFilter.Videos, collectionsNavigation(navigator)) }
    entry<Route.Documents> { DocumentsRoute(collectionsNavigation(navigator)) }
    entry<Route.PhoneFolders> { PhoneFoldersRoute(collectionsNavigation(navigator)) }
    entry<Route.TelegramImports> {
        TelegramImportsContent(onBack = { navigator.back() }, onImport = { navigator.navigate(Route.TelegramChats) })
    }
    entry<Route.TelegramChats> { TelegramChatsRoute(collectionsNavigation(navigator)) }
    entry<Route.TelegramChat> { key ->
        TelegramMediaRoute(key.chatId, key.title, collectionsNavigation(navigator)) {
            navigator.back()
            navigator.back()
        }
    }
    entry<Route.Trash> { TrashRoute(collectionsNavigation(navigator)) }
    entry<Route.Account> { Placeholder("Cuenta y actividad") } // PLACEHOLDER (agent 41: account sheet)
    entry<Route.Activity> { Placeholder("Actividad") } // PLACEHOLDER (agent 41)
    entry<Route.Settings> { Placeholder("Ajustes") } // PLACEHOLDER (agent 41)
    entry<Route.Devices> { Placeholder("Dispositivos") } // PLACEHOLDER (agent 38)
    entry<Route.Onboarding> { Placeholder("Bienvenida") } // PLACEHOLDER (agent 38)
    entry<Route.Join> { key -> Placeholder("Unirse ${key.code.orEmpty()}") } // PLACEHOLDER (agent 38)
    entry<Route.Recovery> { Placeholder("Recuperación") } // PLACEHOLDER (agent 38)
}

private fun photosNavigation(navigator: Navigator) = PhotosNavigation(
    openViewer = { id, position -> navigator.navigate(Route.Viewer(id, position)) },
    openSearch = { navigator.navigate(Route.Search()) },
    openAccount = { navigator.navigate(Route.Account) },
    openBackupSettings = { navigator.navigate(Route.Settings) },
    openRecoveryKit = { navigator.navigate(Route.Recovery) },
    reconnect = { navigator.navigate(Route.Onboarding) }
)

private fun viewerNavigation(navigator: Navigator) = ViewerNavigation(
    back = { navigator.back() },
    openFolder = { navigator.navigate(Route.Files(it)) },
    openActivity = { navigator.navigate(Route.Activity) }
)

private fun collectionsNavigation(navigator: Navigator) = CollectionsNavigation(
    back = { navigator.back() },
    openSearch = { navigator.navigate(Route.Search()) },
    openAccount = { navigator.navigate(Route.Account) },
    openAlbum = { navigator.navigate(Route.Album(it)) },
    newAlbum = { navigator.navigate(Route.AlbumPicker()) },
    addToAlbum = { navigator.navigate(Route.AlbumPicker(albumId = it)) },
    openFavorites = { navigator.navigate(Route.Favorites) },
    openVideos = { navigator.navigate(Route.Videos) },
    openDocuments = { navigator.navigate(Route.Documents) },
    openPhone = { navigator.navigate(Route.PhoneFolders) },
    openTelegram = { navigator.navigate(Route.TelegramImports) },
    openTelegramChats = { navigator.navigate(Route.TelegramChats) },
    openTelegramChat = { id, title -> navigator.navigate(Route.TelegramChat(id, title)) },
    openTrash = { navigator.navigate(Route.Trash) },
    openBackupSettings = { navigator.navigate(Route.Settings) },
    openViewer = { id, position, session -> navigator.navigate(Route.Viewer(id, position, session)) }
)

/** Every route as a placeholder (shell screenshots and navigation tests run without Hilt). */
fun EntryProviderScope<Route>.shellPreviewEntries() {
    entry<Route.Photos>(metadata = EntryInsets.Tabs) { Placeholder("Fotos") }
    entry<Route.Files>(metadata = EntryInsets.Tabs) { Placeholder("Archivos") }
    entry<Route.Collections>(metadata = EntryInsets.Tabs) { Placeholder("Colecciones") }
}

/** Placeholder until the destination's feature agent (Stage 21) lands; [name] is a developer label. */
@Composable
fun Placeholder(name: String) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(
            text = stringResource(StringsR.string.shell_placeholder_destination, name),
            color = BentoTheme.colors.inkMuted,
            style = BentoTheme.typography.sectionTitle,
            modifier = Modifier.semantics { heading() }
        )
    }
}
