package dev.bento.data

import androidx.paging.Pager
import androidx.paging.PagingConfig
import androidx.paging.PagingData
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

    fun timeline(pageSize: Int = PageSizes.GRID): Flow<PagingData<TimelineEntry>> {
        val factory = invalidations.pagingFactory(scope, Topic.TIMELINE) {
            CursorPagingSource { cursor, limit ->
                val page = api.photosTimeline(cursor = cursor, limit = limit.toLong())
                val items = page.groups.flatMap { group -> group.assets.map { TimelineEntry.Photo(group.date, it) } }
                if (cursor == null) uiCache.write(CACHE_KEY, items.map { it.asset }, AssetResponse.serializer())
                CursorPage(items, page.nextCursor)
            }
        }
        val pages = Pager(
            PagingConfig(pageSize = pageSize, initialLoadSize = pageSize, enablePlaceholders = false),
            pagingSourceFactory = factory
        ).flow
        return combine(pages, overlay.changes) { data, changes ->
            data.filter { !overlay.isHidden((it as TimelineEntry.Photo).asset.id, changes) }
                .map { photo -> photo.copy(asset = overlay.apply(photo.asset.id, photo.asset, changes)) as TimelineEntry }
                .insertSeparators { before, after ->
                    val next = after as? TimelineEntry.Photo ?: return@insertSeparators null
                    if ((before as? TimelineEntry.Photo)?.date == next.date) null else TimelineEntry.Day(next.date)
                }
        }
    }

    /**
     * Month index for the fast scroller. Until the backend's `/photos/timeline/index` lands (agent 35) it is
     * derived by walking timeline pages (O(items), cursor-only); swap to the endpoint when it is generated.
     */
    suspend fun monthIndex(): List<MonthIndexEntry> {
        val months = LinkedHashMap<String, MonthIndexEntry>()
        var cursor: String? = null
        do {
            val pageCursor = cursor
            val page = api.photosTimeline(cursor = cursor, limit = INDEX_PAGE.toLong())
            for (group in page.groups) {
                val month = group.date.take(7)
                val existing = months[month]
                months[month] = existing?.copy(count = existing.count + group.assets.size)
                    ?: MonthIndexEntry(month, group.assets.size, pageCursor)
            }
            cursor = page.nextCursor
        } while (cursor != null)
        return months.values.toList()
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

    companion object {
        const val CACHE_KEY = "fotos"
        private const val INDEX_PAGE = 500
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
