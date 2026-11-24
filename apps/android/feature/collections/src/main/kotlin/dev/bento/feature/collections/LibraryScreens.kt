package dev.bento.feature.collections

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.paging.LoadState
import androidx.paging.compose.collectAsLazyPagingItems
import dev.bento.api.BentoImage
import dev.bento.api.generated.TelegramMediaResponse
import dev.bento.data.DocumentEntry
import dev.bento.data.PhoneFolder
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoDialog
import dev.bento.designsystem.component.BentoFilterChip
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.BentoIconButton
import dev.bento.designsystem.component.BentoSheet
import dev.bento.designsystem.component.BentoSnackbarHost
import dev.bento.designsystem.component.BentoSnackbarHostState
import dev.bento.designsystem.component.BentoTextAction
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.EmptyState
import dev.bento.designsystem.component.ErrorState
import dev.bento.designsystem.component.FileKind
import dev.bento.designsystem.component.KindIcon
import dev.bento.designsystem.component.ListRow
import dev.bento.designsystem.component.LoadingState
import dev.bento.designsystem.component.SelectionCheck
import dev.bento.designsystem.component.Thumbnail
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.photos.ChatAvatar
import dev.bento.feature.photos.LocalBentoImageLoader
import dev.bento.feature.photos.MediaEventsEffect
import dev.bento.feature.photos.MediaFormat
import dev.bento.feature.photos.MediaSheet
import dev.bento.feature.photos.MediaSheetHost
import dev.bento.feature.photos.SheetData
import dev.bento.feature.photos.TelegramChatsViewModel
import dev.bento.feature.photos.chatKindLabel
import dev.bento.strings.R as StringsR
import kotlinx.coroutines.launch

/** Kind of a file for the kind palette, from its MIME type (a lookup table). */
@Suppress("CyclomaticComplexMethod")
fun fileKindOf(mime: String, name: String = ""): FileKind = when {
    mime == "application/pdf" -> FileKind.Pdf
    mime.startsWith("image/") -> FileKind.Image
    mime.startsWith("video/") -> FileKind.Video
    mime.startsWith("audio/") -> FileKind.Audio
    mime.contains("spreadsheet") || mime.contains("excel") || name.endsWith(".csv") -> FileKind.Sheet
    mime.contains("presentation") || mime.contains("powerpoint") -> FileKind.Slides
    mime.contains("zip") || mime.contains("compressed") || mime.contains("tar") -> FileKind.Archive
    mime.startsWith("text/") -> FileKind.Text
    else -> FileKind.Doc
}

// --- Documentos ------------------------------------------------------------------------------------------------------

@Composable
fun DocumentsRoute(navigation: CollectionsNavigation) {
    val vm: DocumentsViewModel = hiltViewModel()
    val state by vm.state.collectAsStateWithLifecycle()
    val snackbar = remember { BentoSnackbarHostState() }
    var sheet by remember { mutableStateOf<MediaSheet?>(null) }
    MediaEventsEffect(vm.actions, snackbar, onSheet = { sheet = it })
    DocumentsContent(state, navigation.back, vm::open, vm::load, snackbar)
    MediaSheetHost(sheet, vm.actions, onClose = { sheet = null })
}

