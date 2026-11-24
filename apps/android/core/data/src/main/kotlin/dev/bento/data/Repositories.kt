package dev.bento.data

import androidx.paging.Pager
import androidx.paging.PagingConfig
import androidx.paging.PagingData
import androidx.paging.cachedIn
import androidx.paging.filter
import androidx.paging.insertSeparators
import androidx.paging.map
import dev.bento.api.generated.AlbumCreateRequest
import dev.bento.api.generated.AlbumItemRequest
import dev.bento.api.generated.AlbumResponse
import dev.bento.api.generated.AssetMoveRequest
import dev.bento.api.generated.AssetPatchRequest
import dev.bento.api.generated.AssetResponse
import dev.bento.api.generated.BentoEndpoints
import dev.bento.api.generated.DeviceRemovalPreviewResponse
import dev.bento.api.generated.DeviceRemovalRequest
import dev.bento.api.generated.DeviceRemovalResponse
import dev.bento.api.generated.DeviceRenameRequest
import dev.bento.api.generated.DeviceResponse
import dev.bento.api.generated.DriveItemResponse
import dev.bento.api.generated.FavoriteRequest
import dev.bento.api.generated.FolderCreateRequest
import dev.bento.api.generated.FolderResponse
import dev.bento.api.generated.SearchItemResponse
import dev.bento.api.generated.SearchResultType
import dev.bento.api.generated.SettingsResponse
import dev.bento.api.generated.TrashIdsRequest
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull

/** A row of the photo grid: day headers interleaved with photos (stable keys for Compose). */
sealed interface TimelineEntry {
    val key: String

    data class Day(val date: String) : TimelineEntry {
        override val key = "day:$date"
    }

    data class Photo(val date: String, val asset: AssetResponse) : TimelineEntry {
        override val key = "asset:${asset.id}"
    }
}

/** Fast-scroller month entry (api/android-endpoints.md §5 `GET /photos/timeline/index`). */
data class MonthIndexEntry(val month: String, val count: Int, val firstCursor: String?)

