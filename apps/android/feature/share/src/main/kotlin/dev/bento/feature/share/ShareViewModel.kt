package dev.bento.feature.share

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dev.bento.api.ApiException
import dev.bento.api.generated.AlbumResponse
import dev.bento.api.generated.BentoEndpoints
import dev.bento.feature.files.Destination
import dev.bento.feature.files.DisplayNames
import dev.bento.feature.files.FilesPreferences
import dev.bento.feature.files.FilesRepository
import dev.bento.feature.files.FolderBrowser
import dev.bento.feature.files.PickedContent
import dev.bento.feature.files.UploadCoordinator
import dev.bento.feature.files.UploadTarget
import javax.inject.Inject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Writes a shared text/URL as a `.txt` note Bento then imports (the file is only a hand-off copy). */
fun interface NoteStore {
    /** Returns a URI the import can open. */
    fun write(name: String, text: String): String
}

/** Direct Share: the system share sheet offers the 4 most recent destination folders (product/android.md §4.9). */
fun interface DirectShare {
    fun publish(destinations: List<Destination>)
}

enum class SharePicker { Folder, Album }

data class ShareState(
    val loading: Boolean = true,
    val items: List<SharedDescription> = emptyList(),
    val note: String? = null,
    val noteName: String? = null,
    val destination: Destination = Destination(null, ""),
    val album: AlbumResponse? = null,
    val albums: List<AlbumResponse> = emptyList(),
    val albumsLoading: Boolean = false,
    val picker: SharePicker? = null,
    val saved: Boolean = false
) {
    val readable: List<SharedDescription> get() = items.filter { it.readable }
    val unreadable: List<SharedDescription> get() = items.filterNot { it.readable }
    val count: Int get() = readable.size + if (note != null) 1 else 0
    val totalBytes: Long get() = readable.sumOf { it.sizeBytes ?: 0L } + (note?.toByteArray()?.size?.toLong() ?: 0L)
    val canAddToAlbum: Boolean get() = readable.isNotEmpty() && readable.all { it.media } && note == null
    val canSave: Boolean get() = !loading && count > 0 && !saved
}

/**
 * Share to Bento sheet: describes what arrived (readable or not), picks the destination (last used folder, or the
 * Direct Share target), optionally an album for media, and hands everything to [UploadCoordinator] on `Guardar en Bento`
 * — which only opens descriptors, so the sheet can close right away (≤ 200 ms) while the copy runs in background.
 */
@HiltViewModel
class ShareViewModel @Inject constructor(
    private val describer: ContentDescriber,
    private val uploads: UploadCoordinator,
    private val preferences: FilesPreferences,
    private val files: FilesRepository,
    private val api: BentoEndpoints,
    private val notes: NoteStore,
    private val directShare: DirectShare
) : ViewModel() {
    private val _state = MutableStateFlow(ShareState())
    val state: StateFlow<ShareState> = _state.asStateFlow()
    val folderBrowser = FolderBrowser(files, preferences, viewModelScope)
    private var started = false

    fun start(payload: SharePayload, rootName: String, noteFallback: String) {
        if (started) return
        started = true
        val recent = preferences.recentDestinations.value
        val destination = payload.shortcutFolderId?.let { id -> recent.firstOrNull { it.id == id } ?: Destination(id, rootName) }
            ?: recent.firstOrNull()
            ?: Destination(null, rootName)
        val note = if (payload.noteOnly) payload.text else null
        _state.update {
            it.copy(
                destination = destination,
                note = note,
                noteName = note?.let { text -> DisplayNames.note(payload.subject?.takeIf { s -> s.isNotBlank() } ?: text, noteFallback) }
            )
        }
        if (payload.shortcutFolderId != null && recent.none { it.id == payload.shortcutFolderId }) resolveName(payload.shortcutFolderId)
        viewModelScope.launch {
            val described = withContext(Dispatchers.IO) { payload.items.map { describer.describe(it) } }
            _state.update { it.copy(loading = false, items = described) }
        }
    }

    private fun resolveName(folderId: String) = viewModelScope.launch {
        val name = try {
            files.listing(folderId).breadcrumbs.lastOrNull()?.name
        } catch (error: ApiException) {
            null
        }
        if (name != null) _state.update { it.copy(destination = Destination(folderId, name)) }
    }

    fun showPicker(picker: SharePicker?) {
        _state.update { it.copy(picker = picker) }
        when (picker) {
            SharePicker.Folder -> folderBrowser.open(_state.value.destination.id)
            SharePicker.Album -> loadAlbums()
            null -> Unit
        }
    }

    private fun loadAlbums() {
        if (_state.value.albums.isNotEmpty()) return
        _state.update { it.copy(albumsLoading = true) }
        viewModelScope.launch {
            val albums = try {
                api.listAlbums(limit = MAX_ALBUMS).items
            } catch (error: ApiException) {
                emptyList()
            }
            _state.update { it.copy(albums = albums, albumsLoading = false) }
        }
    }

    fun setDestination(destination: Destination) = _state.update { it.copy(destination = destination, picker = null) }

    fun setAlbum(album: AlbumResponse?) = _state.update { it.copy(album = album, picker = null) }

    /**
     * `Guardar en Bento`: registers every stream now (the grants of the sending app are alive while the sheet is) and
     * returns; unreadable ones are recorded for Activity with their names. Returns false when there is nothing to save.
     */
    fun save(): Boolean {
        val state = _state.value
        if (!state.canSave) return false
        val picked = state.items.map { PickedContent(it.uri, displayName = it.name, mimeType = it.mimeType, sizeBytes = it.sizeBytes) } +
            listOfNotNull(
                state.note?.let { text ->
                    val name = state.noteName ?: "nota.txt"
                    PickedContent(
                        notes.write(name, text),
                        displayName = name,
                        mimeType = "text/plain",
                        sizeBytes = text.toByteArray().size.toLong()
                    )
                }
            )
        uploads.submit(picked, UploadTarget(state.destination.id, state.album?.id))
        preferences.rememberDestination(state.destination)
        runCatching { directShare.publish(preferences.recentDestinations.value.take(DIRECT_SHARE_TARGETS)) }
        _state.update { it.copy(saved = true) }
        return true
    }

    companion object {
        const val DIRECT_SHARE_TARGETS = 4
        private const val MAX_ALBUMS = 50L
    }
}
