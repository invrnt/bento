package dev.bento.app.navigation

import androidx.compose.runtime.Composable
import dev.bento.feature.files.FilesScreen
import dev.bento.feature.search.SearchScreen

/** Navigation glue for agent 40's destinations: features expose callbacks, the shell decides where they lead. */
@Composable
internal fun FilesDestination(navigator: Navigator, key: Route.Files) {
    FilesScreen(
        folderId = key.folderId,
        onOpenViewer = { navigator.navigate(Route.Viewer(it)) },
        onOpenDocument = { navigator.navigate(Route.Document(it)) },
        onSearch = { folderId, folderName -> navigator.navigate(Route.Search(folderId = folderId, folderName = folderName)) },
        onAccount = { navigator.navigate(Route.Activity) },
        // The real status avatar opening Cuenta y actividad (agent 41).
        avatar = { AccountAvatarFor(navigator) }
    )
}

@Composable
internal fun SearchDestination(navigator: Navigator, key: Route.Search) {
    SearchScreen(
        query = key.query,
        scopeFolderId = key.folderId,
        scopeFolderName = key.folderName,
        onBack = { navigator.back() },
        onOpenViewer = { navigator.navigate(Route.Viewer(it)) },
        onOpenDocument = { navigator.navigate(Route.Document(it)) },
        onOpenFolder = { navigator.navigate(Route.Files(it)) },
        onOpenAlbum = { navigator.navigate(Route.Album(it)) }
    )
}