/** Fotos: the timeline, its month index, favorites and trash with undo. */
class TimelineRepository(
    private val api: BentoEndpoints,
    private val invalidations: Invalidations,
    private val uiCache: UiCache,
    private val scope: CoroutineScope
) {
    private val overlay = OverlayStore<AssetResponse>()

    /** First screen from the UI cache (cold start), or null. */
    fun cachedFirstScreen(): List<AssetResponse>? = uiCache.read(CACHE_KEY, AssetResponse.serializer())

    /**
     * The timeline with day separators and optimistic edits. [cacheScope] owns the page cache (a view model scope);
     * the overlay is combined after `cachedIn` so each optimistic change re-presents cached pages instead of
     * re-collecting a spent PagingData.
     */
    fun timeline(pageSize: Int = PageSizes.GRID, cacheScope: CoroutineScope = scope): Flow<PagingData<TimelineEntry>> {
        val factory = invalidations.pagingFactory(scope, Topic.TIMELINE) { CursorPagingSource(::fetchPhotos) }
        val pages = Pager(
            PagingConfig(pageSize = pageSize, initialLoadSize = pageSize, enablePlaceholders = false),
            pagingSourceFactory = factory
        ).flow
        return decorate(pages, cacheScope, daySeparators = true)
    }

    private val jumps = java.util.concurrent.atomic.AtomicReference<Int?>(null)
    private val _layout = MutableStateFlow(TimelineLayout.EMPTY)

    /** Photo positions per month of the current positional timeline (fast scroller, sticky month header). */
    val layout: StateFlow<TimelineLayout> = _layout.asStateFlow()

    @Volatile private var positionalFactory: androidx.paging.InvalidatingPagingSourceFactory<Int, TimelineEntry.Photo>? = null

    /**
     * The whole timeline with placeholders (positions from the month index, [layout]): the grid knows its full
     * height and the fast scroller jumps by index. Day separators are interleaved like [timeline].
     */
    fun positionalTimeline(pageSize: Int = PageSizes.GRID): Flow<PagingData<TimelineEntry>> {
        val factory = invalidations.pagingFactory(scope, Topic.TIMELINE) {
            TimelinePositionalSource(::fetchPhotos, ::monthIndex, { _layout.value = it }, jumps)
        }
        positionalFactory = factory
        val pages = Pager(
            PagingConfig(
                pageSize = pageSize,
                initialLoadSize = pageSize * 2,
                prefetchDistance = pageSize,
                enablePlaceholders = true,
                maxSize = pageSize * 12,
                jumpThreshold = pageSize * 4
            ),
            pagingSourceFactory = factory
        ).flow
        return decorate(pages, scope, daySeparators = true)
    }

    /**
     * One positional timeline shared by Fotos and the viewer (application scope): the viewer pages through the very
     * pages the grid already loaded, so opening it never refetches.
     */
    val sharedPositional: Flow<PagingData<TimelineEntry>> by lazy { positionalTimeline().cachedIn(scope) }

    /** Reload the positional timeline so that its first page starts exactly at photo [position]. */
    fun jumpTo(position: Int) {
        jumps.set(position)
        positionalFactory?.invalidate()
    }

    /** Favoritos / Videos: the timeline filtered on the device (the backend has no filter yet). */
    fun filteredTimeline(
        predicate: (AssetResponse) -> Boolean,
        cacheScope: CoroutineScope,
        pageSize: Int = PageSizes.GRID
    ): Flow<PagingData<TimelineEntry>> {
        val factory = invalidations.pagingFactory(scope, Topic.TIMELINE) {
            FilteredTimelineSource(::fetchPhotos, { predicate(it.asset) })
        }
        val pages = Pager(PagingConfig(pageSize = pageSize, enablePlaceholders = false), pagingSourceFactory = factory).flow
        return decorate(pages, cacheScope, daySeparators = true, keep = predicate)
    }

    private suspend fun fetchPhotos(cursor: String?, limit: Int): CursorPage<TimelineEntry.Photo> {
        val page = api.photosTimeline(cursor = cursor, limit = limit.toLong())
        val items = page.groups.flatMap { group -> group.assets.map { TimelineEntry.Photo(group.date, it) } }
        if (cursor == null) uiCache.write(CACHE_KEY, items.take(UiCache.MAX_ITEMS).map { it.asset }, AssetResponse.serializer())
        return CursorPage(items, page.nextCursor)
    }

    /** Optimistic overlay (favorite, trash) + day separators over raw photo pages. */
    private fun decorate(
        pages: Flow<PagingData<TimelineEntry.Photo>>,
        cacheScope: CoroutineScope,
        daySeparators: Boolean,
        keep: (AssetResponse) -> Boolean = { true }
    ): Flow<PagingData<TimelineEntry>> = combine(pages.cachedIn(cacheScope), overlay.changes) { data, changes ->
        val visible = data.filter { !overlay.isHidden(it.asset.id, changes) }
            .map { photo -> photo.copy(asset = overlay.apply(photo.asset.id, photo.asset, changes)) }
            .filter { keep(it.asset) }
            .map { it as TimelineEntry }
        if (!daySeparators) {
            visible
        } else {
            visible.insertSeparators { before, after ->
                val next = after as? TimelineEntry.Photo ?: return@insertSeparators null
                if ((before as? TimelineEntry.Photo)?.date == next.date) null else TimelineEntry.Day(next.date)
            }
        }
    }

    /** Optimistic favorite for several photos (selection bar) with one undo. */
    suspend fun setFavorite(assets: List<AssetResponse>, favorite: Boolean): Undoable = optimistic(
        applyLocal = { assets.forEach { overlay.replace(it.id, it.copy(favorite = favorite)) } },
        rollbackLocal = { assets.forEach { overlay.clear(it.id) } },
        remote = { assets.forEach { api.setPhotoFavorite(it.id, FavoriteRequest(favorite)) } },
        inverse = { assets.forEach { api.setPhotoFavorite(it.id, FavoriteRequest(it.favorite)) } },
        onSettled = { invalidations.invalidate(Topic.TIMELINE, Topic.ALBUMS, Topic.SEARCH) }
    )

    /** Move several photos to the trash with one undo. */
    suspend fun trash(assetIds: List<String>): Undoable = optimistic(
        applyLocal = { assetIds.forEach(overlay::hide) },
        rollbackLocal = { assetIds.forEach(overlay::clear) },
        remote = { assetIds.forEach { api.deleteAsset(it) } },
        inverse = { api.restoreTrash(TrashIdsRequest(ids = assetIds)) },
        onSettled = { invalidations.invalidate(Topic.TIMELINE, Topic.DRIVE, Topic.TRASH, Topic.SEARCH, Topic.ALBUMS) }
    )

    /** Rename a photo (viewer info sheet / Renombrar) with undo. */
    suspend fun rename(asset: AssetResponse, name: String): Undoable = optimistic(
        applyLocal = { overlay.replace(asset.id, asset.copy(filename = name)) },
        rollbackLocal = { overlay.clear(asset.id) },
        remote = { api.renameDriveAsset(asset.id, AssetPatchRequest(name = name)) },
        inverse = { api.renameDriveAsset(asset.id, AssetPatchRequest(name = asset.filename)) },
        onSettled = { invalidations.invalidate(Topic.TIMELINE, Topic.DRIVE, Topic.SEARCH) }
    )

    /** The latest optimistic view of [asset] (viewer pages render from paging snapshots). */
    fun current(asset: AssetResponse): AssetResponse = overlay.apply(asset.id, asset)

    /** Live optimistic changes (the viewer re-reads its current item when these change). */
    val overlayChanges: StateFlow<Map<String, OverlayStore.Change<AssetResponse>>> get() = overlay.changes

    /** Month index for the fast scroller: one grouped query on the backend (`GET /photos/timeline/index`). */
    suspend fun monthIndex(): List<MonthIndexEntry> = api.photosTimelineIndex().months.map { month ->
        MonthIndexEntry(month.month, month.count.toInt(), month.firstCursor)
    }

    /** Optimistic favorite with undo. */
    suspend fun setFavorite(asset: AssetResponse, favorite: Boolean): Undoable = optimistic(
        applyLocal = { overlay.replace(asset.id, asset.copy(favorite = favorite)) },
        rollbackLocal = { overlay.clear(asset.id) },
        remote = { api.setPhotoFavorite(asset.id, FavoriteRequest(favorite)) },
        inverse = { api.setPhotoFavorite(asset.id, FavoriteRequest(!favorite)) },
        onSettled = { invalidations.invalidate(Topic.TIMELINE, Topic.ALBUMS, Topic.SEARCH) }
    )

    /** Move to trash immediately (hidden locally), `Deshacer` restores it. */
    suspend fun trash(assetId: String): Undoable = optimistic(
        applyLocal = { overlay.hide(assetId) },
        rollbackLocal = { overlay.clear(assetId) },
        remote = { api.deleteAsset(assetId) },
        inverse = { api.restoreTrash(TrashIdsRequest(ids = listOf(assetId))) },
        onSettled = { invalidations.invalidate(Topic.TIMELINE, Topic.DRIVE, Topic.TRASH, Topic.SEARCH, Topic.ALBUMS) }
    )

    suspend fun asset(assetId: String): AssetResponse = api.photoDetail(assetId)

    /** `Disponible sin conexión`: pin (downloads the original, excluded from eviction) or unpin. Returns pinned. */
    suspend fun setOffline(assetId: String, pinned: Boolean): Boolean =
        (if (pinned) api.pinAssetOffline(assetId) else api.unpinAssetOffline(assetId)).pinned

    companion object {
        const val CACHE_KEY = "fotos"
    }
}

