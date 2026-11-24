package dev.bento.feature.files

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dev.bento.api.ApiErrorKind
import dev.bento.api.ApiException
import dev.bento.api.generated.DriveBreadcrumbResponse
import dev.bento.api.generated.DriveItemResponse
import dev.bento.api.generated.TelegramChatResponse
import dev.bento.data.Invalidations
import dev.bento.data.Topic
import dev.bento.data.Undoable
import dev.bento.designsystem.trace.InteractionTrace
import dev.bento.strings.R as StringsR
import java.io.File
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Bottom sheets of Archivos (one at a time). */
sealed interface FilesSheet {
    data object New : FilesSheet

    data object NewFolder : FilesSheet

    data object Sort : FilesSheet

    data class ItemMenu(val item: DriveItemResponse) : FilesSheet

    data class Rename(val item: DriveItemResponse) : FilesSheet

    data class Move(val items: List<DriveItemResponse>) : FilesSheet

    data class Details(val item: DriveItemResponse) : FilesSheet

    data class Telegram(val item: DriveItemResponse) : FilesSheet

    /** Plaintext notice before a copy leaves Bento; [then] runs on `Continuar`. */
    data class Disclosure(
        val kind: dev.bento.feature.files.Disclosure,
        val items: List<DriveItemResponse>,
        val then: PendingAction
    ) : FilesSheet

    /** Offline and not pinned (journey 8): explains how to make it available offline. */
    data class OfflineUnavailable(val item: DriveItemResponse) : FilesSheet
}

enum class PendingAction { OpenWith, Share, SaveToPhone }

/** A decrypting download in progress ("Descifrando «x»…"). */
data class Preparing(val name: String, val done: Long = 0, val total: Long = -1)

data class TelegramPicker(val loading: Boolean = true, val chats: List<TelegramChatResponse> = emptyList(), val failed: Boolean = false)

data class FilesState(
    val folderId: String? = null,
    val loading: Boolean = true,
    val loadFailed: Boolean = false,
    val fromCache: Boolean = false,
    val offline: Boolean = false,
    val items: List<DriveItemResponse> = emptyList(),
    val breadcrumbs: List<DriveBreadcrumbResponse> = emptyList(),
    val truncated: Boolean = false,
    val sort: FolderSort = FolderSort(),
    val layout: FilesLayout = FilesLayout.List,
    val selection: Set<String> = emptySet(),
    val pinned: Set<String> = emptySet(),
    val sheet: FilesSheet? = null,
    val preparing: Preparing? = null,
    val renameError: UiText? = null,
    val newFolderError: UiText? = null,
    val busy: Boolean = false,
    val telegram: TelegramPicker = TelegramPicker(),
    /** Large screens: the file shown in the detail pane. */
    val focused: String? = null,
    /** Large screens: the folder tree pane (children per folder, null = root) and the expanded folders. */
    val tree: Map<String?, List<DriveItemResponse>> = emptyMap(),
    val expanded: Set<String> = emptySet(),
    /** The folder this screen was opened on (back from it leaves the screen). */
    val startFolderId: String? = null
) {
    val canGoUp: Boolean get() = folderId != startFolderId
    val selecting: Boolean get() = selection.isNotEmpty()
    val selectedItems: List<DriveItemResponse> get() = items.filter { it.id in selection }
    val folderName: String? get() = breadcrumbs.lastOrNull()?.name
    val empty: Boolean get() = !loading && !loadFailed && items.isEmpty()
}

/** One-shot effects the screen performs with Android APIs (intents, SAF, navigation). */
sealed interface FilesEffect {
    data class Message(val message: FilesMessage) : FilesEffect

    data class OpenViewer(val assetId: String) : FilesEffect

    data class OpenDocument(val assetId: String) : FilesEffect

    data class OpenWith(val file: File, val mimeType: String) : FilesEffect

    data class Share(val files: List<Pair<File, String>>) : FilesEffect

    /** `Descargar al teléfono` of one file: SAF create document, then [FilesViewModel.saveTo]. */
    data class CreateDocument(val item: DriveItemResponse) : FilesEffect

