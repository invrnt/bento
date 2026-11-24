package dev.bento.feature.viewer

import android.content.Context
import androidx.annotation.OptIn
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.paging.Pager
import androidx.paging.PagingConfig
import androidx.paging.PagingData
import androidx.paging.PagingSource
import androidx.paging.PagingState
import androidx.paging.cachedIn
import androidx.paging.filter
import androidx.paging.map
import coil3.ImageLoader
import dagger.assisted.Assisted
import dagger.assisted.AssistedFactory
import dagger.assisted.AssistedInject
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import dev.bento.api.ApiException
import dev.bento.api.BentoMediaUris
import dev.bento.api.bentoDataSourceFactory
import dev.bento.api.di.LoopbackClient
import dev.bento.api.generated.AlbumResponse
import dev.bento.api.generated.AssetResponse
import dev.bento.data.AlbumsRepository
import dev.bento.data.DriveRepository
import dev.bento.data.OverlayStore
import dev.bento.data.TimelineEntry
import dev.bento.data.TimelineRepository
import dev.bento.engine.BentoEngine
import dev.bento.engine.EngineState
import dev.bento.feature.photos.MediaActions
import dev.bento.feature.photos.UiText
import dev.bento.feature.photos.ViewerSessions
import dev.bento.feature.photos.ViewerSource
import dev.bento.strings.R as StringsR
import java.util.Locale
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient

/** Route arguments: the asset, its position in the source, and the grid's session token (null: timeline). */
data class ViewerArgs(val assetId: String, val position: Int, val session: String?)

/** Everything the info sheet shows beyond the DTO (loaded when it opens). */
data class ViewerInfo(
    val assetId: String,
    val exif: ExifSummary? = null,
    val folderPath: String? = null,
    val albums: List<AlbumResponse> = emptyList(),
    val pinned: Boolean? = null,
    val loaded: Boolean = false
)