/** Archivos (Drive): folder listings and file operations. */
class DriveRepository(
    private val api: BentoEndpoints,
    private val invalidations: Invalidations,
    private val uiCache: UiCache,
    private val scope: CoroutineScope
) {
    private val overlay = OverlayStore<DriveItemResponse>()

    fun cachedRoot(): List<DriveItemResponse>? = uiCache.read(CACHE_KEY, DriveItemResponse.serializer())

    fun items(folderId: String?, pageSize: Int = PageSizes.LIST): Flow<PagingData<DriveItemResponse>> {
        val factory = invalidations.pagingFactory(scope, Topic.DRIVE) {
            CursorPagingSource { cursor, limit ->
                val page = api.driveItems(folderId = folderId, cursor = cursor, limit = limit.toLong())
                if (cursor == null && folderId == null) uiCache.write(CACHE_KEY, page.items, DriveItemResponse.serializer())
                CursorPage(page.items, page.nextCursor)
            }
        }
        val pages = Pager(PagingConfig(pageSize = pageSize, enablePlaceholders = false), pagingSourceFactory = factory).flow
        return combine(pages, overlay.changes) { data, changes ->
            data.filter { !overlay.isHidden(it.id, changes) }.map { overlay.apply(it.id, it, changes) }
        }
    }

    /** Drive path of an asset or folder ("/Fotos/2024"), or null when unknown. */
    suspend fun pathOf(id: String): String? {
        val root = api.drivePaths(dev.bento.api.generated.DrivePathsRequest(ids = listOf(id))) as? JsonObject ?: return null
        return ((root["paths"] as? JsonObject)?.get(id) as? kotlinx.serialization.json.JsonPrimitive)?.contentOrNull
    }

    /** Subfolders of [folderId] (root when null), for folder pickers; reads up to [maxPages] pages. */
    suspend fun folders(folderId: String?, maxPages: Int = 10): List<DriveItemResponse> {
        val out = ArrayList<DriveItemResponse>()
        var cursor: String? = null
        repeat(maxPages) {
            val page = api.driveItems(folderId = folderId, cursor = cursor, limit = 200)
            out += page.items.filter { it.folder != null }
            cursor = page.nextCursor ?: return out
        }
        return out
    }

    suspend fun createFolder(name: String, parentId: String?): FolderResponse =
        api.createFolder(FolderCreateRequest(name = name, parentId = parentId)).also { invalidations.invalidate(Topic.DRIVE) }

    suspend fun rename(item: DriveItemResponse, name: String): Undoable {
        val previous = item.name
        return optimistic(
            applyLocal = { overlay.replace(item.id, item.copy(name = name)) },
            rollbackLocal = { overlay.clear(item.id) },
            remote = { renameRemote(item, name) },
            inverse = { renameRemote(item, previous) },
            onSettled = { invalidations.invalidate(Topic.DRIVE, Topic.SEARCH) }
        )
    }

    suspend fun move(assetId: String, toFolderId: String?, fromFolderId: String?): Undoable = optimistic(
        applyLocal = { overlay.hide(assetId) },
        rollbackLocal = { overlay.clear(assetId) },
        remote = { api.moveDriveAsset(assetId, AssetMoveRequest(folderId = toFolderId)) },
        inverse = { api.moveDriveAsset(assetId, AssetMoveRequest(folderId = fromFolderId)) },
        onSettled = { invalidations.invalidate(Topic.DRIVE) }
    )

    suspend fun trash(item: DriveItemResponse): Undoable = optimistic(
        applyLocal = { overlay.hide(item.id) },
        rollbackLocal = { overlay.clear(item.id) },
        remote = { if (item.folder != null) api.deleteFolder(item.id) else api.deleteAsset(item.id) },
        inverse = { api.restoreTrash(TrashIdsRequest(ids = listOf(item.id))) },
        onSettled = { invalidations.invalidate(Topic.DRIVE, Topic.TRASH, Topic.TIMELINE, Topic.SEARCH) }
    )

    private suspend fun renameRemote(item: DriveItemResponse, name: String) {
        if (item.folder != null) {
            api.updateFolder(item.id, dev.bento.api.generated.FolderPatchRequest(name = name))
        } else {
            api.renameDriveAsset(item.id, AssetPatchRequest(name = name))
        }
    }

    companion object {
        const val CACHE_KEY = "archivos"
    }
}

