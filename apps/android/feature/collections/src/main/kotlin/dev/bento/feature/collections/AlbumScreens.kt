package dev.bento.feature.collections

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.paging.LoadState
import androidx.paging.compose.collectAsLazyPagingItems
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoSheet
import dev.bento.designsystem.component.BentoSnackbarHost
import dev.bento.designsystem.component.BentoSnackbarHostState
import dev.bento.designsystem.component.BentoTextField
import dev.bento.designsystem.component.EmptyState
import dev.bento.designsystem.component.ErrorState
import dev.bento.designsystem.component.FloatingActionBar
import dev.bento.designsystem.component.LoadingState
import dev.bento.designsystem.format.pluralCountResource
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.photos.Disclosure
import dev.bento.feature.photos.GridDensity
import dev.bento.feature.photos.ListMediaCells
import dev.bento.feature.photos.LocalBentoImageLoader
import dev.bento.feature.photos.MediaActions
import dev.bento.feature.photos.MediaCells
import dev.bento.feature.photos.MediaEventsEffect
import dev.bento.feature.photos.MediaGrid
import dev.bento.feature.photos.MediaGridCallbacks
import dev.bento.feature.photos.MediaGridState
import dev.bento.feature.photos.MediaSheet
import dev.bento.feature.photos.MediaSheetHost
import dev.bento.feature.photos.PagingMediaCells
import dev.bento.feature.photos.SelectionHandlers
import dev.bento.feature.photos.SelectionState
import dev.bento.feature.photos.SelectionTopBar
import dev.bento.feature.photos.ViewerSessions
import dev.bento.feature.photos.ViewerSource
import dev.bento.feature.photos.cellsOf
import dev.bento.feature.photos.selectionActions
import dev.bento.strings.R as StringsR
import kotlinx.coroutines.launch

/**
 * A titled media grid with selection, the floating action bar and undo: album detail, Favoritos, Videos.
 * [empty] renders when there is nothing to show.
 */
