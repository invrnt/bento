package dev.bento.feature.files

import android.app.Activity
import android.content.ClipData
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.MediaStore
import androidx.activity.compose.BackHandler
import androidx.activity.compose.LocalActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.draganddrop.dragAndDropTarget
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draganddrop.DragAndDropEvent
import androidx.compose.ui.draganddrop.DragAndDropTarget
import androidx.compose.ui.draganddrop.mimeTypes
import androidx.compose.ui.draganddrop.toAndroidDragEvent
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.isCtrlPressed
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.google.android.gms.common.ConnectionResult
import com.google.android.gms.common.GoogleApiAvailability
import com.google.mlkit.vision.documentscanner.GmsDocumentScannerOptions
import com.google.mlkit.vision.documentscanner.GmsDocumentScanning
import com.google.mlkit.vision.documentscanner.GmsDocumentScanningResult
import dev.bento.api.generated.DriveItemResponse
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoChip
import dev.bento.designsystem.component.BentoFab
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.BentoIconButton
import dev.bento.designsystem.component.BentoSheet
import dev.bento.designsystem.component.BentoSnackbarHost
import dev.bento.designsystem.component.BentoSnackbarHostState
import dev.bento.designsystem.component.BentoSnackbarTone
import dev.bento.designsystem.component.BentoTopBar
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.EmptyState
import dev.bento.designsystem.component.ErrorState
import dev.bento.designsystem.component.FileKind
import dev.bento.designsystem.component.FloatingAction
import dev.bento.designsystem.component.FloatingActionBar
import dev.bento.designsystem.component.KindIcon
import dev.bento.designsystem.component.ListRow
import dev.bento.designsystem.component.LoadingState
import dev.bento.designsystem.component.ProgressBar
import dev.bento.designsystem.format.formatCount
import dev.bento.designsystem.format.pluralCountResource
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.designsystem.trace.InteractionTrace
import dev.bento.feature.files.di.FilesEntryPoint
import dev.bento.strings.R as StringsR
import java.io.File
import java.time.LocalDateTime
import kotlinx.coroutines.delay

/** Everything Archivos can ask for; defaults make previews and tests terse. */
data class FilesActions(
    val onOpen: (DriveItemResponse) -> Unit = {},
    val onSelect: (DriveItemResponse) -> Unit = {},
    val onMenu: (DriveItemResponse) -> Unit = {},
    val onShare: (List<DriveItemResponse>) -> Unit = {},
    val onFavorite: (DriveItemResponse) -> Unit = {},
    val onTrash: (List<DriveItemResponse>) -> Unit = {},
    val onMove: (List<DriveItemResponse>) -> Unit = {},
    val onDownload: (List<DriveItemResponse>) -> Unit = {},
    val onPin: (List<DriveItemResponse>, Boolean) -> Unit = { _, _ -> },
    val onNavigate: (String?) -> Unit = {},
    val onRetry: () -> Unit = {},
    val onNew: () -> Unit = {},
    val onSort: () -> Unit = {},
    val onToggleLayout: () -> Unit = {},
    val onSearch: () -> Unit = {},
    val onSearchHere: () -> Unit = {},
    val onSelectAll: () -> Unit = {},
    val onClearSelection: () -> Unit = {},
    val onToggleTree: (String) -> Unit = {},
    val onDrop: (List<PickedContent>) -> Unit = {},
    val onPauseUploads: () -> Unit = {},
    val onResumeUploads: () -> Unit = {},
    val onDismissUploads: () -> Unit = {},
    val onToggleAudio: () -> Unit = {},
    val onCloseAudio: () -> Unit = {},
    val onCancelPreparing: () -> Unit = {}
)

/**
 * Archivos (product/android.md §4.5, §4.6): list by default (grid toggle), folders first, sort remembered per folder,
 * breadcrumbs, `+ Nuevo`, item menu, selection with a floating action bar, move sheet, offline pins, upload card,
 * list-detail (folder tree) at ≥ 840 dp, keyboard/mouse shortcuts and drag and drop in.
 */
