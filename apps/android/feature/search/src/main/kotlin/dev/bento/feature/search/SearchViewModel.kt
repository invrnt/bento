package dev.bento.feature.search

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dev.bento.api.ApiException
import dev.bento.api.generated.AlbumResponse
import dev.bento.api.generated.BentoEndpoints
import dev.bento.api.generated.SearchItemResponse
import dev.bento.feature.files.Destination
import dev.bento.feature.files.FileKinds
import dev.bento.feature.files.FilesPreferences
import dev.bento.feature.files.FilesRepository
import dev.bento.feature.files.FolderBrowser
import dev.bento.feature.files.OpenKind
import java.time.LocalDate
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import dev.bento.designsystem.trace.InteractionTrace

/** Filter sheets of Buscar (Tipo, Fecha, Carpeta). */
enum class FilterSheet { Kind, Date, Folder }

data class SearchSuggestions(
    val years: List<Int> = emptyList(),
    val folders: List<Destination> = emptyList(),
    val albums: List<AlbumResponse> = emptyList()
)

data class SearchState(
    val query: String = "",
    val filters: SearchFilters = SearchFilters(),
    /** The scope the screen was opened with (`Buscar en esta carpeta`); removing it searches everywhere. */
    val scope: Destination? = null,
    val loading: Boolean = false,
    val failed: Boolean = false,
    val results: List<SearchItemResponse> = emptyList(),
    val nextCursor: String? = null,
    val loadingMore: Boolean = false,
    val recents: List<String> = emptyList(),
    val suggestions: SearchSuggestions = SearchSuggestions(),
    val sheet: FilterSheet? = null,
    /** Indexing still running for some hits (OCR pending): told once, calmly. */
    val indexing: Boolean = false
) {
    /** Before typing and without filters: recents and suggestion chips. */
    val idle: Boolean get() = query.isBlank() && !filters.active
    val noResults: Boolean get() = !idle && !loading && !failed && results.isEmpty()
    val grouped: Map<ResultGroup, List<SearchItemResponse>> get() = results.groupBy { groupOf(it) }.toSortedMap()
}

sealed interface SearchEffect {
    data class OpenViewer(val assetId: String) : SearchEffect

    data class OpenDocument(val assetId: String) : SearchEffect

    data class OpenFolder(val folderId: String?) : SearchEffect

    data class OpenAlbum(val albumId: String) : SearchEffect
}

/**
 * Buscar (product/android.md §4.7): 150 ms debounce, `GET /api/search` with type/date/folder filters, grouped results
 * with match reasons, local recents and suggestion chips. Search by meaning is never offered on Android.
 */