@Suppress("LongMethod", "LongParameterList")
@Composable
fun CollectionGridScreen(
    title: String,
    cellsFor: (GridDensity) -> MediaCells,
    isEmpty: Boolean,
    loading: Boolean,
    failed: Boolean,
    actions: MediaActions,
    onBack: () -> Unit,
    onOpen: (assetId: String, position: Int) -> Unit,
    onRetry: () -> Unit,
    empty: @Composable () -> Unit,
    modifier: Modifier = Modifier,
    bottomAction: (@Composable () -> Unit)? = null,
    onRemoveFromAlbum: ((List<String>) -> Unit)? = null,
    onSetCover: ((String) -> Unit)? = null,
    topActions: @Composable RowScope.() -> Unit = {},
    snackbar: BentoSnackbarHostState = remember { BentoSnackbarHostState() }
) {
    val c = BentoTheme.colors
    val selection = remember { SelectionState() }
    val gridState = remember { MediaGridState() }
    var sheet by remember { mutableStateOf<MediaSheet?>(null) }
    val scope = rememberCoroutineScope()
    MediaEventsEffect(actions, snackbar, onSheet = { sheet = it })
    BackHandler(enabled = selection.active) { selection.clear() }
    Box(modifier.fillMaxSize().background(c.surface)) {
        Column(Modifier.fillMaxSize()) {
            if (selection.active) {
                SelectionTopBar(selection.count, selection::clear, onSelectAll = {
                    val cells = cellsFor(gridState.density)
                    selection.set(
                        (0 until cells.count).mapNotNull {
                            (cells.peek(it) as? dev.bento.feature.photos.GridCell.Media)?.asset
                        },
                        true
                    )
                })
            } else {
                CollectionTopBar(title, onBack, actions = topActions)
            }
            Box(Modifier.weight(1f).fillMaxWidth()) {
                when {
                    loading -> LoadingState(Modifier.align(Alignment.Center))

                    failed -> ErrorState(
                        stringResource(StringsR.string.collections_album_error),
                        Modifier.align(Alignment.Center).padding(24.dp),
                        onRetry = onRetry
                    )

                    isEmpty -> empty()

                    else -> MediaGrid(
                        cellsFor = cellsFor,
                        state = gridState,
                        selection = selection,
                        contentPadding = PaddingValues(bottom = 96.dp),
                        callbacks = MediaGridCallbacks(
                            onOpen = { cell, position -> onOpen(cell.asset.id, position) },
                            onFavorite = { asset -> actions.favorite(listOf(asset), !asset.favorite) },
                            onShare = { asset -> actions.export(Disclosure.Share) { actions.share(listOf(asset)) } },
                            onDelete = { asset -> actions.trash(listOf(asset.id)) },
                            onDeleteSelection = { actions.trash(selection.selected.keys.toList()) }
                        )
                    )
                }
            }
        }
        Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth()) {
            BentoSnackbarHost(snackbar, Modifier.fillMaxWidth())
            if (!selection.active && bottomAction != null) {
                Box(Modifier.fillMaxWidth().padding(16.dp), contentAlignment = Alignment.CenterEnd) { bottomAction() }
            }
            val selected = selection.selected.values.toList()
            val (primary, overflow) = selectionActions(
                selected,
                SelectionHandlers(
                    share = { actions.export(Disclosure.Share) { actions.share(selected) } },
                    addToAlbum = { sheet = MediaSheet.AddToAlbum(selected.map { it.id }) },
                    favorite = {
                        val all = selected.all { it.favorite }
                        actions.favorite(selected, !all)
                        selection.set(selected.map { it.copy(favorite = !all) }, true)
                    },
                    delete = {
                        actions.trash(selected.map { it.id })
                        selection.clear()
                    },
                    move = { sheet = MediaSheet.Move(selected) },
                    saveToPhone = { actions.export(Disclosure.SaveToPhone) { actions.saveToPhone(selected) } },
                    sendTelegram = { sheet = MediaSheet.Telegram(selected) },
                    removeFromAlbum = onRemoveFromAlbum?.let { remove ->
                        {
                            remove(selected.map { it.id })
                            selection.clear()
                        }
                    },
                    setCover = onSetCover?.let { set ->
                        {
                            selected.singleOrNull()?.let { set(it.id) }
                            selection.clear()
                        }
                    }
                )
            )
            FloatingActionBar(
                visible = selection.active,
                actions = primary,
                overflow = overflow,
                onClose = selection::clear
            )
        }
    }
    MediaSheetHost(sheet, actions, onClose = { sheet = null }, onDone = { scope.launch { selection.clear() } })
}

/** Album messages as snackbars; a deleted album leaves the screen. */
@Composable
private fun AlbumEffects(vm: AlbumViewModel, snackbar: BentoSnackbarHostState, navigation: CollectionsNavigation) {
    val message by vm.message.collectAsStateWithLifecycle()
    val deleted by vm.deleted.collectAsStateWithLifecycle()
    val resolved = message?.resolve()
    LaunchedEffect(resolved) {
        if (resolved != null) {
            vm.messageShown()
            snackbar.show(resolved)
        }
    }
    LaunchedEffect(deleted) { if (deleted) navigation.back() }
}

