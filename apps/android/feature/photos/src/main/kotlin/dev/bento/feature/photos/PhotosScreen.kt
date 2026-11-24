package dev.bento.feature.photos

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibilityScope
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.paging.LoadState
import androidx.paging.compose.collectAsLazyPagingItems
import dev.bento.data.TimelineLayout
import dev.bento.designsystem.component.AttentionCard
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoSnackbarHost
import dev.bento.designsystem.component.BentoSnackbarHostState
import dev.bento.designsystem.component.BentoTopBar
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.EmptyState
import dev.bento.designsystem.component.ErrorState
import dev.bento.designsystem.component.FloatingActionBar
import dev.bento.designsystem.component.LoadingState
import dev.bento.designsystem.component.StatusAvatar
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.strings.R as StringsR
import kotlinx.coroutines.launch

/** Navigation out of Fotos (wired by the app's nav graph). */
class PhotosNavigation(
    /** Opens the viewer on the timeline at photo [position] (the shared element flies from the tile). */
    val openViewer: (assetId: String, position: Int) -> Unit,
    val openSearch: () -> Unit,
    val openAccount: () -> Unit,
    val openBackupSettings: () -> Unit,
    val openRecoveryKit: () -> Unit,
    val reconnect: () -> Unit
)

/** What the grid area shows (product/android.md §1.1: cached first, never a spinner when something is cached). */
enum class PhotosLoad { Live, Cached, FirstRun, Empty, Error }

// State wiring for the screen (cached vs live vs empty); the decisions are in PhotosContent and PhotosCards.
@Suppress("CyclomaticComplexMethod", "LongMethod")
@Composable
fun PhotosRoute(navigation: PhotosNavigation, animatedScope: AnimatedVisibilityScope? = null) {
    val vm: PhotosViewModel = hiltViewModel()
    val items = vm.cells.collectAsLazyPagingItems()
    val monthItems = vm.monthCells.collectAsLazyPagingItems()
    val cached by vm.cached.collectAsStateWithLifecycle()
    val layout by vm.layout.collectAsStateWithLifecycle()
    val density by vm.density.collectAsStateWithLifecycle()
    val card by vm.card.collectAsStateWithLifecycle()
    val account by vm.account.collectAsStateWithLifecycle()
    val busy by vm.actions.busy.collectAsStateWithLifecycle()
    val message by vm.messages.collectAsStateWithLifecycle()

    val live = remember(items) { PagingMediaCells(items) }
    val liveMonth = remember(monthItems) { PagingMediaCells(monthItems) }
    val cachedCells = remember(cached) { cached?.let { ListMediaCells(cellsOf(it)) } }
    val cachedMonth = remember(cached) { cached?.let { ListMediaCells(cellsOf(it, dayHeaders = false)) } }
    val refresh = items.loadState.refresh
    val load = when {
        items.itemCount > 0 -> PhotosLoad.Live
        cached == null -> PhotosLoad.FirstRun.takeIf { refresh is LoadState.Loading } ?: PhotosLoad.Cached
        cached!!.isNotEmpty() -> PhotosLoad.Cached
        refresh is LoadState.NotLoading -> PhotosLoad.Empty
        refresh is LoadState.Error -> PhotosLoad.Error
        else -> PhotosLoad.FirstRun
    }
    val gridState = remember { MediaGridState(density) }
    // Back from the viewer: make sure the tile of the last viewed photo is on screen before the shared element lands.
    val returned = remember { arrayOf(vm.sessions.consumeReturn()) }
    androidx.compose.runtime.SideEffect {
        val back = returned[0] ?: return@SideEffect
        if (load != PhotosLoad.Live) return@SideEffect
        returned[0] = null
        val grid = gridState.current
        val index = live.positions().indexOf(back.position)
        val visible = grid.layoutInfo.visibleItemsInfo.any { (it.key as? String) == "asset:${back.assetId}" }
        if (!visible && index >= 0) grid.requestScrollToItem(index + (if (card != null) 1 else 0))
    }
    LaunchedEffect(density) { if (gridState.density != density) gridState.changeDensity(density, null) }
    LaunchedEffect(gridState.density) { vm.setDensity(gridState.density) }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia()) { vm.upload(it) }
    val snackbar = remember { BentoSnackbarHostState() }
    val context = LocalContext.current
    LaunchedEffect(message) {
        message?.let {
            vm.messageShown()
            snackbar.show(it.resolve(context))
        }
    }

    CompositionLocalProvider(LocalBentoImageLoader provides vm.imageLoader) {
        PhotosContent(
            load = load,
            cellsFor = { d ->
                when {
                    load == PhotosLoad.Live -> if (d.dayHeaders) live else liveMonth
                    else -> (if (d.dayHeaders) cachedCells else cachedMonth) ?: ListMediaCells(emptyList())
                }
            },
            layout = layout.takeIf { load == PhotosLoad.Live && it.total > 0 },
            gridState = gridState,
            card = card,
            account = account,
            actions = vm.actions,
            snackbar = snackbar,
            busy = busy,
            navigation = navigation,
            onJump = vm::jumpTo,
            onRetry = { items.retry() },
            onUpload = { picker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageAndVideo)) },
            onDismissBackupCard = vm::dismissBackupCard,
            animatedScope = animatedScope
        )
    }
}