/** A thin documents list (agent 40's file list component can replace the rows later). */
@Composable
fun DocumentsContent(
    state: Loadable<dev.bento.data.DocumentsRepository.Result>,
    onBack: () -> Unit,
    onOpen: (String) -> Unit,
    onRetry: () -> Unit,
    snackbar: BentoSnackbarHostState = remember { BentoSnackbarHostState() }
) {
    val context = LocalContext.current
    val locale = LocalConfiguration.current.locales[0]
    SubPage(stringResource(StringsR.string.collections_documents), onBack, snackbar) {
        when (state) {
            Loadable.Loading -> LoadingState(Modifier.fillMaxSize())

            Loadable.Failed -> ErrorState(
                stringResource(StringsR.string.collections_documents_error),
                Modifier.fillMaxSize().padding(24.dp),
                onRetry = onRetry
            )

            is Loadable.Ready -> if (state.value.items.isEmpty()) {
                EmptyState(
                    title = stringResource(StringsR.string.collections_documents_empty_title),
                    body = stringResource(StringsR.string.collections_documents_empty_body),
                    icon = BentoIcons.FileText,
                    modifier = Modifier.fillMaxSize().padding(24.dp)
                )
            } else {
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
                    if (state.value.truncated) {
                        item(key = "truncated") {
                            Callout(
                                body = stringResource(StringsR.string.collections_documents_truncated),
                                modifier = Modifier.padding(16.dp)
                            )
                        }
                    }
                    items(state.value.items, key = { it.id }) { doc -> DocumentRow(doc, context, locale) { onOpen(doc.id) } }
                }
            }
        }
    }
}

@Composable
private fun DocumentRow(doc: DocumentEntry, context: android.content.Context, locale: java.util.Locale, onClick: () -> Unit) {
    ListRow(
        headline = doc.name,
        supporting = listOfNotNull(
            MediaFormat.bytes(context, doc.sizeBytes, locale),
            doc.createdAt?.let {
                MediaFormat.longDate(it, locale)
            }
        )
            .joinToString(" · "),
        leading = { KindIcon(fileKindOf(doc.mimeType, doc.name)) },
        onClick = onClick,
        onClickLabel = stringResource(StringsR.string.common_action_open_with)
    )
}

// --- Del teléfono ------------------------------------------------------------------------------------------------------

@Composable
fun PhoneFoldersRoute(navigation: CollectionsNavigation) {
    val vm: PhoneFoldersViewModel = hiltViewModel()
    val state by vm.state.collectAsStateWithLifecycle()
    PhoneFoldersContent(state, navigation.back, navigation.openBackupSettings, vm::load)
}

@Composable
fun PhoneFoldersContent(state: Loadable<List<PhoneFolder>>, onBack: () -> Unit, onBackup: () -> Unit, onRetry: () -> Unit) {
    val locale = LocalConfiguration.current.locales[0]
    SubPage(stringResource(StringsR.string.collections_phone), onBack) {
        when (state) {
            Loadable.Loading -> LoadingState(Modifier.fillMaxSize())

            Loadable.Failed -> ErrorState(
                stringResource(StringsR.string.collections_phone_error),
                Modifier.fillMaxSize().padding(24.dp),
                onRetry = onRetry
            )

            is Loadable.Ready -> if (state.value.isEmpty()) {
                EmptyState(
                    title = stringResource(StringsR.string.collections_phone_empty_title),
                    body = stringResource(StringsR.string.collections_phone_empty_body),
                    icon = BentoIcons.Smartphone,
                    modifier = Modifier.fillMaxSize().padding(24.dp)
                ) {
                    BentoButton(
                        stringResource(StringsR.string.collections_phone_action),
                        onBackup,
                        variant = BentoButtonVariant.Primary,
                        leadingIcon = BentoIcons.CloudUpload
                    )
                }
            } else {
                LazyColumn(Modifier.fillMaxSize()) {
                    items(state.value, key = { it.id }) { folder ->
                        val status = when {
                            !folder.enabled -> stringResource(StringsR.string.collections_phone_state_off)

                            folder.error != null -> stringResource(StringsR.string.collections_phone_state_error)

                            folder.state == "scanning" -> stringResource(StringsR.string.collections_phone_state_scanning)

                            folder.state == "paused" -> stringResource(StringsR.string.collections_phone_state_paused)

                            folder.filesPending > 0 -> pluralStringResource(
                                StringsR.plurals.collections_phone_pending,
                                folder.filesPending,
                                MediaFormat.number(folder.filesPending, locale)
                            )

                            else -> stringResource(StringsR.string.collections_phone_state_done)
                        }
                        ListRow(
                            headline = folder.label,
                            supporting = stringResource(
                                StringsR.string.collections_phone_row,
                                pluralStringResource(
                                    StringsR.plurals.collections_count_items,
                                    folder.filesTotal,
                                    MediaFormat.number(folder.filesTotal, locale)
                                ),
                                status
                            ),
                            leading = {
                                BentoIcon(
                                    if (folder.kind ==
                                        "media_store"
                                    ) {
                                        BentoIcons.Camera
                                    } else {
                                        BentoIcons.FolderClosed
                                    },
                                    null,
                                    tint = BentoTheme.colors.inkMuted
                                )
                            },
                            trailing = { BentoIcon(BentoIcons.ChevronRight, null, tint = BentoTheme.colors.inkSubtle) },
                            onClick = onBackup
                        )
                    }
                }
            }
        }
    }
}