@Composable
fun AlbumRoute(albumId: String, navigation: CollectionsNavigation) {
    val vm = hiltViewModel<AlbumViewModel, AlbumViewModel.Factory>(key = "album:$albumId") { it.create(albumId) }
    val state by vm.state.collectAsStateWithLifecycle()
    val snackbar = remember { BentoSnackbarHostState() }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val undoLabel = stringResource(StringsR.string.common_action_undo)
    val ready = (state as? Loadable.Ready)?.value
    val dialog by vm.dialog.collectAsStateWithLifecycle()
    val busy by vm.busy.collectAsStateWithLifecycle()
    AlbumEffects(vm, snackbar, navigation)
    val cells = remember(ready) { ListMediaCells(cellsOf(ready?.assets.orEmpty())) }
    val monthCells = remember(ready) { ListMediaCells(cellsOf(ready?.assets.orEmpty(), dayHeaders = false)) }
    CompositionLocalProvider(LocalBentoImageLoader provides vm.imageLoader) {
        CollectionGridScreen(
            title = ready?.album?.title.orEmpty(),
            cellsFor = { if (it.dayHeaders) cells else monthCells },
            isEmpty = ready?.assets?.isEmpty() == true,
            loading = state is Loadable.Loading,
            failed = state is Loadable.Failed,
            actions = vm.actions,
            snackbar = snackbar,
            onBack = navigation.back,
            onOpen = { id, position ->
                val assets = ready?.assets.orEmpty()
                assets.firstOrNull { it.id == id }?.let(vm.sessions::open)
                navigation.openViewer(id, position, vm.sessions.register(ViewerSource.Snapshot(assets)))
            },
            onRetry = vm::load,
            onRemoveFromAlbum = { ids ->
                vm.remove(ids) { message, undo ->
                    scope.launch { if (snackbar.showUndo(message.resolve(context), undoLabel)) undo.undo() }
                }
            },
            onSetCover = vm::setCover,
            topActions = {
                if (ready != null) {
                    AlbumMenu(onRename = { vm.showDialog(AlbumDialog.Rename) }, onDelete = { vm.showDialog(AlbumDialog.Delete) })
                }
            },
            bottomAction = {
                dev.bento.designsystem.component.BentoFab(
                    text = stringResource(StringsR.string.collections_album_add_photos),
                    icon = BentoIcons.ImagePlus,
                    onClick = { navigation.addToAlbum(albumId) }
                )
            },
            empty = {
                EmptyState(
                    title = stringResource(StringsR.string.collections_album_empty_title),
                    body = stringResource(StringsR.string.collections_album_empty_body),
                    icon = BentoIcons.SquareLibrary,
                    modifier = Modifier.fillMaxSize().padding(24.dp)
                ) {
                    BentoButton(
                        stringResource(StringsR.string.collections_album_add_photos),
                        { navigation.addToAlbum(albumId) },
                        variant = BentoButtonVariant.Primary,
                        leadingIcon = BentoIcons.ImagePlus
                    )
                }
            }
        )
    }
    if (ready != null) {
        when (dialog) {
            AlbumDialog.Rename -> AlbumRenameSheet(ready.album.title, busy, onSave = vm::rename, onDismiss = { vm.showDialog(null) })
            AlbumDialog.Delete -> AlbumDeleteDialog(ready.album.title, onConfirm = vm::delete, onDismiss = { vm.showDialog(null) })
            null -> Unit
        }
    }
}

/**
 * The library as a picker (Nuevo álbum, Añadir fotos): taps select, `Siguiente` asks for the album name (new album) or
 * adds to [albumId] directly.
 */
@Suppress("LongMethod")
@Composable
fun LibraryPickerRoute(albumId: String?, albumTitle: String?, navigation: CollectionsNavigation, onCreated: (String?) -> Unit) {
    val vm: LibraryPickerViewModel = hiltViewModel()
    val items = vm.cells.collectAsLazyPagingItems()
    val monthItems = vm.monthCells.collectAsLazyPagingItems()
    val layout by vm.layout.collectAsStateWithLifecycle()
    val live = remember(items) { PagingMediaCells(items) }
    val liveMonth = remember(monthItems) { PagingMediaCells(monthItems) }
    val selection = remember { SelectionState() }
    val gridState = remember { MediaGridState() }
    var naming by remember { mutableStateOf(false) }
    val c = BentoTheme.colors
    CompositionLocalProvider(LocalBentoImageLoader provides vm.imageLoader) {
        Box(Modifier.fillMaxSize().background(c.surface)) {
            Column(Modifier.fillMaxSize()) {
                CollectionTopBar(
                    title = if (selection.active) {
                        pluralCountResource(StringsR.plurals.common_count_selected, selection.count)
                    } else {
                        stringResource(StringsR.string.collections_picker_title)
                    },
                    onBack = navigation.back
                )
                Box(Modifier.weight(1f)) {
                    if (items.itemCount == 0 && items.loadState.refresh is LoadState.Loading) {
                        LoadingState(Modifier.align(Alignment.Center))
                    } else {
                        MediaGrid(
                            cellsFor = { if (it.dayHeaders) live else liveMonth },
                            state = gridState,
                            selection = selection,
                            layout = layout.takeIf { it.total > 0 },
                            pickMode = true,
                            contentPadding = PaddingValues(bottom = 96.dp),
                            callbacks = MediaGridCallbacks(onOpen = { cell, _ -> selection.toggle(cell.asset) }, onJump = vm::jumpTo)
                        )
                    }
                }
            }
            BentoButton(
                text = stringResource(
                    if (albumId ==
                        null
                    ) {
                        StringsR.string.collections_picker_next
                    } else {
                        StringsR.string.collections_picker_done
                    }
                ),
                onClick = {
                    if (albumId == null) {
                        naming = true
                    } else {
                        vm.actions.addToAlbum(albumId, albumTitle.orEmpty(), selection.selected.keys.toList())
                        onCreated(albumId)
                    }
                },
                enabled = selection.active,
                variant = BentoButtonVariant.Primary,
                modifier = Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(16.dp)
            )
        }
    }
    if (naming) {
        val name = rememberTextFieldState()
        var error by remember { mutableStateOf<String?>(null) }
        val missing = stringResource(StringsR.string.collections_create_name_error)
        BentoSheet(onDismissRequest = { naming = false }, title = stringResource(StringsR.string.collections_new_album)) {
            BentoTextField(
                state = name,
                label = stringResource(StringsR.string.collections_create_title),
                placeholder = stringResource(StringsR.string.photos_album_name_hint),
                error = error,
                modifier = Modifier.fillMaxWidth()
            )
            BentoButton(
                stringResource(StringsR.string.collections_create_action),
                {
                    val title = name.text.toString().trim()
                    if (title.isEmpty()) {
                        error = missing
                    } else {
                        vm.actions.createAlbum(title, selection.selected.keys.toList())
                        naming = false
                        onCreated(null)
                    }
                },
                variant = BentoButtonVariant.Primary,
                modifier = Modifier.fillMaxWidth().padding(top = 12.dp)
            )
        }
    }
}