@OptIn(UnstableApi::class)
@HiltViewModel(assistedFactory = ViewerViewModel.Factory::class)
class ViewerViewModel @AssistedInject constructor(
    @Assisted val args: ViewerArgs,
    private val timeline: TimelineRepository,
    private val albums: AlbumsRepository,
    private val drive: DriveRepository,
    private val exif: ExifReader,
    private val sessions: ViewerSessions,
    @ApplicationContext private val context: Context,
    @LoopbackClient private val client: OkHttpClient,
    private val engine: BentoEngine,
    val actions: MediaActions,
    val imageLoader: ImageLoader
) : ViewModel() {
    @AssistedFactory
    interface Factory {
        fun create(args: ViewerArgs): ViewerViewModel
    }

    init {
        actions.bind(viewModelScope)
    }

    private val source: ViewerSource? = if (args.session == null &&
        args.position >= 0
    ) {
        ViewerSource.Timeline
    } else {
        sessions.source(args.session)
    }

    /** Pages of the current collection (placeholders for the whole timeline), with optimistic edits applied. */
    val pages: Flow<PagingData<AssetResponse>> = when (val s = source) {
        ViewerSource.Timeline -> timeline.sharedPositional.map { data ->
            data.filter { it is TimelineEntry.Photo }.map { (it as TimelineEntry.Photo).asset }
        }

        is ViewerSource.Snapshot -> combine(flowOf(s.assets), timeline.overlayChanges) { list, changes ->
            PagingData.from(list.filterNot { changes[it.id] is OverlayStore.Change.Hide }.map(timeline::current))
        }

        is ViewerSource.Ids -> combine(
            Pager(PagingConfig(pageSize = 20, initialLoadSize = 20, enablePlaceholders = true)) {
                IdsPagingSource(s.ids, args.position) { id -> timeline.asset(id) }
            }.flow,
            timeline.overlayChanges
        ) { data, changes -> data.filter { changes[it.id] !is OverlayStore.Change.Hide }.map(timeline::current) }

        null -> combine(
            flow {
                emit(runCatching { timeline.asset(args.assetId) }.getOrNull())
            },
            timeline.overlayChanges
        ) { asset, changes ->
            PagingData.from(listOfNotNull(asset?.takeIf { changes[it.id] !is OverlayStore.Change.Hide }?.let(timeline::current)))
        }
    }.cachedIn(viewModelScope)

    /** Initial page: the tile's position (timeline/snapshot order), or the asset's index in a snapshot. */
    val initialPage: Int = when (val s = source) {
        is ViewerSource.Snapshot -> s.assets.indexOfFirst { it.id == args.assetId }.coerceAtLeast(0)
        null -> 0
        else -> args.position.coerceAtLeast(0)
    }

    /** The tapped asset (first frame before pages arrive), when the grid handed it over. */
    val opening: AssetResponse? =
        sessions.opening(args.assetId) ?: (source as? ViewerSource.Snapshot)?.assets?.firstOrNull { it.id == args.assetId }

    /** Page count known up front (the pager exists at the right page on the first frame). */
    val expectedCount: Int = when (val s = source) {
        ViewerSource.Timeline -> timeline.layout.value.total
        is ViewerSource.Snapshot -> s.assets.size
        is ViewerSource.Ids -> s.ids.size
        null -> 1
    }

    private val _info = MutableStateFlow<ViewerInfo?>(null)
    val info: StateFlow<ViewerInfo?> = _info.asStateFlow()

    private val _message = MutableStateFlow<UiText?>(null)
    val message: StateFlow<UiText?> = _message.asStateFlow()

    fun messageShown() {
        _message.value = null
    }

    /** The page settled on [asset] at [position]: remember it for the way back to the grid. */
    fun onCurrent(asset: AssetResponse, position: Int) {
        sessions.reportPosition(asset.id, position)
        if (_info.value?.assetId != asset.id) _info.value = null
    }

    fun loadInfo(asset: AssetResponse, locale: Locale) {
        if (_info.value?.assetId == asset.id && _info.value?.loaded == true) return
        _info.value = ViewerInfo(asset.id)
        viewModelScope.launch {
            coroutineScope {
                // The backend's summary first; the original's header is read here only when it is already on the phone.
                val exifJob = async {
                    asset.exif?.let { ExifSummary.from(it, locale) } ?: if (asset.locallyAvailable) exif.read(asset, locale) else null
                }
                val pathJob = async { runCatching { drive.pathOf(asset.id) }.getOrNull() }
                val albumsJob = async { runCatching { albums.albumsContaining(asset.id) }.getOrDefault(emptyList()) }
                val (exifValue, path, inAlbums) = awaitAll(exifJob, pathJob, albumsJob)
                @Suppress("UNCHECKED_CAST")
                if (_info.value?.assetId == asset.id) {
                    _info.value =
                        ViewerInfo(
                            asset.id,
                            exifValue as ExifSummary?,
                            path as String?,
                            inAlbums as List<AlbumResponse>,
                            _info.value?.pinned,
                            loaded = true
                        )
                }
            }
        }
    }

    fun setOffline(asset: AssetResponse, pinned: Boolean) {
        viewModelScope.launch {
            try {
                val now = timeline.setOffline(asset.id, pinned)
                _info.value = (_info.value?.takeIf { it.assetId == asset.id } ?: ViewerInfo(asset.id)).copy(pinned = now)
                if (now) _message.value = UiText(StringsR.string.viewer_offline_saved)
            } catch (error: ApiException) {
                _message.value = UiText(StringsR.string.common_error_generic)
            }
        }
    }

    // --- Video ---------------------------------------------------------------------------------------------------

    private var exo: ExoPlayer? = null

    /** One player for the viewer (survives rotation and PiP), streaming `/content` with Range through the loopback. */
    val player: ExoPlayer
        get() = exo ?: ExoPlayer.Builder(context)
            .setMediaSourceFactory(DefaultMediaSourceFactory(bentoDataSourceFactory(client) { engine.state.value as? EngineState.Ready }))
            .setAudioAttributes(AudioAttributes.Builder().setUsage(C.USAGE_MEDIA).setContentType(C.AUDIO_CONTENT_TYPE_MOVIE).build(), true)
            .setHandleAudioBecomingNoisy(true)
            .build()
            .also { exo = it }

    private var playingId: String? = null

    fun prepareVideo(asset: AssetResponse, autoplay: Boolean) {
        if (playingId == asset.id) return
        playingId = asset.id
        player.setMediaItem(
            MediaItem.Builder().setUri(BentoMediaUris.asset(asset.id)).setMimeType(asset.mimeType).setMediaId(asset.id).build()
        )
        player.prepare()
        player.playWhenReady = autoplay
    }

    fun stopVideo() {
        playingId = null
        exo?.stop()
        exo?.clearMediaItems()
    }

    override fun onCleared() {
        exo?.release()
        exo = null
    }
}

/** Pages over a fixed list of ids (album order), loading each asset by id; placeholders keep the count exact. */
internal class IdsPagingSource(
    private val ids: List<String>,
    private val initial: Int,
    private val fetch: suspend (String) -> AssetResponse
) : PagingSource<Int, AssetResponse>() {
    override val jumpingSupported: Boolean = true

    override suspend fun load(params: LoadParams<Int>): LoadResult<Int, AssetResponse> = try {
        val start = when (params) {
            is LoadParams.Refresh -> (params.key ?: initial).coerceIn(0, (ids.size - 1).coerceAtLeast(0))
            is LoadParams.Append -> params.key
            is LoadParams.Prepend -> (params.key - params.loadSize).coerceAtLeast(0)
        }
        val end = when (params) {
            is LoadParams.Prepend -> params.key
            else -> (start + params.loadSize).coerceAtMost(ids.size)
        }
        val assets = coroutineScope { ids.subList(start, end).map { id -> async { runCatching { fetch(id) }.getOrNull() } }.awaitAll() }
        LoadResult.Page(
            data = assets.filterNotNull(),
            prevKey = start.takeIf { it > 0 },
            nextKey = end.takeIf { it < ids.size },
            itemsBefore = start,
            itemsAfter = ids.size - end
        )
    } catch (error: ApiException) {
        LoadResult.Error(error)
    }

    override fun getRefreshKey(state: PagingState<Int, AssetResponse>): Int? = state.anchorPosition
}