@Composable
fun FilesScreen(
    folderId: String?,
    onOpenViewer: (String) -> Unit,
    onOpenDocument: (String) -> Unit,
    onSearch: (folderId: String?, folderName: String?) -> Unit,
    onAccount: () -> Unit,
    modifier: Modifier = Modifier,
    // The shell passes the status avatar (agent 41's `AccountAvatar`); the plain icon is only a fallback.
    avatar: (@Composable () -> Unit)? = null,
    viewModel: FilesViewModel = hiltViewModel()
) {
    val context = LocalContext.current
    val state by viewModel.state.collectAsStateWithLifecycle()
    if (!state.loading && state.items.isNotEmpty()) SideEffect { InteractionTrace.end(InteractionTrace.FILES_OPEN) }
    val uploads by viewModel.uploads.state.collectAsStateWithLifecycle()
    val audio by viewModel.audio.state.collectAsStateWithLifecycle()
    val snackbar = remember { BentoSnackbarHostState() }
    val entry = remember(context) { runCatching { FilesEntryPoint.get(context) }.getOrNull() }
    val launchers = rememberFilesLaunchers(viewModel, entry?.contentFiles())

    LaunchedEffect(folderId) { viewModel.start(folderId) }
    BackHandler(enabled = state.selecting || state.canGoUp) { if (state.selecting) viewModel.clearSelection() else viewModel.up() }
    FilesEffects(viewModel, snackbar, launchers, FilesNavigation(onOpenViewer, onOpenDocument, onSearch))
    LaunchedEffect(audio.playing) {
        while (audio.playing) {
            viewModel.audio.tick()
            delay(AUDIO_TICK_MS)
        }
    }
    val scanAvailable = remember(context) {
        GoogleApiAvailability.getInstance().isGooglePlayServicesAvailable(context) == ConnectionResult.SUCCESS
    }
    CompositionLocalProvider(LocalBentoImageLoader provides entry?.imageLoader()) {
        FilesContent(
            state = state,
            uploads = uploads,
            audio = audio,
            actions = filesActions(viewModel) { onSearch(null, null) },
            snackbar = snackbar,
            modifier = modifier,
            onLoadTree = viewModel::loadTree,
            avatar = avatar ?: { BentoIconButton(BentoIcons.User, stringResource(StringsR.string.files_account), onAccount) }
        )
        FilesSheetHost(state, viewModel, scanAvailable, launchers)
    }
}

private const val AUDIO_TICK_MS = 500L

internal fun scanner() = GmsDocumentScanning.getClient(
    GmsDocumentScannerOptions.Builder()
        .setGalleryImportAllowed(true)
        .setResultFormats(GmsDocumentScannerOptions.RESULT_FORMAT_PDF)
        .setScannerMode(GmsDocumentScannerOptions.SCANNER_MODE_FULL)
        .build()
)

/** FileProvider URI (authority `<applicationId>.files`, `cacheDir/share/` only) with a per-URI read grant. */
fun providerUri(context: Context, file: File): Uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file)

/** Revokes every app's read grant on [file]'s content URI (before the copy is deleted, SEC-04). */
fun revokeSharedFile(context: Context, file: File) {
    context.revokeUriPermission(providerUri(context, file), Intent.FLAG_GRANT_READ_URI_PERMISSION)
}

fun viewIntent(context: Context, file: File, mimeType: String): Intent {
    val uri = providerUri(context, file)
    val view = Intent(Intent.ACTION_VIEW).setDataAndType(uri, mimeType).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    return Intent.createChooser(view, null).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
}

fun shareIntent(context: Context, files: List<Pair<File, String>>): Intent {
    val uris = files.map { providerUri(context, it.first) }
    val send = if (uris.size == 1) {
        Intent(Intent.ACTION_SEND).setType(files.first().second).putExtra(Intent.EXTRA_STREAM, uris.first())
    } else {
        Intent(Intent.ACTION_SEND_MULTIPLE).setType(commonMime(files.map { it.second }))
            .putParcelableArrayListExtra(Intent.EXTRA_STREAM, ArrayList(uris))
    }
    send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    send.clipData = ClipData.newRawUri(null, uris.first()).apply { uris.drop(1).forEach { addItem(ClipData.Item(it)) } }
    return Intent.createChooser(send, null)
}