// --- Importado de Telegram ---------------------------------------------------------------------------------------------

/**
 * Importado de Telegram: how it works and `Importar de Telegram`. The backend does not tag imported items yet, so
 * imports appear in Fotos/Archivos rather than in a list here (backend gap noted in the handoff).
 */
@Composable
fun TelegramImportsContent(onBack: () -> Unit, onImport: () -> Unit) {
    SubPage(stringResource(StringsR.string.collections_telegram), onBack) {
        EmptyState(
            title = stringResource(StringsR.string.collections_telegram_empty_title),
            body = stringResource(StringsR.string.collections_telegram_empty_body),
            icon = BentoIcons.Send,
            modifier = Modifier.fillMaxSize().padding(24.dp)
        ) {
            BentoButton(
                stringResource(StringsR.string.collections_telegram_import),
                onImport,
                variant = BentoButtonVariant.Primary,
                leadingIcon = BentoIcons.Download
            )
        }
    }
}

/** Chat picker: Mensajes guardados first (backend order), then recent chats. */
@Composable
fun TelegramChatsRoute(navigation: CollectionsNavigation) {
    val vm: TelegramChatsViewModel = hiltViewModel()
    val chats by vm.chats.collectAsStateWithLifecycle()
    val search = rememberTextFieldState()
    LaunchedEffect(search) { snapshotFlow { search.text.toString() }.collect { vm.query.value = it } }
    SubPage(stringResource(StringsR.string.collections_telegram_chats_title), navigation.back) {
        Column(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
            dev.bento.designsystem.component.BentoTextField(
                state = search,
                label = stringResource(StringsR.string.photos_telegram_search),
                hideLabel = true,
                placeholder = stringResource(StringsR.string.photos_telegram_search),
                leadingIcon = BentoIcons.Search,
                modifier = Modifier.fillMaxWidth()
            )
            when (val data = chats) {
                SheetData.Loading -> LoadingState(Modifier.fillMaxSize())

                SheetData.Failed -> ErrorState(stringResource(StringsR.string.collections_telegram_chats_error), Modifier.fillMaxSize())

                is SheetData.Ready -> LazyColumn(Modifier.fillMaxSize()) {
                    items(data.items, key = { it.id }) { chat ->
                        ListRow(
                            headline = chat.title,
                            supporting = chatKindLabel(chat.kind),
                            leading = { ChatAvatar(chat.title) },
                            trailing = { BentoIcon(BentoIcons.ChevronRight, null, tint = BentoTheme.colors.inkSubtle) },
                            onClick = { navigation.openTelegramChat(chat.id, chat.title) }
                        )
                    }
                }
            }
        }
    }
}

/** A chat's media: kind chips, select all, then `Importar N` (background job). */
@Suppress("LongMethod")
@Composable
fun TelegramMediaRoute(chatId: Long, title: String, navigation: CollectionsNavigation, onImported: () -> Unit) {
    val vm = hiltViewModel<TelegramMediaViewModel, TelegramMediaViewModel.Factory>(key = "tg-media:$chatId") { it.create(chatId) }
    val state by vm.state.collectAsStateWithLifecycle()
    val kind by vm.kind.collectAsStateWithLifecycle()
    val selected by vm.selected.collectAsStateWithLifecycle()
    val done by vm.done.collectAsStateWithLifecycle()
    LaunchedEffect(done) { if (done) onImported() }
    TelegramMediaContent(title, state, kind, selected, navigation.back, vm::setKind, vm::toggle, vm::selectAll, vm::loadMore, vm::import)
}

