package dev.bento.feature.files

import dev.bento.api.ApiException
import dev.bento.api.BentoHttp
import dev.bento.api.generated.AssetResponse
import dev.bento.api.generated.BentoEndpoints
import dev.bento.api.generated.DriveBreadcrumbResponse
import dev.bento.api.generated.DriveItemResponse
import dev.bento.api.generated.DrivePathsRequest
import dev.bento.api.generated.EnsureFolderRequest
import dev.bento.api.generated.FavoriteRequest
import dev.bento.api.generated.FolderPatchRequest
import dev.bento.api.generated.SearchResultType
import dev.bento.api.generated.ShareRequest
import dev.bento.api.generated.TelegramChatResponse
import dev.bento.data.DriveRepository
import dev.bento.data.Invalidations
import dev.bento.data.Topic
import dev.bento.data.UiCache
import dev.bento.data.Undoable
import dev.bento.data.optimistic
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody

/** One folder, fully listed (folders + files), with its path from the root. */
data class FolderListing(
    val folderId: String?,
    val items: List<DriveItemResponse>,
    val breadcrumbs: List<DriveBreadcrumbResponse>,
    /** True when the folder has more than [FilesRepository.MAX_LISTING] items and only the first ones are shown. */
    val truncated: Boolean = false,
    /** The order the backend listed [items] in. */
    val sort: FolderSort = FolderSort()
)

/**
 * Archivos operations that [DriveRepository] does not cover. A folder is listed completely (keyset pages, up to
 * [MAX_LISTING]) in the order the backend sorts it (`sort`/`order`, folders first, kept across the cursor's pages).
 * Mutations with `Deshacer` (rename, move, trash, new folder) stay in [DriveRepository].
 */
