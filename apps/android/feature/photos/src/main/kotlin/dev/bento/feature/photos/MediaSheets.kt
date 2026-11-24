package dev.bento.feature.photos

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dev.bento.api.ApiException
import dev.bento.api.BentoImage
import dev.bento.api.generated.AlbumResponse
import dev.bento.api.generated.DriveItemResponse
import dev.bento.api.generated.TelegramChatResponse
import dev.bento.data.AlbumsRepository
import dev.bento.data.DriveRepository
import dev.bento.data.TelegramMediaRepository
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.BentoSheet
import dev.bento.designsystem.component.BentoTextField
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.KindIcon
import dev.bento.designsystem.component.ListRow
import dev.bento.designsystem.component.LoadingState
import dev.bento.designsystem.component.SwitchRow
import dev.bento.designsystem.component.Thumbnail
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.strings.R as StringsR
import javax.inject.Inject
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch

/** Load state for small sheet lists. */
sealed interface SheetData<out T> {
    data object Loading : SheetData<Nothing>

    data class Ready<T>(val items: List<T>) : SheetData<T>

    data object Failed : SheetData<Nothing>
}

/**
 * "Se compartirá una copia sin cifrar": shown before a plaintext export the first time per kind, with
 * `No volver a mostrar` (product/android.md §10).
 */
@Composable
fun PlaintextDisclosureSheet(kind: Disclosure, onContinue: (hideNextTime: Boolean) -> Unit, onDismiss: () -> Unit) {
    var hide by rememberSaveable { mutableStateOf(false) }
    BentoSheet(onDismissRequest = onDismiss, title = stringResource(StringsR.string.photos_disclosure_title)) {
        Callout(tone = CalloutTone.Info, body = stringResource(kind.body), icon = BentoIcons.EyeOff, modifier = Modifier.fillMaxWidth())
        SwitchRow(
            title = stringResource(StringsR.string.common_plaintext_dont_show_again),
            checked = hide,
            onCheckedChange = { hide = it },
            modifier = Modifier.padding(top = 8.dp)
        )
        BentoButton(
            text = stringResource(StringsR.string.common_action_continue),
            onClick = { onContinue(hide) },
            variant = BentoButtonVariant.Primary,
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp)
        )
        BentoButton(
            text = stringResource(StringsR.string.common_action_cancel),
            onClick = onDismiss,
            variant = BentoButtonVariant.Ghost,
            modifier = Modifier.fillMaxWidth()
        )
    }
}

// --- Añadir a álbum -----------------------------------------------------------------------------------------------

@HiltViewModel
class AlbumSheetViewModel @Inject constructor(private val albums: AlbumsRepository) : ViewModel() {
    private val _data = MutableStateFlow<SheetData<AlbumResponse>>(SheetData.Loading)
    val data: StateFlow<SheetData<AlbumResponse>> = _data.asStateFlow()

    init {
        viewModelScope.launch {
            _data.value = try {
                SheetData.Ready(collectAlbums())
            } catch (error: ApiException) {
                SheetData.Failed
            }
        }
    }

    private suspend fun collectAlbums(): List<AlbumResponse> {
        val out = ArrayList<AlbumResponse>()
        var cursor: String? = null
        repeat(10) {
            val page = albums.page(cursor)
            out += page.items
            cursor = page.nextCursor ?: return out
        }
        return out
    }
}

/** Stateful wrapper: loads albums, then [AddToAlbumSheetContent]. */
@Composable
fun AddToAlbumSheet(onPick: (AlbumResponse) -> Unit, onCreate: (String) -> Unit, onDismiss: () -> Unit) {
    val vm: AlbumSheetViewModel = hiltViewModel(key = "album-sheet")
    val data by vm.data.collectAsStateWithLifecycle()
    AddToAlbumSheetContent(data, onPick, onCreate, onDismiss)
}