@Suppress("LongMethod", "LongParameterList")
@Composable
fun TelegramMediaContent(
    title: String,
    state: Loadable<TelegramMediaViewModel.MediaUi>,
    kind: String,
    selected: Set<Long>,
    onBack: () -> Unit,
    onKind: (String) -> Unit,
    onToggle: (Long) -> Unit,
    onSelectAll: () -> Unit,
    onLoadMore: () -> Unit,
    onImport: () -> Unit
) {
    val context = LocalContext.current
    val locale = LocalConfiguration.current.locales[0]
    Box(Modifier.fillMaxSize()) {
        SubPage(title, onBack, actions = {
            if (state is Loadable.Ready && state.value.items.isNotEmpty()) {
                BentoTextAction(stringResource(StringsR.string.collections_select_all), onSelectAll, Modifier.padding(end = 8.dp))
            }
        }) {
            Column(Modifier.fillMaxSize()) {
                Row(
                    Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    listOf(
                        "all" to StringsR.string.collections_telegram_kind_all,
                        "photo" to StringsR.string.collections_telegram_kind_photo,
                        "video" to StringsR.string.collections_telegram_kind_video,
                        "document" to StringsR.string.collections_telegram_kind_document
                    ).forEach { (value, label) ->
                        BentoFilterChip(stringResource(label), selected = kind == value, onSelectedChange = { onKind(value) })
                    }
                }
                when (state) {
                    Loadable.Loading -> LoadingState(Modifier.fillMaxSize())

                    Loadable.Failed -> ErrorState(
                        stringResource(StringsR.string.collections_telegram_media_error),
                        Modifier.fillMaxSize().padding(24.dp)
                    )

                    is Loadable.Ready -> if (state.value.items.isEmpty()) {
                        EmptyState(
                            title = stringResource(StringsR.string.collections_telegram_media_empty),
                            body = stringResource(StringsR.string.collections_telegram_summary),
                            icon = BentoIcons.Send,
                            modifier = Modifier.fillMaxSize().padding(24.dp)
                        )
                    } else {
                        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 96.dp)) {
                            items(state.value.items, key = { it.messageId }) { media ->
                                TelegramMediaRow(media, media.messageId in selected, context, locale) { onToggle(media.messageId) }
                            }
                            if (state.value.nextCursor != null) {
                                item(key = "more") {
                                    LaunchedEffect(Unit) { onLoadMore() }
                                    LoadingState(Modifier.fillMaxWidth().padding(16.dp))
                                }
                            }
                        }
                    }
                }
            }
        }
        BentoButton(
            text = pluralStringResource(StringsR.plurals.collections_telegram_import_count, selected.size, selected.size),
            onClick = onImport,
            enabled = selected.isNotEmpty(),
            variant = BentoButtonVariant.Primary,
            leadingIcon = BentoIcons.Download,
            modifier = Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(16.dp)
        )
    }
}

@Composable
private fun TelegramMediaRow(
    media: TelegramMediaResponse,
    selected: Boolean,
    context: android.content.Context,
    locale: java.util.Locale,
    onToggle: () -> Unit
) {
    val kind = when (media.kind) {
        "photo" -> FileKind.Image
        "video" -> FileKind.Video
        "audio", "voice" -> FileKind.Audio
        else -> fileKindOf("", media.filename)
    }
    ListRow(
        headline = media.filename,
        supporting = stringResource(
            StringsR.string.collections_telegram_media_row,
            MediaFormat.longDate(media.date, locale),
            media.sizeBytes?.let { MediaFormat.bytes(context, it, locale) }.orEmpty()
        ).trimEnd(' ', '·'),
        leading = { KindIcon(kind) },
        trailing = { SelectionCheck(selected) },
        selected = selected,
        onClick = onToggle
    )
}

// --- Papelera ------------------------------------------------------------------------------------------------------