fun commonMime(types: List<String>): String {
    val distinct = types.distinct()
    if (distinct.size == 1) return distinct.first()
    val families = distinct.map { it.substringBefore('/') }.distinct()
    return if (families.size == 1) "${families.first()}/*" else "*/*"
}

internal fun startExternal(context: Context, intent: Intent): Boolean = try {
    context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    true
} catch (error: android.content.ActivityNotFoundException) {
    false
}

/** `Downloads/Bento/<name>` through MediaStore (no storage permission on Android 10+). */
internal fun downloadsTarget(context: Context, item: DriveItemResponse): Uri? {
    val values = ContentValues().apply {
        put(MediaStore.MediaColumns.DISPLAY_NAME, DisplayNames.file(item.name))
        put(MediaStore.MediaColumns.MIME_TYPE, item.asset?.mimeType ?: "application/octet-stream")
        put(MediaStore.MediaColumns.RELATIVE_PATH, "Download/Bento")
    }
    return runCatching { context.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) }.getOrNull()
}

@Composable
private fun FilesSheetHost(state: FilesState, viewModel: FilesViewModel, scanAvailable: Boolean, launchers: FilesLaunchers) {
    val sheet = state.sheet ?: return
    val root = stringResource(StringsR.string.files_title)
    BentoSheet(onDismissRequest = viewModel::dismissSheet) {
        when (sheet) {
            FilesSheet.New -> NewSheetBody(
                folderName = state.folderName ?: root,
                scanAvailable = scanAvailable,
                onUploadFiles = launchers::pickFiles,
                onUploadMedia = launchers::pickMedia,
                onUploadFolder = launchers::pickTree,
                onScan = launchers::scan,
                onNewFolder = { viewModel.showSheet(FilesSheet.NewFolder) }
            )

            FilesSheet.NewFolder -> {
                val field = rememberTextFieldState(stringResource(StringsR.string.files_new_folder_default))
                NameSheetBody(
                    title = stringResource(StringsR.string.files_new_folder),
                    label = stringResource(StringsR.string.files_new_folder_label),
                    confirm = stringResource(StringsR.string.files_new_folder_create),
                    field = field,
                    error = state.newFolderError,
                    busy = state.busy,
                    onConfirm = { viewModel.createFolder(field.text.toString()) }
                )
            }

            FilesSheet.Sort -> SortSheetBody(state.sort, viewModel::setSort)

            is FilesSheet.ItemMenu -> ItemMenuBody(
                sheet.item,
                pinned = sheet.item.pinnedIn(state.pinned)
            ) { action ->
                onMenuAction(viewModel, state, sheet.item, action)
            }

            is FilesSheet.Rename -> {
                val field = rememberTextFieldState(sheet.item.name)
                NameSheetBody(
                    title = stringResource(StringsR.string.files_rename_title),
                    label = stringResource(StringsR.string.files_rename_label),
                    confirm = stringResource(StringsR.string.common_action_save),
                    field = field,
                    error = state.renameError,
                    busy = state.busy,
                    onConfirm = { viewModel.rename(sheet.item, field.text.toString()) }
                )
            }

            is FilesSheet.Move -> {
                val browser by viewModel.moveBrowser.state.collectAsStateWithLifecycle()
                FolderPickerBody(
                    title = stringResource(StringsR.string.files_move_title),
                    confirmLabel = stringResource(StringsR.string.files_move_here),
                    state = browser,
                    onOpen = viewModel.moveBrowser::open,
                    onUp = viewModel.moveBrowser::up,
                    onSearch = viewModel.moveBrowser::search,
                    onCreate = viewModel.moveBrowser::create,
                    onConfirm = { viewModel.moveTo(sheet.items, it) }
                )
            }

            is FilesSheet.Details -> DetailsSheetBody(
                sheet.item,
                location = (listOf(root) + state.breadcrumbs.map { it.name }).joinToString(" › "),
                pinned = sheet.item.pinnedIn(state.pinned)
            )

            is FilesSheet.Telegram -> TelegramSheetBody(state.telegram, viewModel::loadChats) { viewModel.sendToTelegram(sheet.item, it) }

            is FilesSheet.Disclosure -> DisclosureSheetBody(sheet.kind, viewModel::confirmDisclosure, viewModel::dismissSheet)

            is FilesSheet.OfflineUnavailable -> OfflineSheetBody(sheet.item, viewModel::dismissSheet)
        }
    }
}