class FilesRepository(
    private val api: BentoEndpoints,
    /** Raw loopback client for requests the generated client cannot express; null in JVM tests. */
    private val http: BentoHttp?,
    val drive: DriveRepository,
    private val invalidations: Invalidations,
    private val uiCache: UiCache
) {
    private val memory = object : LinkedHashMap<String, FolderListing>(MEMORY_FOLDERS, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, FolderListing>?): Boolean = size > MEMORY_FOLDERS
    }

    private val openFolders = HashMap<String?, String?>()

    /**
     * The folder Archivos showed last for a start folder, kept for this process: a screen recreated after a full-screen
     * destination (reader, viewer) reopens where the person was.
     */
    fun lastOpen(startFolderId: String?): String? = synchronized(openFolders) { openFolders[startFolderId] ?: startFolderId }

    fun rememberOpen(startFolderId: String?, folderId: String?) = synchronized(openFolders) { openFolders[startFolderId] = folderId }

    /** The last listing of [folderId] seen in this process (instant back navigation). */
    fun cached(folderId: String?): FolderListing? = synchronized(memory) { memory[folderId ?: ROOT] }

    /** The root's first screen from the instant-start cache (cold start, before the engine answers). */
    fun cachedRoot(): FolderListing? = drive.cachedRoot()?.let { FolderListing(null, it, emptyList(), sort = ROOT_CACHE_SORT) }

    suspend fun listing(folderId: String?, sort: FolderSort = FolderSort()): FolderListing {
        val items = ArrayList<DriveItemResponse>()
        var cursor: String? = null
        var breadcrumbs: List<DriveBreadcrumbResponse> = emptyList()
        do {
            val page = api.driveItems(folderId = folderId, cursor = cursor, limit = PAGE, sort = sort.wireSort, order = sort.wireOrder)
            if (cursor == null) breadcrumbs = page.breadcrumbs.orEmpty()
            items += page.items
            cursor = page.nextCursor?.takeIf { it != cursor }
        } while (cursor != null && items.size < MAX_LISTING)
        if (folderId == null && sort == ROOT_CACHE_SORT) uiCache.write(DriveRepository.CACHE_KEY, items, DriveItemResponse.serializer())
        return FolderListing(folderId, items, breadcrumbs, truncated = cursor != null, sort = sort).also {
            synchronized(memory) {
                memory[folderId ?: ROOT] =
                    it
            }
        }
    }

    /** Sub-folders of [parentId] (move sheet, folder pickers, the tree pane). */
    suspend fun folders(parentId: String?): List<DriveItemResponse> = listing(parentId).items.filter { it.folder != null }

    /** Folders whose name matches [query] anywhere in Archivos (move sheet search). */
    suspend fun findFolders(query: String): List<DriveItemResponse> {
        if (query.isBlank()) return emptyList()
        val hits = api.search(q = query, type = SearchResultType.FOLDER, limit = 30L).items
        return hits.map { hit ->
            DriveItemResponse(asset = null, folder = null, id = hit.id, name = hit.title, type = "folder", updatedAt = "")
        }
    }

    /**
     * Moves a folder (`PATCH /api/drive/folders/{id}` with `parent_id`). Sent as raw JSON because the generated client
     * omits nulls (`explicitNulls = false`) and `parent_id: null` (the root) must be explicit.
     */
    suspend fun moveFolder(folderId: String, parentId: String?) {
        val raw = http
        if (raw == null || parentId != null) {
            api.updateFolder(folderId, FolderPatchRequest(parentId = parentId))
        } else {
            val body = buildJsonObject { put("parent_id", JsonNull) }.toString()
            raw.execute("PATCH", "/api/drive/folders/${raw.encodePath(folderId)}", body = body.toRequestBody(JSON)) {}
        }
        invalidations.invalidate(Topic.DRIVE, Topic.SEARCH)
    }

    /** An [Undoable] that runs [inverse] (for composed mutations). */
    suspend fun undoable(
        inverse: suspend () -> Unit
    ): Undoable = optimistic(applyLocal = {}, rollbackLocal = {}, remote = {}, inverse = inverse)

    suspend fun asset(assetId: String): AssetResponse = api.assetDetail(assetId)

    suspend fun setPinned(assetId: String, pinned: Boolean): Boolean {
        val result = if (pinned) api.pinAssetOffline(assetId) else api.unpinAssetOffline(assetId)
        // Listings carry `offline_pinned`: reload them so the badge follows the pin.
        invalidations.invalidate(Topic.DRIVE, Topic.TIMELINE)
        return result.pinned
    }

    suspend fun setFavorite(assetId: String, favorite: Boolean): AssetResponse =
        api.setPhotoFavorite(assetId, FavoriteRequest(favorite)).also {
            invalidations.invalidate(Topic.DRIVE, Topic.TIMELINE, Topic.ALBUMS)
        }

    suspend fun telegramChats(query: String? = null): List<TelegramChatResponse> = api.listChats(query = query?.ifBlank { null }).items

    suspend fun sendToTelegram(assetId: String, chatId: Long): Boolean = api.shareAsset(assetId, ShareRequest(chatId = chatId)).sent

    /** Drive path of a folder ("/Trabajo/2024"); the root is "/". */
    suspend fun pathOf(folderId: String?): String {
        if (folderId == null) return ROOT
        val paths = api.drivePaths(DrivePathsRequest(ids = listOf(folderId))) as? JsonObject
        val value = (paths?.get("paths") as? JsonObject)?.get(folderId) as? JsonPrimitive
        return value?.contentOrNull ?: throw ApiException.Decoding(IllegalStateException("folder path missing"))
    }

    /** Creates every missing folder of [path] (idempotent) and returns the id of the last one. */
    suspend fun ensureFolder(path: String): String? {
        val result = api.ensureDriveFolder(EnsureFolderRequest(path)) as? JsonObject
        val folder = result?.get("folder") as? JsonObject
        return (folder?.get("id") as? JsonPrimitive)?.contentOrNull.also { invalidations.invalidate(Topic.DRIVE) }
    }

    companion object {
        const val ROOT = "/"

        /** The instant-start cache holds the root in the default order (callers re-sort it for another sort). */
        private val ROOT_CACHE_SORT = FolderSort()
        private const val MEMORY_FOLDERS = 24
        private val JSON = "application/json".toMediaType()
        const val MAX_LISTING = 5_000
        private const val PAGE = 200L

        fun child(path: String, segment: String): String = if (path == ROOT) "/$segment" else "$path/$segment"
    }
}