@Composable
fun AddToAlbumSheetContent(data: SheetData<AlbumResponse>, onPick: (AlbumResponse) -> Unit, onCreate: (String) -> Unit, onDismiss: () -> Unit) {
    var creating by rememberSaveable { mutableStateOf(false) }
    val name = rememberTextFieldState()
    var error by remember { mutableStateOf<String?>(null) }
    val missingName = stringResource(StringsR.string.collections_create_name_error)
    BentoSheet(onDismissRequest = onDismiss, title = stringResource(StringsR.string.photos_album_sheet_title)) {
        if (creating) {
            BentoTextField(
                state = name,
                label = stringResource(StringsR.string.photos_album_name_label),
                placeholder = stringResource(StringsR.string.photos_album_name_hint),
                error = error,
                modifier = Modifier.fillMaxWidth()
            )
            BentoButton(
                text = stringResource(StringsR.string.photos_album_create),
                onClick = {
                    val title = name.text.toString().trim()
                    if (title.isEmpty()) error = missingName else onCreate(title)
                },
                variant = BentoButtonVariant.Primary,
                modifier = Modifier.fillMaxWidth().padding(top = 12.dp)
            )
            return@BentoSheet
        }
        ListRow(
            headline = stringResource(StringsR.string.photos_album_new),
            leading = { BentoIcon(BentoIcons.Plus, null, tint = BentoTheme.colors.accent) },
            onClick = { creating = true }
        )
        when (data) {
            SheetData.Loading -> LoadingState(Modifier.fillMaxWidth().padding(24.dp))

            SheetData.Failed -> Callout(tone = CalloutTone.Danger, body = stringResource(StringsR.string.photos_action_failed))

            is SheetData.Ready -> if (data.items.isEmpty()) {
                Text(
                    stringResource(StringsR.string.photos_album_empty),
                    color = BentoTheme.colors.inkMuted,
                    style = BentoTheme.typography.body,
                    modifier = Modifier.padding(16.dp)
                )
            } else {
                LazyColumn(Modifier.fillMaxWidth().heightIn(max = 420.dp)) {
                    items(data.items, key = { it.id }) { album ->
                        ListRow(
                            headline = album.title,
                            supporting = pluralStringResource(StringsR.plurals.photos_album_count, album.assetIds.size, album.assetIds.size),
                            leading = { AlbumCover(album, Modifier.size(48.dp)) },
                            onClick = { onPick(album) }
                        )
                    }
                }
            }
        }
    }
}

/** 1:1 cover from the album's first photo (the backend has no explicit cover yet), or the album icon. */
@Composable
fun AlbumCover(album: AlbumResponse, modifier: Modifier = Modifier, aspectRatio: Float = 1f, sizePx: Int = 256) {
    val first = album.assetIds.firstOrNull()
    val painter = first?.let { rememberCoverPainter(it, sizePx) }
    Thumbnail(
        painter = painter,
        contentDescription = null,
        aspectRatio = aspectRatio,
        modifier = modifier.clip(BentoShapes.md),
        placeholder = { BentoIcon(BentoIcons.SquareLibrary, null, tint = BentoTheme.colors.inkSubtle) }
    )
}

@Composable
private fun rememberCoverPainter(assetId: String, sizePx: Int): androidx.compose.ui.graphics.painter.Painter? {
    val loader = LocalBentoImageLoader.current ?: return null
    val context = androidx.compose.ui.platform.LocalContext.current
    val request = remember(assetId, sizePx) {
        coil3.request.ImageRequest.Builder(context).data(BentoImage.thumbnail(assetId)).size(sizePx).build()
    }
    val painter = coil3.compose.rememberAsyncImagePainter(request, loader)
    val state by painter.state.collectAsStateWithLifecycle()
    return painter.takeIf { state is coil3.compose.AsyncImagePainter.State.Success }
}

// --- Mover a carpeta ----------------------------------------------------------------------------------------------

@HiltViewModel
class MoveSheetViewModel @Inject constructor(private val drive: DriveRepository) : ViewModel() {
    data class Level(val id: String?, val name: String?)

    private val _path = MutableStateFlow(listOf(Level(null, null)))
    val path: StateFlow<List<Level>> = _path.asStateFlow()
    private val _folders = MutableStateFlow<SheetData<DriveItemResponse>>(SheetData.Loading)
    val folders: StateFlow<SheetData<DriveItemResponse>> = _folders.asStateFlow()