private fun onMenuAction(viewModel: FilesViewModel, state: FilesState, item: DriveItemResponse, action: MenuAction) {
    when (action) {
        MenuAction.Open -> {
            viewModel.dismissSheet()
            viewModel.open(item)
        }

        MenuAction.Share -> viewModel.share(listOf(item))

        MenuAction.Download -> viewModel.download(listOf(item))

        MenuAction.Offline -> viewModel.setPinned(item, !item.pinnedIn(state.pinned))

        MenuAction.Move -> viewModel.showSheet(FilesSheet.Move(listOf(item)))

        MenuAction.Rename -> viewModel.showSheet(FilesSheet.Rename(item))

        MenuAction.Favorite -> viewModel.setFavorite(item, item.asset?.favorite != true)

        MenuAction.Telegram -> viewModel.showSheet(FilesSheet.Telegram(item))

        MenuAction.Details -> viewModel.showSheet(FilesSheet.Details(item))

        MenuAction.Delete -> viewModel.trash(listOf(item))
    }
}

/** Stateless Archivos (previews, screenshots and Compose tests). */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun FilesContent(
    state: FilesState,
    uploads: UploadsState,
    audio: AudioState,
    actions: FilesActions,
    modifier: Modifier = Modifier,
    snackbar: BentoSnackbarHostState = remember { BentoSnackbarHostState() },
    onLoadTree: (String?) -> Unit = {},
    avatar: @Composable () -> Unit = {}
) {
    val activity = LocalActivity.current
    var dropping by remember { mutableStateOf(false) }
    val dropTarget = remember(actions, activity) {
        object : DragAndDropTarget {
            override fun onEntered(event: DragAndDropEvent) {
                dropping = true
            }

            override fun onExited(event: DragAndDropEvent) {
                dropping = false
            }

            override fun onEnded(event: DragAndDropEvent) {
                dropping = false
            }

            override fun onDrop(event: DragAndDropEvent): Boolean {
                dropping = false
                val drag = event.toAndroidDragEvent()
                activity?.requestDragAndDropPermissions(drag)
                val clip = drag.clipData ?: return false
                val items = (0 until clip.itemCount).mapNotNull { clip.getItemAt(it).uri?.toString() }.map { PickedContent(it) }
                actions.onDrop(items)
                return items.isNotEmpty()
            }
        }
    }
    // With a hardware keyboard (tablets, ChromeOS) the pane takes focus so shortcuts work before any row is focused.
    val keyboard = LocalConfiguration.current.keyboard != android.content.res.Configuration.KEYBOARD_NOKEYS
    val focus = remember { FocusRequester() }
    LaunchedEffect(keyboard) { if (keyboard) runCatching { focus.requestFocus() } }
    BoxWithConstraints(
        modifier
            .fillMaxSize()
            .background(BentoTheme.colors.tray)
            .testTag("files-root")
            .focusRequester(focus)
            .focusable()
            .onPreviewKeyEvent { event -> event.type == KeyEventType.KeyDown && handleKey(event, state, actions) }
            .dragAndDropTarget(shouldStartDragAndDrop = { it.mimeTypes().isNotEmpty() }, target = dropTarget)
    ) {
        val expanded = maxWidth >= 840.dp
        Row(Modifier.fillMaxSize()) {
            if (expanded) {
                FolderTreePane(state, actions, onLoadTree, Modifier.width(280.dp).fillMaxHeight())
            }
            Box(Modifier.weight(1f).fillMaxHeight()) {
                FilesPane(state, uploads, audio, actions, snackbar, avatar, gridColumnsMin = if (expanded) 160 else 140)
            }
        }
        if (dropping) {
            Box(
                Modifier.fillMaxSize().padding(8.dp).border(2.dp, BentoTheme.colors.accent, BentoShapes.lg)
                    .background(BentoTheme.colors.accentSoft.copy(alpha = 0.4f), BentoShapes.lg),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    stringResource(StringsR.string.files_drop_here),
                    color = BentoTheme.colors.accentInk,
                    style = BentoTheme.typography.sectionTitle
                )
            }
        }
    }
}