@Suppress("LongMethod", "LongParameterList", "CyclomaticComplexMethod")
@Composable
fun PhotosContent(
    load: PhotosLoad,
    cellsFor: (GridDensity) -> MediaCells,
    layout: TimelineLayout?,
    gridState: MediaGridState,
    card: PhotosCard?,
    account: AccountSummary,
    actions: MediaActions?,
    snackbar: BentoSnackbarHostState,
    busy: Boolean,
    navigation: PhotosNavigation,
    onJump: (Int) -> Unit,
    onRetry: () -> Unit,
    onUpload: () -> Unit,
    onDismissBackupCard: () -> Unit,
    modifier: Modifier = Modifier,
    selection: SelectionState = remember { SelectionState() },
    animatedScope: AnimatedVisibilityScope? = null
) {
    val c = BentoTheme.colors
    var sheet by rememberSheetState()
    val scope = rememberCoroutineScope()
    if (actions != null) {
        MediaEventsEffect(actions, snackbar, onSheet = { sheet = it }, onTrashed = { ids ->
            selection.set(
                selection.selected.values.filter {
                    it.id in
                        ids
                },
                false
            )
        })
    }
    BackHandler(enabled = selection.active) { selection.clear() }
    TrackJank("Fotos", gridState.current.isScrollInProgress)

    Box(modifier.fillMaxSize().background(c.surface)) {
        Column(Modifier.fillMaxSize()) {
            if (selection.active) {
                SelectionTopBar(
                    count = selection.count,
                    onClose = selection::clear,
                    onSelectAll = {
                        val cells = cellsFor(gridState.density)
                        selection.set((0 until cells.count).mapNotNull { (cells.peek(it) as? GridCell.Media)?.asset }, true)
                    }
                )
            } else {
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
            }
            Box(Modifier.weight(1f).fillMaxWidth()) {
                when (load) {
                    PhotosLoad.FirstRun -> LoadingState(Modifier.align(Alignment.Center))

                    PhotosLoad.Error -> ErrorState(
                        body = stringResource(StringsR.string.photos_error_load),
                        onRetry = onRetry,
                        modifier = Modifier.align(Alignment.Center).padding(24.dp)
                    )

                    PhotosLoad.Empty -> Column(Modifier.fillMaxSize()) {
                        card?.let { PhotosCardView(it, navigation, onDismissBackupCard) }
                        EmptyState(
                            title = stringResource(StringsR.string.photos_empty_title),
                            body = stringResource(StringsR.string.photos_empty_body),
                            icon = BentoIcons.Images,
                            modifier = Modifier.fillMaxWidth().weight(1f).padding(24.dp)
                        ) {
                            Column {
                                BentoButton(
                                    stringResource(StringsR.string.photos_empty_backup),
                                    navigation.openBackupSettings,
                                    variant = BentoButtonVariant.Primary,
                                    leadingIcon = BentoIcons.Smartphone,
                                    modifier = Modifier.fillMaxWidth()
                                )
                                BentoButton(
                                    stringResource(StringsR.string.photos_empty_upload),
                                    onUpload,
                                    variant = BentoButtonVariant.Secondary,
                                    leadingIcon = BentoIcons.Upload,
                                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp)
                                )
                            }
                        }
                    }

                    PhotosLoad.Live, PhotosLoad.Cached -> MediaGrid(
                        cellsFor = cellsFor,
                        state = gridState,
                        selection = selection,
                        layout = layout,
                        animatedScope = animatedScope,
                        contentPadding = PaddingValues(bottom = if (selection.active) 96.dp else 16.dp),
                        top = card?.let { { PhotosCardView(it, navigation, onDismissBackupCard) } },
                        callbacks = MediaGridCallbacks(
                            onOpen = { cell, position -> navigation.openViewer(cell.asset.id, position) },
                            onFavorite = actions?.let { a -> { asset -> a.favorite(listOf(asset), !asset.favorite) } },
                            onShare = actions?.let { a -> { asset -> a.export(Disclosure.Share) { a.share(listOf(asset)) } } },
                            onDelete = actions?.let { a -> { asset -> a.trash(listOf(asset.id)) } },
                            onJump = onJump.takeIf { load == PhotosLoad.Live },
                            onDeleteSelection = actions?.let { a -> { a.trash(selection.selected.keys.toList()) } }
                        )
                    )
                }
            }
        }

        Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth()) {
            BentoSnackbarHost(snackbar, Modifier.fillMaxWidth())
            if (busy) {
                dev.bento.designsystem.component.ProgressBar(
                    progress = null,
                    label = stringResource(StringsR.string.photos_preparing_copy),
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp)
                )
            }
            if (actions != null) {
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
                        sendTelegram = { sheet = MediaSheet.Telegram(selected) }
                    )
                )
                FloatingActionBar(
                    visible = selection.active,
                    actions = primary,
                    overflow = overflow,
                    onClose = selection::clear,
                    title = pluralStringResource(StringsR.plurals.common_count_selected, selection.count, selection.count)
                )
            }
        }
    }
    if (actions != null) {
        MediaSheetHost(sheet, actions, onClose = { sheet = null }, onDone = { scope.launch { selection.clear() } })
    }
}