/** Favoritos / Videos. */
@Composable
fun FilteredRoute(filter: MediaFilter, navigation: CollectionsNavigation) {
    val vm = hiltViewModel<FilteredViewModel, FilteredViewModel.Factory>(key = "filtered:$filter") { it.create(filter) }
    val items = vm.cells.collectAsLazyPagingItems()
    val monthItems = vm.monthCells.collectAsLazyPagingItems()
    val live = remember(items) { PagingMediaCells(items) }
    val liveMonth = remember(monthItems) { PagingMediaCells(monthItems) }
    val refresh = items.loadState.refresh
    val favorites = filter == MediaFilter.Favorites
    CompositionLocalProvider(LocalBentoImageLoader provides vm.imageLoader) {
        CollectionGridScreen(
            title = stringResource(if (favorites) StringsR.string.collections_favorites else StringsR.string.collections_videos),
            cellsFor = { if (it.dayHeaders) live else liveMonth },
            isEmpty = items.itemCount == 0 && refresh is LoadState.NotLoading,
            loading = items.itemCount == 0 && refresh is LoadState.Loading,
            failed = items.itemCount == 0 && refresh is LoadState.Error,
            actions = vm.actions,
            onBack = navigation.back,
            onOpen = { id, position -> openFromSnapshot(vm.sessions, live, id, position, navigation) },
            onRetry = { items.retry() },
            empty = {
                EmptyState(
                    title = stringResource(
                        if (favorites) StringsR.string.collections_favorites_empty_title else StringsR.string.collections_videos_empty_title
                    ),
                    body = stringResource(
                        if (favorites) StringsR.string.collections_favorites_empty_body else StringsR.string.collections_videos_empty_body
                    ),
                    icon = if (favorites) BentoIcons.Heart else BentoIcons.Video,
                    modifier = Modifier.fillMaxSize().padding(24.dp)
                )
            }
        )
    }
}

/** Opens the viewer over the collection's loaded items (a snapshot; paging continues in the grid). */
internal fun openFromSnapshot(sessions: ViewerSessions, cells: MediaCells, id: String, position: Int, navigation: CollectionsNavigation) {
    val assets = (0 until cells.count).mapNotNull { (cells.peek(it) as? dev.bento.feature.photos.GridCell.Media)?.asset }
    assets.firstOrNull { it.id == id }?.let(sessions::open)
    navigation.openViewer(id, position, sessions.register(ViewerSource.Snapshot(assets)))
}