/** Search filters (`GET /api/search`). */
data class SearchQuery(
    val text: String,
    val type: SearchResultType? = null,
    val folderId: String? = null,
    val dateFrom: String? = null,
    val dateTo: String? = null
)

class SearchRepository(private val api: BentoEndpoints, private val invalidations: Invalidations, private val scope: CoroutineScope) {
    fun search(query: SearchQuery, pageSize: Int = PageSizes.SEARCH): Flow<PagingData<SearchItemResponse>> {
        val factory = invalidations.pagingFactory(scope, Topic.SEARCH) {
            CursorPagingSource { cursor, limit ->
                val page = api.search(
                    q = query.text,
                    type = query.type,
                    folderId = query.folderId,
                    dateFrom = query.dateFrom,
                    dateTo = query.dateTo,
                    limit = limit.coerceAtMost(MAX_LIMIT).toLong(),
                    cursor = cursor
                )
                CursorPage(page.items, page.nextCursor)
            }
        }
        return Pager(
            PagingConfig(
                pageSize = pageSize.coerceAtMost(MAX_LIMIT),
                initialLoadSize = pageSize.coerceAtMost(MAX_LIMIT),
                enablePlaceholders = false
            ),
            pagingSourceFactory = factory
        ).flow
    }

    private companion object {
        const val MAX_LIMIT = 100
    }
}

