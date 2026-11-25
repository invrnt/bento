package dev.bento.feature.collections

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.paging.LoadState
import androidx.paging.compose.collectAsLazyPagingItems
import dev.bento.api.generated.AlbumResponse
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.BentoIconButton
import dev.bento.designsystem.component.BentoTopBar
import dev.bento.designsystem.component.EmptyState
import dev.bento.designsystem.component.ListRow
import dev.bento.designsystem.component.SectionHeader
import dev.bento.designsystem.component.StatusAvatar
import dev.bento.designsystem.format.pluralCountResource
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.photos.AccountSummary
import dev.bento.feature.photos.AlbumCover
import dev.bento.feature.photos.LocalBentoImageLoader
import dev.bento.strings.R as StringsR

/** Navigation out of Colecciones (wired by the app's nav graph). */
class CollectionsNavigation(
    val back: () -> Unit,
    val openSearch: () -> Unit,
    val openAccount: () -> Unit,
    val openAlbum: (String) -> Unit,
    val newAlbum: () -> Unit,
    val addToAlbum: (String) -> Unit,
    val openFavorites: () -> Unit,
    val openVideos: () -> Unit,
    val openDocuments: () -> Unit,
    val openPhone: () -> Unit,
    val openTelegram: () -> Unit,
    val openTelegramChats: () -> Unit,
    val openTelegramChat: (Long, String) -> Unit,
    val openTrash: () -> Unit,
    val openBackupSettings: () -> Unit,
    /** Opens the viewer on a registered session (token) at [position]. */
    val openViewer: (assetId: String, position: Int, session: String?) -> Unit
)

object CollectionsTestTags {
    const val Hub = "collections:hub"
    const val TrashList = "collections:trash"
    const val AlbumMenu = "collections:album-menu"
    fun album(id: String) = "collections:album:$id"
}

@Composable
fun CollectionsRoute(navigation: CollectionsNavigation) {
    val vm: CollectionsViewModel = hiltViewModel()
    val albums = vm.albums.collectAsLazyPagingItems()
    val account by vm.account.collectAsStateWithLifecycle()
    val list = (0 until albums.itemCount).mapNotNull { albums.peek(it) }
    CompositionLocalProvider(LocalBentoImageLoader provides vm.imageLoader) {
        CollectionsContent(
            albums = list,
            albumsLoading = albums.loadState.refresh is LoadState.Loading && albums.itemCount == 0,
            account = account,
            navigation = navigation,
            onAlbumVisible = { index -> if (index < albums.itemCount) albums[index] }
        )
    }
}

/**
 * Colecciones (product/android.md §4.8): the library rows (Favoritos, Videos, Documentos, Del teléfono,
 * Importado de Telegram, Papelera), then Álbumes as a 2-column grid of 4:3 covers with title and count.
 */