    init {
        load()
    }

    fun open(folder: DriveItemResponse) {
        _path.value = _path.value + Level(folder.id, folder.name)
        load()
    }

    fun up(): Boolean {
        if (_path.value.size <= 1) return false
        _path.value = _path.value.dropLast(1)
        load()
        return true
    }

    private fun load() {
        val folderId = _path.value.last().id
        _folders.value = SheetData.Loading
        viewModelScope.launch {
            _folders.value = try {
                SheetData.Ready(drive.folders(folderId))
            } catch (error: ApiException) {
                SheetData.Failed
            }
        }
    }
}

@Composable
fun MoveToFolderSheet(onMove: (folderId: String?, folderName: String) -> Unit, onDismiss: () -> Unit) {
    val vm: MoveSheetViewModel = hiltViewModel(key = "move-sheet")
    val path by vm.path.collectAsStateWithLifecycle()
    val folders by vm.folders.collectAsStateWithLifecycle()
    val root = stringResource(StringsR.string.photos_move_root)
    MoveToFolderSheetContent(
        path = path.map { it.name ?: root },
        folders = folders,
        onOpen = vm::open,
        onUp = { vm.up() },
        onMoveHere = { onMove(path.last().id, path.last().name ?: root) },
        onDismiss = onDismiss
    )
}

@Composable
fun MoveToFolderSheetContent(
    path: List<String>,
    folders: SheetData<DriveItemResponse>,
    onOpen: (DriveItemResponse) -> Unit,
    onUp: () -> Unit,
    onMoveHere: () -> Unit,
    onDismiss: () -> Unit
) {
    BentoSheet(onDismissRequest = onDismiss, title = stringResource(StringsR.string.photos_move_sheet_title)) {
        Row(
            Modifier.fillMaxWidth().heightIn(min = 48.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            if (path.size > 1) {
                dev.bento.designsystem.component.BentoIconButton(BentoIcons.ArrowLeft, stringResource(StringsR.string.common_action_back), onUp)
            }
            Text(
                path.joinToString(" › "),
                color = BentoTheme.colors.ink,
                style = BentoTheme.typography.labelStrong,
                maxLines = 1,
                modifier = Modifier.weight(1f)
            )
        }
        Column(Modifier.fillMaxWidth().heightIn(min = 120.dp, max = 380.dp)) {
            when (folders) {
                SheetData.Loading -> LoadingState(Modifier.fillMaxWidth().padding(24.dp))

                SheetData.Failed -> Callout(tone = CalloutTone.Danger, body = stringResource(StringsR.string.photos_action_failed))

                is SheetData.Ready -> if (folders.items.isEmpty()) {
                    Text(
                        stringResource(StringsR.string.photos_move_empty),
                        color = BentoTheme.colors.inkMuted,
                        style = BentoTheme.typography.body,
                        modifier = Modifier.padding(16.dp)
                    )
                } else {
                    LazyColumn {
                        items(folders.items, key = { it.id }) { folder ->
                            ListRow(
                                headline = folder.name,
                                leading = { KindIcon(dev.bento.designsystem.component.FileKind.Folder) },
                                trailing = { BentoIcon(BentoIcons.ChevronRight, null, tint = BentoTheme.colors.inkSubtle) },
                                onClick = { onOpen(folder) },
                                onClickLabel = stringResource(StringsR.string.photos_move_open_folder, folder.name)
                            )
                        }
                    }
                }
            }
        }
        BentoButton(
            text = stringResource(StringsR.string.photos_move_here),
            onClick = onMoveHere,
            variant = BentoButtonVariant.Primary,
            leadingIcon = BentoIcons.FolderInput,
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp)
        )
    }
}

// --- Enviar por Telegram ------------------------------------------------------------------------------------------

