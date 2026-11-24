package dev.bento.feature.collections

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.paging.PagingData
import androidx.paging.cachedIn
import androidx.paging.map
import coil3.ImageLoader
import dagger.assisted.Assisted
import dagger.assisted.AssistedFactory
import dagger.assisted.AssistedInject
import dagger.hilt.android.lifecycle.HiltViewModel
import dev.bento.api.ApiException
import dev.bento.api.generated.AlbumResponse
import dev.bento.api.generated.AssetResponse
import dev.bento.api.generated.TelegramMediaResponse
import dev.bento.data.AlbumsRepository
import dev.bento.data.DocumentsRepository
import dev.bento.data.Invalidations
import dev.bento.data.OverlayStore
import dev.bento.data.PhoneFolder
import dev.bento.data.PhoneFoldersRepository
import dev.bento.data.SessionRepository
import dev.bento.data.TelegramMediaRepository
import dev.bento.data.TimelineRepository
import dev.bento.data.Topic
import dev.bento.data.TrashRepository
import dev.bento.designsystem.component.AvatarStatus
import dev.bento.feature.photos.AccountSummary
import dev.bento.feature.photos.GridCell
import dev.bento.feature.photos.MediaActions
import dev.bento.feature.photos.MediaFormat
import dev.bento.feature.photos.UiText
import dev.bento.feature.photos.ViewerSessions
import dev.bento.feature.photos.cellsOf
import dev.bento.feature.photos.toGridCells
import dev.bento.strings.R as StringsR
import javax.inject.Inject
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.longOrNull

/** Generic load state for list screens. */
sealed interface Loadable<out T> {
    data object Loading : Loadable<Nothing>

    data class Ready<T>(val value: T) : Loadable<T>

    data object Failed : Loadable<Nothing>
}

@HiltViewModel
class CollectionsViewModel @Inject constructor(
    albums: AlbumsRepository,
    private val session: SessionRepository,
    val imageLoader: ImageLoader
) : ViewModel() {
    val albums: Flow<PagingData<AlbumResponse>> = albums.albums().cachedIn(viewModelScope)
    private val _account = MutableStateFlow(AccountSummary(null, AvatarStatus.Idle))
    val account: StateFlow<AccountSummary> = _account.asStateFlow()

    init {
        viewModelScope.launch {
            runCatching { session.account() }.onSuccess { a ->
                _account.value =
                    AccountSummary(a.account?.displayName, if (a.step == "authorized") AvatarStatus.Idle else AvatarStatus.Attention)
            }
        }
    }
}

/** Album detail: its photos (newest first, with month/day headers), add/remove with undo. */
@HiltViewModel(assistedFactory = AlbumViewModel.Factory::class)
class AlbumViewModel @AssistedInject constructor(
    @Assisted val albumId: String,
    private val albums: AlbumsRepository,
    private val timeline: TimelineRepository,
    invalidations: Invalidations,
    val actions: MediaActions,
    val imageLoader: ImageLoader,
    val sessions: ViewerSessions
) : ViewModel() {
    @AssistedFactory
    interface Factory {
        fun create(albumId: String): AlbumViewModel
    }

    data class AlbumUi(val album: AlbumResponse, val assets: List<AssetResponse>)

    private val _state = MutableStateFlow<Loadable<AlbumUi>>(Loadable.Loading)
    private val removed = MutableStateFlow<Set<String>>(emptySet())

    /** The album with optimistic edits (favorite, trash, removal) applied. */
    val state: StateFlow<Loadable<AlbumUi>> = combine(_state, timeline.overlayChanges, removed) { s, changes, gone ->
        if (s !is Loadable.Ready) return@combine s
        Loadable.Ready(
            s.value.copy(
                assets = s.value.assets.filter { it.id !in gone && changes[it.id] !is OverlayStore.Change.Hide }.map(timeline::current)
            )
        )
    }.stateIn(viewModelScope, SharingStarted.Eagerly, Loadable.Loading)

    init {
        actions.bind(viewModelScope)
        load()
        invalidations.topics.filter { Topic.ALBUMS in it }.onEach { load() }.launchIn(viewModelScope)
    }

    fun load() {
        viewModelScope.launch {
            _state.value = try {
                val album = albums.album(albumId)
                val gate = Semaphore(8)
                val assets = coroutineScope {
                    album.assetIds.map { id -> async { gate.withPermit { runCatching { timeline.asset(id) }.getOrNull() } } }.awaitAll()
                }.filterNotNull().sortedByDescending { it.takenAt ?: it.createdAt }
                removed.value = emptySet()
                Loadable.Ready(AlbumUi(album, assets))
            } catch (error: ApiException) {
                if (_state.value is Loadable.Ready) _state.value else Loadable.Failed
            }
        }
    }

    fun remove(ids: List<String>, onUndo: (UiText, dev.bento.data.Undoable) -> Unit) {
        removed.value = removed.value + ids
        viewModelScope.launch {
            try {
                val undos = ids.map { albums.remove(albumId, it) }
                val combined = undos.singleOrNull() ?: dev.bento.data.optimistic({}, {}, {}, { undos.forEach { it.undo() } })
                onUndo(UiText(StringsR.string.collections_album_removed), combined)
            } catch (error: ApiException) {
                removed.value = removed.value - ids.toSet()
            }
        }
    }

    fun cells(assets: List<AssetResponse>): List<GridCell> = cellsOf(assets)
}

