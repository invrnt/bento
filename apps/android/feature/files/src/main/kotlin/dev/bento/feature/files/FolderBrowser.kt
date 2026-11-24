package dev.bento.feature.files

import dev.bento.api.ApiErrorKind
import dev.bento.api.ApiException
import dev.bento.api.generated.DriveBreadcrumbResponse
import dev.bento.api.generated.DriveItemResponse
import dev.bento.strings.R as StringsR
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** The folder picker inside the move sheet, the share destination row and the search folder filter. */
data class FolderBrowserState(
    val folderId: String? = null,
    val crumbs: List<DriveBreadcrumbResponse> = emptyList(),
    val folders: List<DriveItemResponse> = emptyList(),
    val loading: Boolean = true,
    val failed: Boolean = false,
    val query: String = "",
    val results: List<DriveItemResponse> = emptyList(),
    val recent: List<Destination> = emptyList(),
    /** Ids that cannot be a destination (the folders being moved: no cycles). */
    val blocked: Set<String> = emptySet(),
    val creating: Boolean = false,
    val createError: UiText? = null
) {
    val currentName: String? get() = crumbs.lastOrNull()?.name
    val canChooseHere: Boolean get() = folderId == null || folderId !in blocked
}

/**
 * Browses Drive folders level by level, searches folder names, creates a folder inline (then enters it), and offers
 * recent destinations at the top. Owned by a ViewModel ([scope] = its scope).
 */
class FolderBrowser(
    private val repository: FilesRepository,
    private val preferences: FilesPreferences,
    private val scope: CoroutineScope,
    blocked: Set<String> = emptySet(),
    private val debounceMs: Long = 150
) {
    private val _state = MutableStateFlow(FolderBrowserState(blocked = blocked, recent = preferences.recentDestinations.value))
    val state: StateFlow<FolderBrowserState> = _state.asStateFlow()
    private var loadJob: Job? = null
    private var searchJob: Job? = null

    fun open(folderId: String?) {
        loadJob?.cancel()
        _state.update {
            it.copy(folderId = folderId, loading = true, failed = false, query = "", results = emptyList(), createError = null)
        }
        loadJob = scope.launch {
            try {
                val listing = repository.listing(folderId)
                _state.update { state ->
                    state.copy(
                        loading = false,
                        crumbs = listing.breadcrumbs,
                        folders = FolderSort().apply(listing.items.filter { it.folder != null })
                    )
                }
            } catch (error: ApiException) {
                _state.update { it.copy(loading = false, failed = true) }
            }
        }
    }

    fun up() {
        val crumbs = _state.value.crumbs
        open(if (crumbs.size >= 2) crumbs[crumbs.size - 2].folderId else null)
    }

    fun search(query: String) {
        _state.update { it.copy(query = query) }
        searchJob?.cancel()
        if (query.isBlank()) {
            _state.update { it.copy(results = emptyList()) }
            return
        }
        searchJob = scope.launch {
            delay(debounceMs)
            val results = try {
                repository.findFolders(query)
            } catch (error: ApiException) {
                emptyList()
            }
            _state.update { it.copy(results = results) }
        }
    }

    /** `Nueva carpeta` inline: creates it here and enters it. */
    fun create(name: String) {
        val trimmed = name.trim()
        if (trimmed.isEmpty()) {
            _state.update { it.copy(createError = UiText.of(StringsR.string.files_new_folder_empty)) }
            return
        }
        _state.update { it.copy(creating = true, createError = null) }
        scope.launch {
            try {
                val folder = repository.drive.createFolder(DisplayNames.folder(trimmed), _state.value.folderId)
                _state.update { it.copy(creating = false) }
                open(folder.id)
            } catch (error: ApiException) {
                val conflict = error is ApiException.Http && error.kind == ApiErrorKind.CONFLICT
                val message = if (conflict) StringsR.string.files_new_folder_exists else StringsR.string.files_new_folder_failed
                _state.update { it.copy(creating = false, createError = UiText.of(message)) }
            }
        }
    }

    /** The current folder as a destination ([rootName] labels the Archivos root). */
    fun destination(rootName: String): Destination = Destination(_state.value.folderId, _state.value.currentName ?: rootName)
}