@OptIn(FlowPreview::class)
@HiltViewModel
class TelegramChatsViewModel @Inject constructor(private val telegram: TelegramMediaRepository) : ViewModel() {
    val query = MutableStateFlow("")
    private val _chats = MutableStateFlow<SheetData<TelegramChatResponse>>(SheetData.Loading)
    val chats: StateFlow<SheetData<TelegramChatResponse>> = _chats.asStateFlow()

    init {
        viewModelScope.launch {
            query.debounce(150).distinctUntilChanged().collect { text ->
                _chats.value = try {
                    SheetData.Ready(telegram.chats(text))
                } catch (error: ApiException) {
                    SheetData.Failed
                }
            }
        }
    }
}

/** Chat picker for "Enviar por Telegram…"; the plaintext line is always shown (product/android.md §10). */
@Composable
fun TelegramChatSheet(onPick: (TelegramChatResponse) -> Unit, onDismiss: () -> Unit) {
    val vm: TelegramChatsViewModel = hiltViewModel(key = "telegram-sheet")
    val chats by vm.chats.collectAsStateWithLifecycle()
    val search = rememberTextFieldState()
    LaunchedEffect(search) { snapshotFlow { search.text.toString() }.collect { vm.query.value = it } }
    TelegramChatSheetContent(chats, search, onPick, onDismiss)
}

@Composable
fun TelegramChatSheetContent(
    chats: SheetData<TelegramChatResponse>,
    search: androidx.compose.foundation.text.input.TextFieldState,
    onPick: (TelegramChatResponse) -> Unit,
    onDismiss: () -> Unit,
    title: String = stringResource(StringsR.string.photos_telegram_sheet_title),
    showDisclosure: Boolean = true
) {
    BentoSheet(onDismissRequest = onDismiss, title = title) {
        if (showDisclosure) {
            Callout(tone = CalloutTone.Info, body = stringResource(StringsR.string.common_plaintext_telegram), icon = BentoIcons.EyeOff)
        }
        BentoTextField(
            state = search,
            label = stringResource(StringsR.string.photos_telegram_search),
            hideLabel = true,
            placeholder = stringResource(StringsR.string.photos_telegram_search),
            leadingIcon = BentoIcons.Search,
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp)
        )
        Column(Modifier.fillMaxWidth().heightIn(min = 160.dp, max = 420.dp)) {
            when (chats) {
                SheetData.Loading -> LoadingState(Modifier.fillMaxWidth().padding(24.dp))

                SheetData.Failed -> Callout(tone = CalloutTone.Danger, body = stringResource(StringsR.string.collections_telegram_chats_error))

                is SheetData.Ready -> if (chats.items.isEmpty()) {
                    Text(
                        stringResource(StringsR.string.photos_telegram_empty),
                        color = BentoTheme.colors.inkMuted,
                        style = BentoTheme.typography.body,
                        modifier = Modifier.padding(16.dp)
                    )
                } else {
                    LazyColumn {
                        items(chats.items, key = { it.id }) { chat ->
                            ListRow(
                                headline = chat.title,
                                supporting = chatKindLabel(chat.kind),
                                leading = { ChatAvatar(chat.title) },
                                onClick = { onPick(chat) }
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun chatKindLabel(kind: String): String = stringResource(
    when (kind) {
        "self", "saved" -> StringsR.string.collections_telegram_chat_saved
        "group", "supergroup" -> StringsR.string.collections_telegram_chat_group
        "channel" -> StringsR.string.collections_telegram_chat_channel
        else -> StringsR.string.collections_telegram_chat_user
    }
)

/** Initials avatar for a chat (Telegram avatars are not fetched: no extra network). */
@Composable
fun ChatAvatar(title: String, modifier: Modifier = Modifier) {
    val c = BentoTheme.colors
    androidx.compose.foundation.layout.Box(
        modifier.size(40.dp).clip(BentoShapes.full).background(c.accentSoft),
        contentAlignment = Alignment.Center
    ) {
        Text(
            title.split(' ').filter { it.isNotBlank() }.take(2).joinToString("") { it.take(1).uppercase() },
            color = c.accentInk,
            style = BentoTheme.typography.labelStrong
        )
    }
}