    /** Several files: written to `Downloads/Bento` (MediaStore). */
    data class SaveToDownloads(val items: List<DriveItemResponse>) : FilesEffect

    data class Search(val folderId: String?, val folderName: String?) : FilesEffect
}

@HiltViewModel
class FilesViewModel @Inject constructor(
    private val repository: FilesRepository,
    private val preferences: FilesPreferences,
    private val content: ContentFiles,
    val uploads: UploadCoordinator,
    val audio: AudioControls,
    private val connectivity: Connectivity,
    private val invalidations: Invalidations,
    private val treeReader: TreeReader
) : ViewModel() {
    private val _state = MutableStateFlow(FilesState(layout = preferences.layout.value, pinned = preferences.pinned.value))
    val state: StateFlow<FilesState> = _state.asStateFlow()
    private val effects = Channel<FilesEffect>(Channel.BUFFERED)
    val effect: Flow<FilesEffect> = effects.receiveAsFlow()
    private var loadJob: Job? = null
    private var prepareJob: Job? = null
    private var started = false

    /** The move sheet's folder browser (blocked = the folders being moved). */
    var moveBrowser: FolderBrowser = FolderBrowser(repository, preferences, viewModelScope)
        private set

    init {
        preferences.pinned.onEach { pinned -> _state.update { it.copy(pinned = pinned) } }.launchIn(viewModelScope)
        preferences.layout.onEach { layout -> _state.update { it.copy(layout = layout) } }.launchIn(viewModelScope)
        invalidations.topics.filter { Topic.DRIVE in it }.onEach { load(quiet = true) }.launchIn(viewModelScope)
    }

    fun start(folderId: String?) {
        if (started) return
        started = true
        _state.update { it.copy(startFolderId = folderId) }
        navigateTo(repository.lastOpen(folderId))
    }

    /** Drill-in/out inside Archivos (the navigation bar stays; back goes up one level). */
    fun navigateTo(folderId: String?) {
        loadJob?.cancel()
        repository.rememberOpen(_state.value.startFolderId, folderId)
        val cached = repository.cached(folderId) ?: if (folderId == null) repository.cachedRoot() else null
        _state.update {
            it.copy(
                folderId = folderId,
                sort = preferences.sort(folderId),
                items = cached?.let { listing -> preferences.sort(folderId).apply(listing.items) }.orEmpty(),
                breadcrumbs = cached?.breadcrumbs.orEmpty(),
                loading = cached == null,
                loadFailed = false,
                fromCache = cached != null,
                truncated = cached?.truncated ?: false,
                selection = emptySet(),
                focused = null
            )
        }
        load()
    }

    /** Back: the parent folder; false when this screen's start folder is showing (the shell handles back). */
    fun up(): Boolean {
        val state = _state.value
        if (!state.canGoUp) return false
        val crumbs = state.breadcrumbs
        navigateTo(if (crumbs.size >= 2) crumbs[crumbs.size - 2].folderId else null)
        return true
    }

    // Tree pane (≥ 840 dp) ----------------------------------------------------------------------------------------

    fun loadTree(parentId: String?) {
        viewModelScope.launch {
            try {
                val folders = FolderSort().apply(repository.folders(parentId))
                _state.update { it.copy(tree = it.tree + (parentId to folders)) }
            } catch (error: ApiException) {
                Unit
            }
        }
    }

    fun toggleExpanded(folderId: String) {
        val expanded = folderId in _state.value.expanded
        _state.update { it.copy(expanded = if (expanded) it.expanded - folderId else it.expanded + folderId) }
        if (!expanded && folderId !in _state.value.tree) loadTree(folderId)
    }

    fun load(quiet: Boolean = false) {
        loadJob?.cancel()
        val folderId = _state.value.folderId
        if (!quiet && _state.value.items.isEmpty()) _state.update { it.copy(loading = true, loadFailed = false) }
        loadJob = viewModelScope.launch {
            try {
                val listing = repository.listing(folderId)
                _state.update { state ->
                    state.copy(
                        loading = false,
                        loadFailed = false,
                        fromCache = false,
                        offline = false,
                        items = state.sort.apply(listing.items),
                        breadcrumbs = listing.breadcrumbs,
                        truncated = listing.truncated,
                        selection = state.selection.intersect(listing.items.map { it.id }.toSet())
                    )
                }
            } catch (error: ApiException) {
                val offline = !connectivity.online()
                _state.update { it.copy(loading = false, loadFailed = it.items.isEmpty(), offline = offline) }
            }
        }
    }

    // Layout and sort ---------------------------------------------------------------------------------------------

    fun toggleLayout() = preferences.setLayout(if (_state.value.layout == FilesLayout.List) FilesLayout.Grid else FilesLayout.List)

    fun setSort(sort: FolderSort) {
        preferences.setSort(_state.value.folderId, sort)
        _state.update { it.copy(sort = sort, items = sort.apply(it.items)) }
    }

    // Sheets ------------------------------------------------------------------------------------------------------

    fun showSheet(sheet: FilesSheet?) {
        _state.update { it.copy(sheet = sheet, renameError = null, newFolderError = null) }
        when (sheet) {
            is FilesSheet.Move -> {
                moveBrowser =
                    FolderBrowser(
                        repository,
                        preferences,
                        viewModelScope,
                        blocked = sheet.items.filter {
                            it.folder != null
                        }.map { it.id }.toSet()
                    )
                moveBrowser.open(_state.value.folderId)
            }

            is FilesSheet.Telegram -> loadChats(null)

            else -> Unit
        }
    }

    fun dismissSheet() = showSheet(null)

    // Selection ---------------------------------------------------------------------------------------------------

    fun toggleSelection(item: DriveItemResponse) = _state.update {
        it.copy(selection = if (item.id in it.selection) it.selection - item.id else it.selection + item.id)
    }

    fun selectAll() = _state.update { it.copy(selection = it.items.map { item -> item.id }.toSet()) }

    fun clearSelection() = _state.update { it.copy(selection = emptySet()) }

    fun focus(item: DriveItemResponse?) = _state.update { it.copy(focused = item?.id) }

    // Opening -----------------------------------------------------------------------------------------------------

    fun open(item: DriveItemResponse) {
        if (_state.value.selecting) {
            toggleSelection(item)
            return
        }
        val asset = item.asset
        if (item.folder != null || asset == null) {
            InteractionTrace.begin(InteractionTrace.FILES_OPEN)
            navigateTo(item.id)
            return
        }
        val kind = FileKinds.openKind(asset)
        if (kind in NEEDS_ORIGINAL && !connectivity.online() && asset.id !in _state.value.pinned) {
            showSheet(FilesSheet.OfflineUnavailable(item))
            return
        }
        when (kind) {
            OpenKind.Image, OpenKind.Video -> send(FilesEffect.OpenViewer(asset.id))
            OpenKind.Pdf, OpenKind.Text -> send(FilesEffect.OpenDocument(asset.id))
            OpenKind.Audio -> audio.play(asset.id, asset.filename)
            OpenKind.Folder -> navigateTo(item.id)
            OpenKind.Other -> guarded(Disclosure.OpenWith, listOf(item), PendingAction.OpenWith)
        }
    }

    fun openWith(item: DriveItemResponse) = guarded(Disclosure.OpenWith, listOf(item), PendingAction.OpenWith)

    fun share(items: List<DriveItemResponse>) = guarded(Disclosure.Share, items.filter { it.asset != null }, PendingAction.Share)

    fun download(items: List<DriveItemResponse>) = guarded(
        Disclosure.SaveToPhone,
        items.filter {
            it.asset != null
        },
        PendingAction.SaveToPhone
    )

    /** Shows the plaintext notice unless the person chose "No volver a mostrar" for this action type. */
    private fun guarded(kind: Disclosure, items: List<DriveItemResponse>, action: PendingAction) {
        if (items.isEmpty()) return
        if (preferences.skipsDisclosure(kind)) run(action, items) else showSheet(FilesSheet.Disclosure(kind, items, action))
    }

    fun confirmDisclosure(dontShowAgain: Boolean) {
        val sheet = _state.value.sheet as? FilesSheet.Disclosure ?: return
        if (dontShowAgain) preferences.skipDisclosure(sheet.kind)
        dismissSheet()
        run(sheet.then, sheet.items)
    }

    private fun run(action: PendingAction, items: List<DriveItemResponse>) {
        when (action) {
            PendingAction.OpenWith -> prepare(items.take(1)) { files ->
                send(FilesEffect.OpenWith(files.first().first, files.first().second))
            }

            PendingAction.Share -> prepare(items) { files -> send(FilesEffect.Share(files)) }

            PendingAction.SaveToPhone -> if (items.size == 1) {
                send(FilesEffect.CreateDocument(items.first()))
            } else {
                send(FilesEffect.SaveToDownloads(items))
            }
        }
        clearSelection()
    }

    private fun prepare(items: List<DriveItemResponse>, done: (List<Pair<File, String>>) -> Unit) {
        prepareJob?.cancel()
        prepareJob = viewModelScope.launch {
            val files = ArrayList<Pair<File, String>>()
            try {
                for (item in items) {
                    val asset = item.asset ?: continue
                    _state.update { it.copy(preparing = Preparing(asset.filename)) }
                    val file = content.plaintextCopy(asset.id, asset.filename) { bytes, total ->
                        _state.update { it.copy(preparing = Preparing(asset.filename, bytes, total)) }
                    }
                    files += file to asset.mimeType
                }
                _state.update { it.copy(preparing = null) }
                done(files)
            } catch (error: ApiException) {
                _state.update { it.copy(preparing = null) }
                files.forEach { content.discard(it.first) }
                openFailed(items.firstOrNull())
            }
        }
    }

    fun cancelPreparing() {
        prepareJob?.cancel()
        _state.update { it.copy(preparing = null) }
    }

    private fun openFailed(item: DriveItemResponse?) {
        if (item != null && !connectivity.online() && item.asset?.id !in _state.value.pinned) {
            showSheet(FilesSheet.OfflineUnavailable(item))
        } else {
            message(UiText.of(StringsR.string.files_open_failed), danger = true)
        }
    }

    /** Streams one original into the SAF document the person created. */
    fun saveTo(item: DriveItemResponse, write: suspend (assetId: String, onProgress: (Long, Long) -> Unit) -> Unit) {
        val asset = item.asset ?: return
        prepareJob?.cancel()
        prepareJob = viewModelScope.launch {
            _state.update { it.copy(preparing = Preparing(asset.filename)) }
            try {
                write(asset.id) { bytes, total -> _state.update { it.copy(preparing = Preparing(asset.filename, bytes, total)) } }
                message(UiText.of(StringsR.string.files_saved_to_phone, asset.filename))
            } catch (error: ApiException) {
                message(UiText.of(StringsR.string.files_save_failed), danger = true)
            } catch (error: java.io.IOException) {
                message(UiText.of(StringsR.string.files_save_failed), danger = true)
            } finally {
                _state.update { it.copy(preparing = null) }
            }
        }
    }

    // Mutations ---------------------------------------------------------------------------------------------------

    fun createFolder(name: String) {
        val trimmed = name.trim()
        if (trimmed.isEmpty()) {
            _state.update { it.copy(newFolderError = UiText.of(StringsR.string.files_new_folder_empty)) }
            return
        }
        _state.update { it.copy(busy = true, newFolderError = null) }
        viewModelScope.launch {
            try {
                val folder = repository.drive.createFolder(DisplayNames.folder(trimmed), _state.value.folderId)
                _state.update { it.copy(busy = false, sheet = null) }
                message(UiText.of(StringsR.string.files_new_folder_created, folder.name))
                load(quiet = true)
            } catch (error: ApiException) {
                val text = if (error.isConflict()) StringsR.string.files_new_folder_exists else StringsR.string.files_new_folder_failed
                _state.update { it.copy(busy = false, newFolderError = UiText.of(text)) }
            }
        }
    }

    fun rename(item: DriveItemResponse, name: String) {
        val clean = if (item.folder != null) DisplayNames.folder(name.trim()) else DisplayNames.file(name.trim())
        if (name.isBlank() || clean == item.name) {
            dismissSheet()
            return
        }
        _state.update { it.copy(busy = true, renameError = null) }
        viewModelScope.launch {
            try {
                replaceLocal(item.copy(name = clean))
                val undo = repository.drive.rename(item, clean)
                _state.update { it.copy(busy = false, sheet = null) }
                message(UiText.of(StringsR.string.files_renamed, clean), undo)
            } catch (error: ApiException) {
                replaceLocal(item)
                val text = if (error.isConflict()) StringsR.string.files_new_folder_exists else StringsR.string.files_rename_failed
                _state.update { it.copy(busy = false, renameError = UiText.of(text)) }
            }
        }
    }

    fun trash(items: List<DriveItemResponse>) {
        if (items.isEmpty()) return
        clearSelection()
        dismissSheet()
        hideLocal(items.map { it.id })
        viewModelScope.launch {
            val undos = ArrayList<Undoable>()
            try {
                items.forEach { undos += repository.drive.trash(it) }
                val text = if (items.size == 1) {
                    UiText.of(StringsR.string.files_trashed, items.first().name)
                } else {
                    UiText.plural(StringsR.plurals.files_trashed_many, items.size, items.size)
                }
                message(text, combined(undos))
            } catch (error: ApiException) {
                undos.forEach { runCatching { it.undo() } }
                load(quiet = true)
                message(UiText.of(StringsR.string.files_action_failed), danger = true)
            }
        }
    }

    /** `Mover aquí` from the move sheet. Folders move with `PATCH parent_id`; cycles are refused before calling. */
    fun moveTo(items: List<DriveItemResponse>, destination: Destination) {
        if (items.any { it.folder != null && it.id == destination.id }) {
            message(UiText.of(StringsR.string.files_move_into_self), danger = true)
            return
        }
        val from = _state.value.folderId
        dismissSheet()
        clearSelection()
        if (destination.id == from) return
        preferences.rememberDestination(destination)
        hideLocal(items.map { it.id })
        viewModelScope.launch {
            val undos = ArrayList<Undoable>()
            try {
                items.forEach { item ->
                    undos +=
                        if (item.folder !=
                            null
                        ) {
                            moveFolder(item, destination.id, from)
                        } else {
                            repository.drive.move(item.id, destination.id, from)
                        }
                }
                val text = if (items.size == 1) {
                    UiText.of(StringsR.string.files_moved, destination.name)
                } else {
                    UiText.plural(StringsR.plurals.files_moved_many, items.size, items.size, destination.name)
                }
                message(text, combined(undos))
            } catch (error: ApiException) {
                undos.forEach { runCatching { it.undo() } }
                load(quiet = true)
                val text = if (error is ApiException.Http && error.kind == ApiErrorKind.CONFLICT) {
                    StringsR.string.files_move_into_self
                } else {
                    StringsR.string.files_move_failed
                }
                message(UiText.of(text), danger = true)
            }
        }
    }

    private suspend fun moveFolder(item: DriveItemResponse, to: String?, from: String?): Undoable {
        repository.moveFolder(item.id, to)
        return repository.undoable { repository.moveFolder(item.id, from) }
    }

    fun setPinned(item: DriveItemResponse, pinned: Boolean) {
        val asset = item.asset ?: return
        dismissSheet()
        preferences.setPinned(asset.id, pinned)
        viewModelScope.launch {
            try {
                repository.setPinned(asset.id, pinned)
                message(UiText.of(if (pinned) StringsR.string.files_pinned else StringsR.string.files_unpinned, asset.filename))
            } catch (error: ApiException) {
                preferences.setPinned(asset.id, !pinned)
                message(UiText.of(StringsR.string.files_action_failed), danger = true)
            }
        }
    }

    fun setPinned(items: List<DriveItemResponse>, pinned: Boolean) {
        clearSelection()
        items.filter { it.asset != null }.forEach { setPinned(it, pinned) }
    }

    fun setFavorite(item: DriveItemResponse, favorite: Boolean) {
        val asset = item.asset ?: return
        dismissSheet()
        replaceLocal(item.copy(asset = asset.copy(favorite = favorite)))
        viewModelScope.launch {
            try {
                repository.setFavorite(asset.id, favorite)
                if (favorite) message(UiText.of(StringsR.string.files_favorited, asset.filename))
            } catch (error: ApiException) {
                replaceLocal(item)
                message(UiText.of(StringsR.string.files_action_failed), danger = true)
            }
        }
    }

    // Telegram ----------------------------------------------------------------------------------------------------

    fun loadChats(query: String?) {
        _state.update { it.copy(telegram = it.telegram.copy(loading = true, failed = false)) }
        viewModelScope.launch {
            try {
                val chats = repository.telegramChats(query)
                _state.update { it.copy(telegram = TelegramPicker(loading = false, chats = chats)) }
            } catch (error: ApiException) {
                _state.update { it.copy(telegram = TelegramPicker(loading = false, failed = true)) }
            }
        }
    }

    fun sendToTelegram(item: DriveItemResponse, chat: TelegramChatResponse) {
        val asset = item.asset ?: return
        dismissSheet()
        viewModelScope.launch {
            try {
                repository.sendToTelegram(asset.id, chat.id)
                message(UiText.of(StringsR.string.files_telegram_sent, chat.title))
            } catch (error: ApiException) {
                message(UiText.of(StringsR.string.files_telegram_failed), danger = true)
            }
        }
    }

    // Uploads -----------------------------------------------------------------------------------------------------

    fun upload(items: List<PickedContent>) {
        dismissSheet()
        if (items.isNotEmpty()) uploads.submit(items, UploadTarget(_state.value.folderId))
    }

    /** `Subir una carpeta`: recreates the picked tree under the current folder. */
    fun uploadTree(treeUri: String) {
        dismissSheet()
        val parent = _state.value.folderId
        viewModelScope.launch {
            try {
                val importer = FolderTreeImport(treeReader, repository, uploads)
                val name = DisplayNames.folder(runCatching { treeReader.rootName(treeUri) }.getOrNull())
                message(UiText.of(StringsR.string.files_folder_upload_started, name))
                val result = importer.run(treeUri, parent)
                if (result.truncated) message(UiText.of(StringsR.string.files_folder_upload_truncated, FolderTreeImport.MAX_FILES))
                load(quiet = true)
            } catch (error: ApiException) {
                message(UiText.of(StringsR.string.files_folder_upload_failed), danger = true)
            } catch (error: RuntimeException) {
                message(UiText.of(StringsR.string.files_folder_upload_failed), danger = true)
            }
        }
    }

    /** A document scan (multipage PDF) into the current folder, named `Escaneo 2026-11-24 10.41.pdf`. */
    fun uploadScan(pdfUri: String, name: String) = upload(listOf(PickedContent(pdfUri, displayName = name, mimeType = "application/pdf")))

    fun searchHere() = send(FilesEffect.Search(_state.value.folderId, _state.value.folderName))

    // Helpers -----------------------------------------------------------------------------------------------------

    private fun hideLocal(ids: List<String>) = _state.update { state -> state.copy(items = state.items.filterNot { it.id in ids }) }

    private fun replaceLocal(item: DriveItemResponse) = _state.update { state ->
        state.copy(items = state.items.map { if (it.id == item.id) item else it })
    }

    private suspend fun combined(undos: List<Undoable>): Undoable = repository.undoable {
        undos.asReversed().forEach { it.undo() }
        load(quiet = true)
    }

    fun message(text: UiText, undo: Undoable? = null, danger: Boolean = false) = send(FilesEffect.Message(FilesMessage(text, undo, danger)))

    private fun send(effect: FilesEffect) {
        effects.trySend(effect)
    }
}

/** Openers that read the original (thumbnails/previews are enough for the viewer). */
private val NEEDS_ORIGINAL = setOf(OpenKind.Pdf, OpenKind.Text, OpenKind.Other, OpenKind.Audio)

internal fun ApiException.isConflict(): Boolean = this is ApiException.Http && kind == ApiErrorKind.CONFLICT
