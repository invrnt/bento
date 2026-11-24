package dev.bento.app.navigation

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
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.strings.R as StringsR

/**
 * Screen registration: one `entry<Route.X> { … }` line per destination. Every entry is a PLACEHOLDER until
 * its feature agent (Stage 21) replaces the line with the real screen, for example:
 *
 * ```
 * entry<Route.Photos> { PhotosScreen(onOpen = { id -> navigator.navigate(Route.Viewer(id)) }) }
 * ```
 */
@Suppress("UNUSED_PARAMETER") // features use [navigator] in their callbacks
fun EntryProviderScope<Route>.bentoEntries(navigator: Navigator) {
    entry<Route.Photos> { Placeholder("Fotos") }
    entry<Route.Files> { key -> Placeholder("Archivos ${key.folderId.orEmpty()}") }
    entry<Route.Collections> { Placeholder("Colecciones") }
    entry<Route.Search> { Placeholder("Buscar") }
    entry<Route.Viewer> { key -> Placeholder("Visor ${key.assetId}") }
    entry<Route.Album> { key -> Placeholder("Álbum ${key.albumId}") }
    entry<Route.Trash> { Placeholder("Papelera") }
    entry<Route.Activity> { Placeholder("Actividad") }
    entry<Route.Settings> { Placeholder("Ajustes") }
    entry<Route.Devices> { Placeholder("Dispositivos") }
    entry<Route.Onboarding> { Placeholder("Bienvenida") }
    entry<Route.Join> { key -> Placeholder("Unirse ${key.code.orEmpty()}") }
    entry<Route.Recovery> { Placeholder("Recuperación") }
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