/** "Elige fotos": the whole timeline as a picker (Nuevo álbum, Añadir fotos). */
@HiltViewModel
class LibraryPickerViewModel @Inject constructor(
    timeline: TimelineRepository,
    val actions: MediaActions,
    val imageLoader: ImageLoader
) : ViewModel() {
    val layout = timeline.layout
    val cells: Flow<PagingData<GridCell>> = timeline.sharedPositional.map { it.toGridCells(dayHeaders = true) }.cachedIn(viewModelScope)
    val monthCells: Flow<PagingData<GridCell>> = timeline.sharedPositional.map {
        it.toGridCells(dayHeaders = false)
    }.cachedIn(viewModelScope)
    private val jump = timeline::jumpTo

    init {
        actions.bind(viewModelScope)
    }

    fun jumpTo(position: Int) = jump(position)
}

enum class MediaFilter { Favorites, Videos }

/** Favoritos / Videos: the timeline filtered on the phone. */
@HiltViewModel(assistedFactory = FilteredViewModel.Factory::class)
class FilteredViewModel @AssistedInject constructor(
    @Assisted val filter: MediaFilter,
    timeline: TimelineRepository,
    val actions: MediaActions,
    val imageLoader: ImageLoader,
    val sessions: ViewerSessions
) : ViewModel() {
    @AssistedFactory
    interface Factory {
        fun create(filter: MediaFilter): FilteredViewModel
    }

    private val pages = timeline.filteredTimeline(
        when (filter) {
            MediaFilter.Favorites -> { asset: AssetResponse -> asset.favorite }
            MediaFilter.Videos -> MediaFormat::isVideo
        },
        viewModelScope
    ).cachedIn(viewModelScope)
    val cells: Flow<PagingData<GridCell>> = pages.map { it.toGridCells(dayHeaders = true) }.cachedIn(viewModelScope)
    val monthCells: Flow<PagingData<GridCell>> = pages.map { it.toGridCells(dayHeaders = false) }.cachedIn(viewModelScope)

    init {
        actions.bind(viewModelScope)
    }
}

@HiltViewModel
class DocumentsViewModel @Inject constructor(
    private val documents: DocumentsRepository,
    val actions: MediaActions,
    private val timeline: TimelineRepository
) :
    ViewModel() {
    private val _state = MutableStateFlow<Loadable<DocumentsRepository.Result>>(Loadable.Loading)
    val state: StateFlow<Loadable<DocumentsRepository.Result>> = _state.asStateFlow()

    init {
        actions.bind(viewModelScope)
        load()
    }

    fun load() {
        viewModelScope.launch {
            _state.value = try {
                Loadable.Ready(documents.documents())
            } catch (error: ApiException) {
                Loadable.Failed
            }
        }
    }

    /** Opens a document with another app (decrypted copy, after the disclosure). */
    fun open(id: String) {
        viewModelScope.launch {
            val asset = runCatching { timeline.asset(id) }.getOrNull() ?: return@launch
            actions.export(dev.bento.feature.photos.Disclosure.OpenWith) { actions.openWith(asset) }
        }
    }
}

@HiltViewModel
class PhoneFoldersViewModel @Inject constructor(private val repository: PhoneFoldersRepository) : ViewModel() {
    private val _state = MutableStateFlow<Loadable<List<PhoneFolder>>>(Loadable.Loading)
    val state: StateFlow<Loadable<List<PhoneFolder>>> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            _state.value = try {
                Loadable.Ready(repository.folders().filter { it.kind == "media_store" || it.kind == "folder" })
            } catch (error: ApiException) {
                Loadable.Failed
            }
        }
    }
}