@Suppress("LongMethod")
@Composable
fun TrashRoute(navigation: CollectionsNavigation) {
    val vm: TrashViewModel = hiltViewModel()
    val items = vm.items.collectAsLazyPagingItems()
    val summary by vm.summary.collectAsStateWithLifecycle()
    val message by vm.message.collectAsStateWithLifecycle()
    val undo by vm.undo.collectAsStateWithLifecycle()
    val snackbar = remember { BentoSnackbarHostState() }
    val context = LocalContext.current
    val undoLabel = stringResource(StringsR.string.common_action_undo)
    val scope = rememberCoroutineScope()
    LaunchedEffect(message) {
        message?.let {
            vm.messageShown()
            snackbar.show(it.resolve(context))
        }
    }
    LaunchedEffect(undo) {
        undo?.let { (text, undoable) ->
            vm.undoShown()
            scope.launch { if (snackbar.showUndo(text.resolve(context), undoLabel)) undoable.undo() }
        }
    }
    val list = (0 until items.itemCount).mapNotNull { items.peek(it) }.filter { it.id.isNotEmpty() }
    CompositionLocalProvider(LocalBentoImageLoader provides vm.imageLoader) {
        TrashContent(
            items = list,
            loading = items.itemCount == 0 && items.loadState.refresh is LoadState.Loading,
            failed = items.itemCount == 0 && items.loadState.refresh is LoadState.Error,
            summary = summary,
            snackbar = snackbar,
            onBack = navigation.back,
            onRestore = { vm.restore(listOf(it)) },
            onPurge = { vm.purge(listOf(it)) },
            onAskEmpty = vm::loadSummary,
            onEmpty = vm::empty,
            onRetry = { items.retry() },
            onVisible = { index -> if (index < items.itemCount) items[index] }
        )
    }
}