private fun handleKey(event: androidx.compose.ui.input.key.KeyEvent, state: FilesState, actions: FilesActions): Boolean = when {
    event.isCtrlPressed && event.key == Key.A -> {
        actions.onSelectAll()
        true
    }

    event.isCtrlPressed && event.key == Key.F -> {
        actions.onSearchHere()
        true
    }

    event.key == Key.Delete && state.selecting -> {
        actions.onTrash(state.selectedItems)
        true
    }

    event.key == Key.Escape && state.selecting -> {
        actions.onClearSelection()
        true
    }

    else -> false
}

@Composable
private fun FilesPane(
    state: FilesState,
    uploads: UploadsState,
    audio: AudioState,
    actions: FilesActions,
    snackbar: BentoSnackbarHostState,
    avatar: @Composable () -> Unit,
    gridColumnsMin: Int
) {
    val listState = rememberLazyListState()
    val fabExpanded by remember { derivedStateOf { listState.firstVisibleItemIndex == 0 && listState.firstVisibleItemScrollOffset < 24 } }
    Column(Modifier.fillMaxSize()) {
        BentoTopBar(
            searchLabel = stringResource(StringsR.string.common_action_search_bento),
            onSearchClick = actions.onSearch,
            windowInsets = WindowInsets(0),
            avatar = {
                BentoIconButton(
                    if (state.layout == FilesLayout.List) BentoIcons.LayoutGrid else BentoIcons.List,
                    stringResource(
                        if (state.layout ==
                            FilesLayout.List
                        ) {
                            StringsR.string.files_layout_grid
                        } else {
                            StringsR.string.files_layout_list
                        }
                    ),
                    actions.onToggleLayout
                )
                avatar()
            }
        )
        if (state.breadcrumbs.isNotEmpty()) Breadcrumbs(state.breadcrumbs, actions.onNavigate)
        Toolbar(state, actions)
        if (state.offline) {
            Callout(
                Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                tone = CalloutTone.Neutral,
                body = stringResource(StringsR.string.files_offline_banner),
                icon = BentoIcons.CloudOff
            )
        }
        Box(Modifier.weight(1f).fillMaxWidth()) {
            when {
                state.loading -> LoadingState(Modifier.fillMaxSize())

                state.loadFailed -> ErrorState(
                    stringResource(StringsR.string.files_load_failed),
                    Modifier.padding(16.dp),
                    onRetry = actions.onRetry
                )

                state.empty -> FilesEmpty(root = state.folderId == null, onNew = actions.onNew)

                state.layout == FilesLayout.Grid -> FilesGrid(state, actions, gridColumnsMin)

                else -> FilesList(state, actions, listState)
            }
        }
    }
    FilesOverlays(state, uploads, audio, actions, snackbar, fabExpanded)
}