/** One chat's media for Importar de Telegram: kind filter, select all, import in background. */
@HiltViewModel(assistedFactory = TelegramMediaViewModel.Factory::class)
class TelegramMediaViewModel @AssistedInject constructor(
    @Assisted val chatId: Long,
    private val telegram: TelegramMediaRepository
) : ViewModel() {
    @AssistedFactory
    interface Factory {
        fun create(chatId: Long): TelegramMediaViewModel
    }

    data class MediaUi(val items: List<TelegramMediaResponse>, val nextCursor: String?, val loadingMore: Boolean = false)

    private val _state = MutableStateFlow<Loadable<MediaUi>>(Loadable.Loading)
    val state: StateFlow<Loadable<MediaUi>> = _state.asStateFlow()
    private val _kind = MutableStateFlow("all")
    val kind: StateFlow<String> = _kind.asStateFlow()
    private val _selected = MutableStateFlow<Set<Long>>(emptySet())
    val selected: StateFlow<Set<Long>> = _selected.asStateFlow()
    private val _done = MutableStateFlow(false)
    val done: StateFlow<Boolean> = _done.asStateFlow()

    init {
        load()
    }

    fun setKind(kind: String) {
        if (kind == _kind.value) return
        _kind.value = kind
        _selected.value = emptySet()
        load()
    }

    fun toggle(id: Long) {
        _selected.value = if (id in _selected.value) _selected.value - id else _selected.value + id
    }

    fun selectAll() {
        val items = (_state.value as? Loadable.Ready)?.value?.items.orEmpty()
        _selected.value = if (_selected.value.size == items.size) emptySet() else items.map { it.messageId }.toSet()
    }

    fun loadMore() {
        val ready = (_state.value as? Loadable.Ready)?.value ?: return
        val cursor = ready.nextCursor ?: return
        if (ready.loadingMore) return
        _state.value = Loadable.Ready(ready.copy(loadingMore = true))
        viewModelScope.launch {
            runCatching { telegram.media(chatId, cursor, _kind.value) }.onSuccess { page ->
                _state.value = Loadable.Ready(MediaUi(ready.items + page.items, page.nextCursor))
            }.onFailure { _state.value = Loadable.Ready(ready.copy(loadingMore = false)) }
        }
    }

    fun import() {
        val ids = _selected.value.toList()
        if (ids.isEmpty()) return
        viewModelScope.launch {
            runCatching { telegram.import(chatId, ids, all = false) }.onSuccess { _done.value = true }
        }
    }

    private fun load() {
        _state.value = Loadable.Loading
        viewModelScope.launch {
            _state.value = try {
                val page = telegram.media(chatId, null, _kind.value)
                Loadable.Ready(MediaUi(page.items, page.nextCursor))
            } catch (error: ApiException) {
                Loadable.Failed
            }
        }
    }
}

/** A trash entry (`/api/trash` is untyped in the schema). */
data class TrashItem(
    val id: String,
    val type: String,
    val name: String,
    val sizeBytes: Long,
    val deletedAt: String?,
    val purgeAt: String?,
    val hasThumbnail: Boolean
) {
    companion object {
        fun from(json: JsonObject): TrashItem? {
            fun str(key: String) = (json[key] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull
            val id = str("id") ?: return null
            return TrashItem(
                id = id,
                type = str("type") ?: "asset",
                name = str("name").orEmpty(),
                sizeBytes = (json["size_bytes"] as? JsonPrimitive)?.longOrNull ?: 0L,
                deletedAt = str("deleted_at"),
                purgeAt = str("purge_at"),
                hasThumbnail = str("thumbnail_url") != null
            )
        }

        /** Whole days left before [purgeAt] (0 = today), from [nowMs]. */
        fun daysLeft(purgeAt: String?, nowMs: Long): Int? {
            val instant = purgeAt?.let { runCatching { java.time.OffsetDateTime.parse(it).toInstant() }.getOrNull() } ?: return null
            val millis = instant.toEpochMilli() - nowMs
            return (millis / 86_400_000L).toInt().coerceAtLeast(0)
        }
    }
}

@HiltViewModel
class TrashViewModel @Inject constructor(
    private val trash: TrashRepository,
    private val timeline: TimelineRepository,
    val imageLoader: ImageLoader
) : ViewModel() {
    val items: Flow<PagingData<TrashItem>> = trash.items().map { data ->
        data.map {
            TrashItem.from(it)
                ?: TrashItem("", "", "", 0, null, null, false)
        }
    }
        .cachedIn(viewModelScope)
    private val _summary = MutableStateFlow<Pair<Int, Long>?>(null)
    val summary: StateFlow<Pair<Int, Long>?> = _summary.asStateFlow()
    private val _message = MutableStateFlow<UiText?>(null)
    val message: StateFlow<UiText?> = _message.asStateFlow()

    fun messageShown() {
        _message.value = null
    }

    fun loadSummary() {
        viewModelScope.launch { _summary.value = runCatching { trash.summary() }.getOrNull() }
    }

    private val _undo = MutableStateFlow<Pair<UiText, dev.bento.data.Undoable>?>(null)

    /** Restoring is reversible too (product/android.md §1.5): `Deshacer` sends it back to the trash. */
    val undo: StateFlow<Pair<UiText, dev.bento.data.Undoable>?> = _undo.asStateFlow()

    fun undoShown() {
        _undo.value = null
    }

    fun restore(ids: List<String>) {
        viewModelScope.launch {
            try {
                val undoable = dev.bento.data.optimistic({}, {}, remote = { trash.restore(ids) }, inverse = { timeline.trash(ids) })
                _undo.value = UiText(StringsR.string.collections_trash_restored) to undoable
            } catch (error: ApiException) {
                _message.value = UiText(StringsR.string.photos_action_failed)
            }
        }
    }

    fun purge(ids: List<String>) = run(StringsR.string.collections_trash_purged) { trash.purge(ids) }

    fun empty() = run(StringsR.string.collections_trash_emptied) { trash.empty() }

    private fun run(done: Int, block: suspend () -> Unit) {
        viewModelScope.launch {
            _message.value = try {
                block()
                UiText(done)
            } catch (error: ApiException) {
                UiText(StringsR.string.photos_action_failed)
            }
        }
    }
}