@HiltViewModel
class SearchViewModel @Inject constructor(
    private val api: BentoEndpoints,
    private val recents: RecentSearches,
    private val files: FilesRepository,
    private val filesPreferences: FilesPreferences
) : ViewModel() {
    private val _state = MutableStateFlow(SearchState())
    val state: StateFlow<SearchState> = _state.asStateFlow()
    private val effects = Channel<SearchEffect>(Channel.BUFFERED)
    val effect: Flow<SearchEffect> = effects.receiveAsFlow()
    private var searchJob: Job? = null
    private var started = false
    internal var today: () -> LocalDate = { LocalDate.now() }
    internal var debounceMs: Long = DEBOUNCE_MS

    /** Folder picker of the Carpeta filter. */
    val folderBrowser = FolderBrowser(files, filesPreferences, viewModelScope)

    init {
        recents.items.onEach { items -> _state.update { it.copy(recents = items) } }.launchIn(viewModelScope)
    }

    fun start(query: String, scope: Destination?) {
        if (started) return
        started = true
        _state.update { it.copy(query = query, scope = scope, filters = it.filters.copy(folder = scope)) }
        loadSuggestions()
        if (query.isNotBlank() || scope != null) runSearch(immediate = true)
    }

    private fun loadSuggestions() {
        _state.update {
            it.copy(
                suggestions = it.suggestions.copy(
                    folders = filesPreferences.recentDestinations.value.filter { d ->
                        d.id !=
                            null
                    }.take(4)
                )
            )
        }
        viewModelScope.launch {
            val years = runCatching { detectedYears(api.photosTimelineIndex().months.map { it.month }, today()) }.getOrDefault(emptyList())
            val albums = try {
                api.listAlbums(limit = MAX_ALBUMS.toLong()).items
            } catch (error: ApiException) {
                emptyList()
            }
            _state.update { it.copy(suggestions = it.suggestions.copy(years = years, albums = albums)) }
        }
    }

    fun setQuery(query: String) {
        if (query == _state.value.query) return
        if (query.isNotBlank() && _state.value.results.isEmpty()) InteractionTrace.beginIfIdle(InteractionTrace.SEARCH_RESULTS)
        _state.update { it.copy(query = query) }
        runSearch()
    }

    fun submit() {
        recents.add(_state.value.query)
        runSearch(immediate = true)
    }

    fun pickRecent(query: String) {
        _state.update { it.copy(query = query) }
        recents.add(query)
        runSearch(immediate = true)
    }

    fun removeRecent(query: String) = recents.remove(query)

    fun clearRecents() = recents.clear()

    fun setKind(kind: SearchKind?) = updateFilters { it.copy(kind = kind) }

    fun setDate(date: DateFilter?) = updateFilters { it.copy(date = date) }

    fun setFolder(folder: Destination?) = updateFilters { it.copy(folder = folder) }

    fun thisMonth() = setDate(DateFilter.ThisMonth(today()))

    fun lastYear() = setDate(DateFilter.LastYear(today()))

    fun year(year: Int) = setDate(DateFilter.Year(year))

    /** No results: remove every filter (keeps the text). */
    fun clearFilters() = updateFilters { SearchFilters() }

    /** `Buscar en todas las carpetas` when scoped. */
    fun searchEverywhere() {
        _state.update { it.copy(scope = null) }
        updateFilters { it.copy(folder = null) }
    }

    fun showSheet(sheet: FilterSheet?) {
        _state.update { it.copy(sheet = sheet) }
        if (sheet == FilterSheet.Folder) folderBrowser.open(_state.value.filters.folder?.id)
    }

    private fun updateFilters(change: (SearchFilters) -> SearchFilters) {
        _state.update { it.copy(filters = change(it.filters), sheet = null) }
        runSearch(immediate = true)
    }

    fun retry() = runSearch(immediate = true)

    private fun runSearch(immediate: Boolean = false) {
        searchJob?.cancel()
        val snapshot = _state.value
        if (snapshot.idle) {
            _state.update { it.copy(loading = false, failed = false, results = emptyList(), nextCursor = null) }
            return
        }
        _state.update { it.copy(loading = true, failed = false) }
        searchJob = viewModelScope.launch {
            if (!immediate) delay(debounceMs)
            try {
                val (items, next) = fetch(snapshot, cursor = null)
                _state.update { it.copy(loading = false, results = items, nextCursor = next, indexing = items.any(::stillIndexing)) }
            } catch (error: ApiException) {
                _state.update { it.copy(loading = false, failed = true) }
            }
        }
    }

    fun loadMore() {
        val snapshot = _state.value
        val cursor = snapshot.nextCursor ?: return
        if (snapshot.loadingMore) return
        _state.update { it.copy(loadingMore = true) }
        viewModelScope.launch {
            try {
                val (items, next) = fetch(snapshot, cursor)
                _state.update { state ->
                    val known = state.results.map { it.type to it.id }.toSet()
                    state.copy(
                        loadingMore = false,
                        results = state.results + items.filter {
                            (it.type to it.id) !in known
                        },
                        nextCursor = next
                    )
                }
            } catch (error: ApiException) {
                _state.update { it.copy(loadingMore = false) }
            }
        }
    }

    private suspend fun fetch(state: SearchState, cursor: String?): Pair<List<SearchItemResponse>, String?> {
        val filters = state.filters
        val page = api.search(
            q = state.query.trim(),
            type = filters.kind?.type,
            folderId = filters.folder?.id,
            dateFrom = filters.date?.from?.toString(),
            dateTo = filters.date?.to?.toString(),
            limit = PAGE,
            cursor = cursor
        )
        val items = page.items.filter { item -> filters.kind?.accepts(item) ?: true }
        return items to page.nextCursor
    }

    /** Opens a hit the way Archivos would: media in the viewer, PDF/text in the reader, others in their folder. */
    fun open(item: SearchItemResponse) {
        recents.add(_state.value.query)
        when (item.type) {
            "folder" -> effects.trySend(SearchEffect.OpenFolder(item.id))

            "album" -> effects.trySend(SearchEffect.OpenAlbum(item.id))

            "photo", "video" -> item.assetId?.let { effects.trySend(SearchEffect.OpenViewer(it)) }

            else -> {
                val assetId = item.assetId ?: return
                viewModelScope.launch {
                    val asset = try {
                        files.asset(assetId)
                    } catch (error: ApiException) {
                        null
                    }
                    val effect = when (asset?.let { FileKinds.openKind(it) }) {
                        OpenKind.Image, OpenKind.Video -> SearchEffect.OpenViewer(assetId)
                        OpenKind.Pdf, OpenKind.Text -> SearchEffect.OpenDocument(assetId)
                        null -> SearchEffect.OpenDocument(assetId)
                        else -> SearchEffect.OpenFolder(asset.folderId)
                    }
                    effects.trySend(effect)
                }
            }
        }
    }

    /** OCR not done yet (embeddings are not used on Android, so they never count as pending). */
    private fun stillIndexing(item: SearchItemResponse): Boolean =
        item.processingState in setOf("created", "blob_stored", "metadata_extracted", "thumbnail_pending", "thumbnail_ready", "ocr_pending")

    companion object {
        const val DEBOUNCE_MS = 150L
        private const val PAGE = 50L
        private const val MAX_ALBUMS = 6
    }
}