@Suppress("LongMethod")
@Composable
fun CollectionsContent(
    albums: List<AlbumResponse>,
    albumsLoading: Boolean,
    account: AccountSummary,
    navigation: CollectionsNavigation,
    modifier: Modifier = Modifier,
    onAlbumVisible: (Int) -> Unit = {}
) {
    val c = BentoTheme.colors
    Column(modifier.fillMaxSize().background(c.surface)) {
        BentoTopBar(
            searchLabel = stringResource(StringsR.string.common_action_search_bento),
            onSearchClick = navigation.openSearch,
            avatar = {
                StatusAvatar(
                    name = account.name ?: stringResource(StringsR.string.photos_avatar_fallback),
                    status = account.status,
                    onClick = navigation.openAccount
                )
            }
        )
        LazyVerticalGrid(
            columns = GridCells.Adaptive(minSize = 160.dp),
            contentPadding = PaddingValues(start = 12.dp, end = 12.dp, bottom = 24.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
            modifier = Modifier.fillMaxSize().testTag(CollectionsTestTags.Hub)
        ) {
            fullLine("library-title") { HubHeading(stringResource(StringsR.string.collections_library)) }
            fullLine("favorites") {
                HubRow(
                    BentoIcons.Heart,
                    StringsR.string.collections_favorites,
                    StringsR.string.collections_favorites_summary,
                    navigation.openFavorites
                )
            }
            fullLine("videos") {
                HubRow(
                    BentoIcons.Video,
                    StringsR.string.collections_videos,
                    StringsR.string.collections_videos_summary,
                    navigation.openVideos
                )
            }
            fullLine("documents") {
                HubRow(
                    BentoIcons.FileText,
                    StringsR.string.collections_documents,
                    StringsR.string.collections_documents_summary,
                    navigation.openDocuments
                )
            }
            fullLine("phone") {
                HubRow(
                    BentoIcons.Smartphone,
                    StringsR.string.collections_phone,
                    StringsR.string.collections_phone_summary,
                    navigation.openPhone
                )
            }
            fullLine("telegram") {
                HubRow(
                    BentoIcons.Send,
                    StringsR.string.collections_telegram,
                    StringsR.string.collections_telegram_summary,
                    navigation.openTelegram
                )
            }
            fullLine("trash") {
                HubRow(
                    BentoIcons.Trash2,
                    StringsR.string.collections_trash,
                    StringsR.string.collections_trash_summary,
                    navigation.openTrash
                )
            }
            fullLine("albums-title") {
                SectionHeader(
                    title = stringResource(StringsR.string.collections_albums),
                    actionLabel = stringResource(StringsR.string.collections_new_album),
                    onAction = navigation.newAlbum,
                    modifier = Modifier.padding(top = 16.dp)
                )
            }
            if (albums.isEmpty() && !albumsLoading) {
                fullLine("albums-empty") {
                    EmptyState(
                        title = stringResource(StringsR.string.collections_albums_empty_title),
                        body = stringResource(StringsR.string.collections_albums_empty_body),
                        icon = BentoIcons.SquareLibrary,
                        compact = true,
                        modifier = Modifier.fillMaxWidth().padding(vertical = 16.dp)
                    ) {
                        dev.bento.designsystem.component.BentoButton(
                            stringResource(StringsR.string.collections_new_album),
                            navigation.newAlbum,
                            leadingIcon = BentoIcons.Plus
                        )
                    }
                }
            }
            items(albums.size, key = { albums[it].id }) { index ->
                onAlbumVisible(index)
                AlbumCard(albums[index], onClick = { navigation.openAlbum(albums[index].id) })
            }
        }
    }
}

private fun androidx.compose.foundation.lazy.grid.LazyGridScope.fullLine(key: String, content: @Composable () -> Unit) =
    item(key = key, span = { GridItemSpan(maxLineSpan) }) { content() }

@Composable
private fun HubHeading(text: String) {
    Text(
        text,
        color = BentoTheme.colors.ink,
        style = BentoTheme.typography.pageTitle,
        modifier = Modifier.padding(start = 4.dp, top = 8.dp, bottom = 4.dp).semantics { heading() }
    )
}

@Composable
private fun HubRow(icon: ImageVector, title: Int, summary: Int, onClick: () -> Unit) {
    val c = BentoTheme.colors
    ListRow(
        headline = stringResource(title),
        supporting = stringResource(summary),
        leading = {
            Box(Modifier.clip(BentoShapes.md).background(c.subtle).padding(10.dp)) {
                if (icon == BentoIcons.Heart) {
                    dev.bento.designsystem.component.BentoFavorite(true)
                } else {
                    BentoIcon(icon, null, tint = c.inkMuted)
                }
            }
        },
        trailing = { BentoIcon(BentoIcons.ChevronRight, null, tint = c.inkSubtle) },
        onClick = onClick
    )
}

/** 4:3 cover, title and count (product/android.md §4.8). */
@Composable
fun AlbumCard(album: AlbumResponse, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val c = BentoTheme.colors
    val count = album.assetIds.size
    Column(
        modifier
            .clip(BentoShapes.lg)
            .clickable(role = Role.Button, onClick = onClick)
            .padding(4.dp)
            .testTag(CollectionsTestTags.album(album.id))
            .semantics(mergeDescendants = true) {}
    ) {
        AlbumCover(album, Modifier.fillMaxWidth(), aspectRatio = 4f / 3f, sizePx = 512)
        Text(
            album.title,
            color = c.ink,
            style = BentoTheme.typography.labelStrong,
            maxLines = 1,
            modifier = Modifier.padding(top = 8.dp, start = 2.dp)
        )
        Text(
            pluralCountResource(StringsR.plurals.photos_album_count, count),
            color = c.inkMuted,
            style = BentoTheme.typography.metadata,
            modifier = Modifier.padding(start = 2.dp, bottom = 4.dp)
        )
    }
}

/** Top bar for collection sub-pages: back, title, optional actions (thumb-first: primary actions stay at the bottom). */
@Composable
fun CollectionTopBar(title: String, onBack: () -> Unit, modifier: Modifier = Modifier, actions: @Composable RowScope.() -> Unit = {}) {
    val c = BentoTheme.colors
    Row(
        modifier
            .fillMaxWidth()
            .background(c.surface)
            .heightIn(min = 64.dp)
            .padding(horizontal = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        BentoIconButton(BentoIcons.ArrowLeft, stringResource(StringsR.string.common_action_back), onBack)
        Text(
            title,
            color = c.ink,
            style = BentoTheme.typography.sectionTitle,
            maxLines = 1,
            modifier = Modifier.weight(1f).padding(start = 4.dp).semantics { heading() }
        )
        actions()
    }
}