@Suppress("LongMethod", "LongParameterList")
@Composable
fun TrashContent(
    items: List<TrashItem>,
    loading: Boolean,
    failed: Boolean,
    summary: Pair<Int, Long>?,
    snackbar: BentoSnackbarHostState,
    onBack: () -> Unit,
    onRestore: (String) -> Unit,
    onPurge: (String) -> Unit,
    onAskEmpty: () -> Unit,
    onEmpty: () -> Unit,
    onRetry: () -> Unit,
    onVisible: (Int) -> Unit = {},
    nowMs: Long = System.currentTimeMillis()
) {
    var acting by remember { mutableStateOf<TrashItem?>(null) }
    var confirmPurge by remember { mutableStateOf<TrashItem?>(null) }
    var confirmEmpty by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val locale = LocalConfiguration.current.locales[0]
    SubPage(stringResource(StringsR.string.collections_trash), onBack, snackbar, actions = {
        if (items.isNotEmpty()) {
            BentoTextAction(stringResource(StringsR.string.collections_trash_empty_action), {
                onAskEmpty()
                confirmEmpty = true
            }, Modifier.padding(end = 8.dp))
        }
    }) {
        when {
            loading -> LoadingState(Modifier.fillMaxSize())

            failed -> ErrorState(
                stringResource(StringsR.string.collections_trash_error),
                Modifier.fillMaxSize().padding(24.dp),
                onRetry = onRetry
            )

            items.isEmpty() -> EmptyState(
                title = stringResource(StringsR.string.collections_trash_empty_title),
                body = stringResource(StringsR.string.collections_trash_empty_body),
                icon = BentoIcons.Trash2,
                modifier = Modifier.fillMaxSize().padding(24.dp)
            )

            else -> LazyColumn(
                Modifier.fillMaxSize().testTag(CollectionsTestTags.TrashList),
                contentPadding = PaddingValues(bottom = 24.dp)
            ) {
                items(items.size, key = { items[it].id }) { index ->
                    onVisible(index)
                    val item = items[index]
                    val days = TrashItem.daysLeft(item.purgeAt, nowMs)
                    val left = when (days) {
                        null -> null
                        0 -> stringResource(StringsR.string.collections_trash_today)
                        else -> pluralStringResource(StringsR.plurals.collections_trash_days_left, days, days)
                    }
                    ListRow(
                        headline = item.name,
                        supporting = listOfNotNull(left, MediaFormat.bytes(context, item.sizeBytes, locale)).joinToString(" · "),
                        leading = { TrashThumb(item) },
                        trailing = {
                            BentoIconButton(BentoIcons.RotateCcw, stringResource(StringsR.string.collections_trash_restore), {
                                onRestore(item.id)
                            })
                        },
                        onClick = { acting = item }
                    )
                }
            }
        }
    }
    acting?.let { item ->
        BentoSheet(onDismissRequest = { acting = null }, title = item.name) {
            ListRow(
                headline = stringResource(StringsR.string.collections_trash_restore),
                leading = { BentoIcon(BentoIcons.RotateCcw, null, tint = BentoTheme.colors.ink) },
                onClick = {
                    acting = null
                    onRestore(item.id)
                }
            )
            ListRow(
                headline = stringResource(StringsR.string.common_action_delete_forever),
                leading = { BentoIcon(BentoIcons.Trash2, null, tint = BentoTheme.colors.dangerInk) },
                onClick = {
                    acting = null
                    confirmPurge = item
                }
            )
        }
    }
    confirmPurge?.let { item ->
        BentoDialog(
            title = stringResource(StringsR.string.collections_trash_purge_title),
            consequence = stringResource(StringsR.string.collections_trash_purge_body),
            confirmLabel = stringResource(StringsR.string.common_action_delete_forever),
            onConfirm = {
                confirmPurge = null
                onPurge(item.id)
            },
            onDismissRequest = { confirmPurge = null }
        )
    }
    if (confirmEmpty) {
        val count = summary?.first ?: items.size
        val bytes = summary?.second ?: items.sumOf { it.sizeBytes }
        BentoDialog(
            title = stringResource(StringsR.string.collections_trash_empty_confirm_title),
            consequence = pluralStringResource(
                StringsR.plurals.collections_trash_empty_confirm_body,
                count,
                MediaFormat.number(count, locale),
                MediaFormat.bytes(context, bytes, locale)
            ),
            confirmLabel = stringResource(StringsR.string.collections_trash_empty_action),
            onConfirm = {
                confirmEmpty = false
                onEmpty()
            },
            onDismissRequest = { confirmEmpty = false }
        )
    }
}

@Composable
private fun TrashThumb(item: TrashItem) {
    val loader = LocalBentoImageLoader.current
    val painter = if (item.hasThumbnail && loader != null) {
        val context = LocalContext.current
        val request =
            remember(item.id) { coil3.request.ImageRequest.Builder(context).data(BentoImage.thumbnail(item.id)).size(256).build() }
        val p = coil3.compose.rememberAsyncImagePainter(request, loader)
        val s by p.state.collectAsStateWithLifecycle()
        p.takeIf { s is coil3.compose.AsyncImagePainter.State.Success }
    } else {
        null
    }
    if (item.hasThumbnail) {
        Thumbnail(painter, contentDescription = null, modifier = Modifier.size(40.dp).clip(BentoShapes.md))
    } else {
        KindIcon(if (item.type == "folder") FileKind.Folder else fileKindOf("", item.name))
    }
}

/** Sub-page scaffold: top bar with back + content + snackbar. */
@Composable
fun SubPage(
    title: String,
    onBack: () -> Unit,
    snackbar: BentoSnackbarHostState? = null,
    actions: @Composable androidx.compose.foundation.layout.RowScope.() -> Unit = {},
    content: @Composable () -> Unit
) {
    Box(Modifier.fillMaxSize().background(BentoTheme.colors.surface)) {
        Column(Modifier.fillMaxSize()) {
            CollectionTopBar(title, onBack, actions = actions)
            Box(Modifier.weight(1f).fillMaxWidth()) { content() }
        }
        if (snackbar != null) BentoSnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter).fillMaxWidth())
    }
}