class AlbumsRepository(private val api: BentoEndpoints, private val invalidations: Invalidations, private val scope: CoroutineScope) {
    fun albums(pageSize: Int = PageSizes.LIST): Flow<PagingData<AlbumResponse>> {
        val factory = invalidations.pagingFactory(scope, Topic.ALBUMS) {
            CursorPagingSource { cursor, limit ->
                val page = api.listAlbums(cursor = cursor, limit = limit.toLong())
                CursorPage(page.items, page.nextCursor)
            }
        }
        return Pager(PagingConfig(pageSize = pageSize, enablePlaceholders = false), pagingSourceFactory = factory).flow
    }

    suspend fun album(albumId: String): AlbumResponse = api.albumDetail(albumId)

    /** Albums that contain [assetId] (viewer info sheet; the backend has no reverse lookup, albums are few). */
    suspend fun albumsContaining(assetId: String, maxPages: Int = 10): List<AlbumResponse> {
        val out = ArrayList<AlbumResponse>()
        var cursor: String? = null
        repeat(maxPages) {
            val page = page(cursor)
            out += page.items.filter { assetId in it.assetIds }
            cursor = page.nextCursor ?: return out
        }
        return out
    }

    /** One page of albums (sheets that list every album without Paging). */
    suspend fun page(cursor: String?, limit: Int = 100): CursorPage<AlbumResponse> =
        api.listAlbums(cursor = cursor, limit = limit.toLong()).let { CursorPage(it.items, it.nextCursor) }

    suspend fun create(title: String): AlbumResponse = api.createAlbum(AlbumCreateRequest(title)).also {
        invalidations.invalidate(Topic.ALBUMS)
    }

    suspend fun add(albumId: String, assetId: String): Undoable = optimistic(
        applyLocal = {},
        rollbackLocal = {},
        remote = { api.addAlbumItem(albumId, AlbumItemRequest(assetId)) },
        inverse = { api.removeAlbumItem(albumId, assetId) },
        onSettled = { invalidations.invalidate(Topic.ALBUMS) }
    )

    /** Adds several photos (selection bar, album picker) with one undo; already-present photos stay. */
    suspend fun addAll(albumId: String, assetIds: List<String>): Undoable {
        val before = api.albumDetail(albumId).assetIds.toSet()
        val added = assetIds.filterNot { it in before }
        return optimistic(
            applyLocal = {},
            rollbackLocal = {},
            remote = { added.forEach { api.addAlbumItem(albumId, AlbumItemRequest(it)) } },
            inverse = { added.forEach { api.removeAlbumItem(albumId, it) } },
            onSettled = { invalidations.invalidate(Topic.ALBUMS) }
        )
    }

    /** Nuevo álbum: create it, then add the picked photos. */
    suspend fun createWith(title: String, assetIds: List<String>): AlbumResponse {
        val album = api.createAlbum(AlbumCreateRequest(title))
        var latest = album
        assetIds.forEach { latest = api.addAlbumItem(album.id, AlbumItemRequest(it)) }
        invalidations.invalidate(Topic.ALBUMS)
        return latest
    }

    suspend fun remove(albumId: String, assetId: String): Undoable = optimistic(
        applyLocal = {},
        rollbackLocal = {},
        remote = { api.removeAlbumItem(albumId, assetId) },
        inverse = { api.addAlbumItem(albumId, AlbumItemRequest(assetId)) },
        onSettled = { invalidations.invalidate(Topic.ALBUMS) }
    )
}

/**
 * Papelera. `/api/trash` has no response model in the OpenAPI schema yet, so items are [JsonObject]s with
 * the backend's keys (`id`, …); a typed DTO appears automatically once the route declares one.
 */
class TrashRepository(private val api: BentoEndpoints, private val invalidations: Invalidations, private val scope: CoroutineScope) {
    fun items(pageSize: Int = PageSizes.LIST): Flow<PagingData<JsonObject>> {
        val factory = invalidations.pagingFactory(scope, Topic.TRASH) {
            CursorPagingSource { cursor, limit -> untypedPage(api.listTrash(cursor = cursor, limit = limit.toLong())) }
        }
        return Pager(PagingConfig(pageSize = pageSize, enablePlaceholders = false), pagingSourceFactory = factory).flow
    }