/** Bottom layers: snackbar, decrypting card, audio mini player, upload card, then the selection bar or the FAB. */
@Composable
private fun FilesOverlays(
    state: FilesState,
    uploads: UploadsState,
    audio: AudioState,
    actions: FilesActions,
    snackbar: BentoSnackbarHostState,
    fabExpanded: Boolean
) {
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Bottom) {
        BentoSnackbarHost(snackbar)
        state.preparing?.let { PreparingCard(it, actions.onCancelPreparing) }
        AudioMiniPlayer(audio, actions.onToggleAudio, actions.onCloseAudio)
        UploadCard(uploads, actions.onPauseUploads, actions.onResumeUploads, actions.onDismissUploads)
        if (state.selecting) {
            val selected = state.selectedItems
            FloatingActionBar(
                visible = true,
                title = pluralCountResource(StringsR.plurals.common_count_selected, selected.size),
                compactTitle = formatCount(selected.size),
                actions = listOf(
                    FloatingAction(BentoIcons.Share2, stringResource(StringsR.string.common_action_share), { actions.onShare(selected) }),
                    FloatingAction(BentoIcons.FolderInput, stringResource(StringsR.string.common_action_move), {
                        actions.onMove(selected)
                    }),
                    FloatingAction(BentoIcons.Download, stringResource(StringsR.string.common_action_download), {
                        actions.onDownload(selected)
                    }),
                    FloatingAction(BentoIcons.Trash2, stringResource(StringsR.string.common_action_delete), {
                        actions.onTrash(selected)
                    }, destructive = true)
                ),
                overflow = listOf(
                    FloatingAction(BentoIcons.Pin, stringResource(StringsR.string.files_menu_offline), { actions.onPin(selected, true) }),
                    FloatingAction(BentoIcons.Check, stringResource(StringsR.string.common_action_select_all), actions.onSelectAll)
                ),
                onClose = actions.onClearSelection,
                modifier = Modifier.padding(16.dp)
            )
        } else {
            Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.End) {
                BentoFab(stringResource(StringsR.string.files_new), BentoIcons.Plus, actions.onNew, expanded = fabExpanded)
            }
        }
    }
}

@Composable
private fun FilesEmpty(root: Boolean, onNew: () -> Unit) {
    EmptyState(
        title = stringResource(if (root) StringsR.string.files_root_empty_title else StringsR.string.files_empty_title),
        body = stringResource(if (root) StringsR.string.files_root_empty_body else StringsR.string.files_empty_body),
        icon = BentoIcons.FolderClosed,
        modifier = Modifier.fillMaxSize().padding(24.dp),
        action = {
            BentoButton(
                stringResource(StringsR.string.files_new),
                onNew,
                variant = BentoButtonVariant.Primary,
                leadingIcon = BentoIcons.Plus
            )
        }
    )
}

@Composable
private fun Toolbar(state: FilesState, actions: FilesActions) {
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        BentoChip(
            stringResource(StringsR.string.files_sort_current, stringResource(sortLabel(state.sort.field)).lowercaseFirst()),
            onClick = actions.onSort,
            leadingIcon = BentoIcons.ArrowUpDown
        )
        Spacer(Modifier.weight(1f))
        if (state.folderId != null) {
            BentoIconButton(BentoIcons.Search, stringResource(StringsR.string.files_search_here), actions.onSearchHere, dense = true)
        }
    }
    if (state.truncated) {
        Text(
            stringResource(StringsR.string.files_truncated, FilesRepository.MAX_LISTING),
            color = BentoTheme.colors.inkMuted,
            style = BentoTheme.typography.metadata,
            modifier = Modifier.padding(horizontal = 16.dp)
        )
    }
}

private fun String.lowercaseFirst(): String = replaceFirstChar { it.lowercase() }

private fun callbacks(actions: FilesActions) = ItemCallbacks(
    onOpen = actions.onOpen,
    onSelect = actions.onSelect,
    onMenu = actions.onMenu,
    onShare = { actions.onShare(listOf(it)) },
    onFavorite = actions.onFavorite,
    onTrash = { actions.onTrash(listOf(it)) }
)

@Composable
private fun FilesList(state: FilesState, actions: FilesActions, listState: LazyListState) {
    val callbacks = remember(actions) { callbacks(actions) }
    LazyColumn(Modifier.fillMaxSize().testTag("files-list"), state = listState, contentPadding = PaddingValues(bottom = 160.dp)) {
        items(state.items, key = { it.id }) { item ->
            FileRow(item, selected = item.id in state.selection, selecting = state.selecting, pinned = state.pinned, callbacks = callbacks)
        }
    }
}