/** The one card at the top of the grid (product/android.md §4.3): one action and a dismiss where it can wait. */
@Composable
fun PhotosCardView(card: PhotosCard, navigation: PhotosNavigation, onDismissBackup: () -> Unit) {
    val modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp)
    when (card) {
        PhotosCard.SignInNeeded -> AttentionCard(
            title = stringResource(StringsR.string.common_error_session_revoked),
            body = stringResource(StringsR.string.photos_card_signin_body),
            actionLabel = stringResource(StringsR.string.common_action_reconnect),
            onAction = navigation.reconnect,
            tone = CalloutTone.Warning,
            icon = BentoIcons.CloudOff,
            modifier = modifier
        )

        PhotosCard.KitPending -> AttentionCard(
            title = stringResource(StringsR.string.photos_card_kit_title),
            body = stringResource(StringsR.string.photos_card_kit_body),
            actionLabel = stringResource(StringsR.string.photos_card_kit_action),
            onAction = navigation.openRecoveryKit,
            tone = CalloutTone.Warning,
            icon = BentoIcons.Lock,
            modifier = modifier
        )

        is PhotosCard.PartialAccess -> AttentionCard(
            title = pluralStringResource(StringsR.plurals.photos_card_partial_title, card.visible, card.visible),
            body = stringResource(StringsR.string.photos_card_partial_body),
            actionLabel = stringResource(StringsR.string.photos_card_partial_action),
            onAction = navigation.openBackupSettings,
            icon = BentoIcons.Images,
            modifier = modifier
        )

        PhotosCard.BackupOff -> AttentionCard(
            title = stringResource(StringsR.string.photos_card_backup_title),
            body = stringResource(StringsR.string.photos_card_backup_body),
            actionLabel = stringResource(StringsR.string.photos_card_backup_action),
            onAction = navigation.openBackupSettings,
            icon = BentoIcons.CloudUpload,
            onDismiss = onDismissBackup,
            modifier = modifier
        )
    }
}