    /** Count and bytes of everything in the trash (Vaciar papelera confirmation), reading at most [maxPages] pages. */
    suspend fun summary(maxPages: Int = 40): Pair<Int, Long> {
        var cursor: String? = null
        var count = 0
        var bytes = 0L
        repeat(maxPages) {
            val page = untypedPage(api.listTrash(cursor = cursor, limit = 200))
            count += page.items.size
            bytes +=
                page.items.sumOf { (it["size_bytes"] as? kotlinx.serialization.json.JsonPrimitive)?.contentOrNull?.toLongOrNull() ?: 0L }
            cursor = page.nextCursor ?: return count to bytes
        }
        return count to bytes
    }

    suspend fun restore(ids: List<String>) {
        api.restoreTrash(TrashIdsRequest(ids = ids))
        invalidations.invalidate(Topic.TRASH, Topic.TIMELINE, Topic.DRIVE, Topic.SEARCH)
    }

    suspend fun purge(ids: List<String>) {
        api.purgeTrash(TrashIdsRequest(ids = ids))
        invalidations.invalidate(Topic.TRASH)
    }

    suspend fun empty() {
        api.emptyTrash()
        invalidations.invalidate(Topic.TRASH)
    }
}

/** Parses `{items: [...], next_cursor}` from an untyped response. */
internal fun untypedPage(element: JsonElement): CursorPage<JsonObject> {
    val root = element as? JsonObject ?: return CursorPage(emptyList(), null)
    val items = (root["items"] as? JsonArray).orEmpty().filterIsInstance<JsonObject>()
    val next = (root["next_cursor"] as? kotlinx.serialization.json.JsonPrimitive)?.contentOrNull
    return CursorPage(items, next)
}

/** Cuenta y actividad: the activity feed and sync status. */
class ActivityRepository(private val api: BentoEndpoints) {
    /** `/api/activity` (untyped in the schema today). */
    suspend fun activity(): JsonObject = api.getActivity() as? JsonObject ?: JsonObject(emptyMap())

    suspend fun syncStatus() = api.syncStatus()

    suspend fun syncNow() = api.syncNow()

    suspend fun jobs(cursor: String? = null) = api.listJobs(cursor = cursor)

    suspend fun retryJob(jobId: String) = api.retryJob(jobId)
}

class DevicesRepository(private val api: BentoEndpoints, private val invalidations: Invalidations) {
    suspend fun devices(includeRemoved: Boolean = false): List<DeviceResponse> = api.listDevices(includeRemoved = includeRemoved).items

    suspend fun rename(deviceId: String, name: String): DeviceResponse =
        api.renameDevice(deviceId, DeviceRenameRequest(name)).also { invalidations.invalidate(Topic.DEVICES) }

    suspend fun removalPreview(deviceId: String): DeviceRemovalPreviewResponse = api.previewDeviceRemoval(deviceId)

    suspend fun remove(deviceId: String, excludeDeviceIds: List<String>? = null): DeviceRemovalResponse =
        api.removeDevice(deviceId, DeviceRemovalRequest(excludeDeviceIds)).also { invalidations.invalidate(Topic.DEVICES) }

    suspend fun acknowledge(deviceId: String): DeviceResponse =
        api.acknowledgeDevice(deviceId).also { invalidations.invalidate(Topic.DEVICES) }
}

class SettingsRepository(private val api: BentoEndpoints, private val invalidations: Invalidations) {
    suspend fun public(): SettingsResponse = api.publicSettings()

    suspend fun values(): JsonObject = api.settingsValues()

    /** `PATCH /api/settings/values` with the revision read from [values] (409 on a concurrent edit). */
    suspend fun patch(request: dev.bento.api.generated.SettingsPatchRequest): JsonElement =
        api.patchSettings(request).also { invalidations.invalidate(Topic.SETTINGS) }
}

/** Account + vault state; binds the UI cache to the active vault. */
class SessionRepository(private val api: BentoEndpoints, private val uiCache: UiCache, private val invalidations: Invalidations) {
    private val _vaultId = MutableStateFlow(uiCache.currentVault())
    val vaultId: StateFlow<String?> = _vaultId.asStateFlow()

    suspend fun account() = api.accountStatus()

    /** Reads `/api/vault`; a different vault than the cached one clears the UI cache. */
    suspend fun vault() = api.vaultStatus().also { status ->
        uiCache.bindVault(status.vaultId)
        if (_vaultId.value != status.vaultId) {
            _vaultId.value = status.vaultId
            invalidations.invalidateAll()
        }
    }

    suspend fun logOut() = api.logOut().also {
        uiCache.clear()
        _vaultId.value = null
        invalidations.invalidateAll()
    }
}