@Composable
private fun FilesGrid(state: FilesState, actions: FilesActions, minDp: Int) {
    val callbacks = remember(actions) { callbacks(actions) }
    LazyVerticalGrid(
        columns = GridCells.Adaptive(minDp.dp),
        modifier = Modifier.fillMaxSize().testTag("files-grid"),
        contentPadding = PaddingValues(start = 12.dp, end = 12.dp, top = 4.dp, bottom = 160.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        items(state.items, key = { it.id }) { item ->
            FileTile(item, selected = item.id in state.selection, selecting = state.selecting, pinned = state.pinned, callbacks = callbacks)
        }
    }
}

@Composable
private fun PreparingCard(preparing: Preparing, onCancel: () -> Unit) {
    val c = BentoTheme.colors
    Column(
        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp).background(c.raised, BentoShapes.lg).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                stringResource(StringsR.string.files_preparing, preparing.name),
                Modifier.weight(1f),
                color = c.ink,
                style = BentoTheme.typography.label
            )
            BentoIconButton(BentoIcons.X, stringResource(StringsR.string.common_action_cancel), onCancel, dense = true)
        }
        ProgressBar(if (preparing.total > 0) preparing.done.toFloat() / preparing.total else null, Modifier.fillMaxWidth())
    }
}

/** ≥ 840 dp: folder tree pane (list-detail with the content pane). */
@Composable
private fun FolderTreePane(state: FilesState, actions: FilesActions, onLoadTree: (String?) -> Unit, modifier: Modifier) {
    val c = BentoTheme.colors
    LaunchedEffect(Unit) { if (null !in state.tree) onLoadTree(null) }
    val rows = remember(state.tree, state.expanded) { flattenTree(state.tree, state.expanded) }
    Column(modifier.background(c.surface)) {
        Text(
            stringResource(StringsR.string.files_tree_title),
            color = c.inkMuted,
            style = BentoTheme.typography.labelStrong,
            modifier = Modifier.padding(start = 20.dp, top = 20.dp, bottom = 8.dp)
        )
        LazyColumn(Modifier.fillMaxSize()) {
            item(key = "root") {
                ListRow(
                    headline = stringResource(StringsR.string.files_title),
                    leading = { KindIcon(FileKind.Folder) },
                    onClick = { actions.onNavigate(null) },
                    selected = state.folderId == null
                )
            }
            items(rows, key = { it.first.id }) { (folder, depth) ->
                val open = folder.id in state.expanded
                Row(Modifier.padding(start = (depth * 16).dp), verticalAlignment = Alignment.CenterVertically) {
                    BentoIconButton(
                        if (open) BentoIcons.ChevronDown else BentoIcons.ChevronRight,
                        stringResource(if (open) StringsR.string.files_tree_collapse else StringsR.string.files_tree_expand, folder.name),
                        { actions.onToggleTree(folder.id) },
                        dense = true
                    )
                    ListRow(
                        headline = folder.name,
                        modifier = Modifier.weight(1f),
                        leading = { BentoIcon(BentoIcons.Folder, null, tint = c.kindFolder) },
                        onClick = { actions.onNavigate(folder.id) },
                        selected = state.folderId == folder.id
                    )
                }
            }
        }
    }
}

internal fun flattenTree(tree: Map<String?, List<DriveItemResponse>>, expanded: Set<String>): List<Pair<DriveItemResponse, Int>> {
    val rows = ArrayList<Pair<DriveItemResponse, Int>>()
    fun walk(parent: String?, depth: Int) {
        tree[parent].orEmpty().forEach { folder ->
            rows += folder to depth
            if (folder.id in expanded && depth < MAX_TREE_DEPTH) walk(folder.id, depth + 1)
        }
    }
    walk(null, 0)
    return rows
}

private const val MAX_TREE_DEPTH = 8
