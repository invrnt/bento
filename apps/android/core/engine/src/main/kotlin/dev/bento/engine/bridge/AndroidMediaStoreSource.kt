package dev.bento.engine.bridge

import android.Manifest
import android.content.ContentResolver
import android.content.Context
import android.content.pm.PackageManager
import android.database.ContentObserver
import android.database.Cursor
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.provider.MediaStore
import androidx.core.content.ContextCompat
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.serializer

@Serializable
data class MediaAccess(val full: Boolean, val partial: Boolean, val location: Boolean)

@Serializable
data class MediaBucket(
    @SerialName("bucket_id") val bucketId: String,
    val name: String,
    @SerialName("relative_path") val relativePath: String?,
    val count: Int,
    @SerialName("video_count") val videoCount: Int
)

@Serializable
data class MediaItem(
    @SerialName("media_id") val mediaId: Long,
    val uri: String,
    @SerialName("bucket_id") val bucketId: String?,
    @SerialName("display_name") val displayName: String?,
    @SerialName("mime_type") val mimeType: String?,
    @SerialName("size_bytes") val sizeBytes: Long?,
    @SerialName("date_taken_ms") val dateTakenMs: Long?,
    @SerialName("date_modified_s") val dateModifiedS: Long?,
    val generation: Long?,
    val width: Int?,
    val height: Int?,
    @SerialName("duration_ms") val durationMs: Long?,
    @SerialName("relative_path") val relativePath: String?
)

@Serializable
data class MediaScanPage(val items: List<MediaItem>, @SerialName("next_after") val nextAfter: Long?)

@Serializable
data class MediaChangesPage(val items: List<MediaItem>, @SerialName("max_generation") val maxGeneration: Long)

/** One `MediaStore.Files` row, already read from the cursor (pure mapping is JVM tested). */
data class MediaRow(
    val id: Long,
    val mediaType: Int,
    val bucketId: String?,
    val bucketName: String?,
    val displayName: String?,
    val mimeType: String?,
    val size: Long?,
    val dateTaken: Long?,
    val dateModified: Long?,
    val generation: Long?,
    val width: Int?,
    val height: Int?,
    val duration: Long?,
    val relativePath: String?
)

object MediaStoreMapping {
    const val MEDIA_TYPE_IMAGE = 1
    const val MEDIA_TYPE_VIDEO = 3

    /** `content://media/external/{images|video}/media/<id>`. */
    fun uriFor(row: MediaRow): String {
        val kind = if (row.mediaType == MEDIA_TYPE_VIDEO) "video" else "images"
        return "content://media/external/$kind/media/${row.id}"
    }

    fun item(row: MediaRow): MediaItem = MediaItem(
        mediaId = row.id,
        uri = uriFor(row),
        bucketId = row.bucketId,
        displayName = row.displayName,
        mimeType = row.mimeType,
        sizeBytes = row.size?.takeIf { it >= 0 },
        dateTakenMs = row.dateTaken?.takeIf { it > 0 },
        dateModifiedS = row.dateModified,
        generation = row.generation,
        width = row.width?.takeIf { it > 0 },
        height = row.height?.takeIf { it > 0 },
        durationMs = row.duration?.takeIf { it > 0 },
        relativePath = row.relativePath
    )

    /** Groups rows into buckets (sorted by name, then id) with total and video counts. */
    fun buckets(rows: Sequence<MediaRow>): List<MediaBucket> {
        data class Acc(val name: String, val path: String?, var count: Int = 0, var videos: Int = 0)
        val byId = LinkedHashMap<String, Acc>()
        for (row in rows) {
            val id = row.bucketId ?: continue
            val acc = byId.getOrPut(id) { Acc(row.bucketName.orEmpty(), row.relativePath) }
            acc.count += 1
            if (row.mediaType == MEDIA_TYPE_VIDEO) acc.videos += 1
        }
        return byId.map { (id, acc) -> MediaBucket(id, acc.name, acc.path, acc.count, acc.videos) }
            .sortedWith(compareBy({ it.name.lowercase() }, { it.bucketId }))
    }

    /** Parses the `exists` argument (a JSON list of numbers). */
    fun parseIds(json: String): List<Long> = BridgeJson.decodeFromString(ListSerializer(Long.serializer()), json)
}

/**
 * [MediaStoreSource] over `MediaStore.Files` (images and videos; pending and trashed rows excluded).
 * Generations come from `GENERATION_MODIFIED` on Android 11+; Android 10 falls back to `DATE_MODIFIED`
 * seconds (coarser, still monotonic per edit).
 */
class AndroidMediaStoreSource(private val context: Context) : MediaStoreSource {
    private val resolver: ContentResolver = context.contentResolver
    private val filesUri: Uri = MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL)
    private var observer: ContentObserver? = null
    private var observerThread: HandlerThread? = null

    override fun access(): String {
        val full = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            granted(Manifest.permission.READ_MEDIA_IMAGES) || granted(Manifest.permission.READ_MEDIA_VIDEO)
        } else {
            granted(Manifest.permission.READ_EXTERNAL_STORAGE)
        }
        val partial = !full && Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE &&
            granted(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
        val result = MediaAccess(full, partial, location = granted(Manifest.permission.ACCESS_MEDIA_LOCATION))
        return BridgeJson.encodeToString(MediaAccess.serializer(), result)
    }

    override fun buckets(): String = bridgeCall {
        val rows = query(selection = BASE_SELECTION, args = emptyArray(), sort = "${MediaStore.MediaColumns._ID} ASC", limit = null)
        BridgeJson.encodeToString(ListSerializer(MediaBucket.serializer()), MediaStoreMapping.buckets(rows.asSequence()))
    }

    override fun scan(bucketId: String, afterMediaId: Long, limit: Int): String = bridgeCall {
        val size = limit.coerceIn(1, MAX_PAGE)
        val rows = query(
            selection = "$BASE_SELECTION AND ${MediaStore.MediaColumns.BUCKET_ID} = ? AND ${MediaStore.MediaColumns._ID} > ?",
            args = arrayOf(bucketId, afterMediaId.toString()),
            sort = "${MediaStore.MediaColumns._ID} ASC",
            limit = size + 1
        )
        val page = rows.take(size)
        val next = if (rows.size > size) page.last().id else null
        BridgeJson.encodeToString(MediaScanPage.serializer(), MediaScanPage(page.map(MediaStoreMapping::item), next))
    }

    override fun changes(sinceGeneration: Long, limit: Int): String = bridgeCall {
        val column = generationColumn()
        val rows = query(
            selection = "$BASE_SELECTION AND $column > ?",
            args = arrayOf(sinceGeneration.toString()),
            sort = "$column ASC, ${MediaStore.MediaColumns._ID} ASC",
            limit = limit.coerceIn(1, MAX_PAGE)
        )
        val max = rows.maxOfOrNull { it.generation ?: 0L } ?: sinceGeneration
        BridgeJson.encodeToString(
            MediaChangesPage.serializer(),
            MediaChangesPage(rows.map(MediaStoreMapping::item), maxOf(max, sinceGeneration))
        )
    }

    override fun exists(mediaIds: String): String = bridgeCall {
        val ids = MediaStoreMapping.parseIds(mediaIds)
        val present = ArrayList<Long>(ids.size)
        for (chunk in ids.chunked(IN_CHUNK)) {
            if (chunk.isEmpty()) continue
            val placeholders = chunk.joinToString(",") { "?" }
            query(
                selection = "$BASE_SELECTION AND ${MediaStore.MediaColumns._ID} IN ($placeholders)",
                args = chunk.map(Long::toString).toTypedArray(),
                sort = "${MediaStore.MediaColumns._ID} ASC",
                limit = null
            ).mapTo(present) { it.id }
        }
        BridgeJson.encodeToString(ListSerializer(Long.serializer()), present)
    }

    override fun openFd(uri: String, requireOriginal: Boolean): Int = bridgeCall {
        var target = Uri.parse(uri)
        if (target.scheme != ContentResolver.SCHEME_CONTENT || target.authority != MediaStore.AUTHORITY) {
            throw BridgeException(BridgeException.UNSUPPORTED, "only MediaStore content URIs")
        }
        if (requireOriginal && granted(Manifest.permission.ACCESS_MEDIA_LOCATION)) target = MediaStore.setRequireOriginal(target)
        val pfd = resolver.openFileDescriptor(target, "r") ?: throw BridgeException(BridgeException.NOT_FOUND, "media item not found")
        pfd.detachFd()
    }

    /** Observe external media while the engine runs; [onChange] gets the changed URI (or null). */
    fun observe(onChange: (String?) -> Unit) {
        stopObserving()
        val thread = HandlerThread("bento-media-observer").apply { start() }
        val contentObserver = object : ContentObserver(Handler(thread.looper)) {
            override fun onChange(selfChange: Boolean, uri: Uri?) = onChange(uri?.toString())
        }
        resolver.registerContentObserver(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, true, contentObserver)
        resolver.registerContentObserver(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, true, contentObserver)
        observer = contentObserver
        observerThread = thread
    }

    fun stopObserving() {
        observer?.let(resolver::unregisterContentObserver)
        observer = null
        observerThread?.quitSafely()
        observerThread = null
    }

    private fun granted(permission: String): Boolean =
        ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED

    private fun generationColumn(): String =
        if (Build.VERSION.SDK_INT >=
            Build.VERSION_CODES.R
        ) {
            MediaStore.MediaColumns.GENERATION_MODIFIED
        } else {
            MediaStore.MediaColumns.DATE_MODIFIED
        }

    private fun query(selection: String, args: Array<String>, sort: String, limit: Int?): List<MediaRow> {
        val projection = PROJECTION + generationColumn()
        val cursor = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            val queryArgs = Bundle().apply {
                putString(ContentResolver.QUERY_ARG_SQL_SELECTION, selection)
                putStringArray(ContentResolver.QUERY_ARG_SQL_SELECTION_ARGS, args)
                putString(ContentResolver.QUERY_ARG_SQL_SORT_ORDER, sort)
                limit?.let { putInt(ContentResolver.QUERY_ARG_LIMIT, it) }
            }
            resolver.query(filesUri, projection, queryArgs, null)
        } else {
            resolver.query(filesUri, projection, selection, args, sort)
        } ?: return emptyList()
        return cursor.use { readRows(it, limit) }
    }

    private fun readRows(cursor: Cursor, limit: Int?): List<MediaRow> {
        val rows = ArrayList<MediaRow>()
        fun long(name: String): Long? = cursor.getColumnIndex(name).takeIf { it >= 0 && !cursor.isNull(it) }?.let(cursor::getLong)
        fun int(name: String): Int? = cursor.getColumnIndex(name).takeIf { it >= 0 && !cursor.isNull(it) }?.let(cursor::getInt)
        fun string(name: String): String? = cursor.getColumnIndex(name).takeIf { it >= 0 && !cursor.isNull(it) }?.let(cursor::getString)
        while (cursor.moveToNext() && (limit == null || rows.size < limit)) {
            rows += MediaRow(
                id = long(MediaStore.MediaColumns._ID) ?: continue,
                mediaType = int(MediaStore.Files.FileColumns.MEDIA_TYPE) ?: 0,
                bucketId = string(MediaStore.MediaColumns.BUCKET_ID),
                bucketName = string(MediaStore.MediaColumns.BUCKET_DISPLAY_NAME),
                displayName = string(MediaStore.MediaColumns.DISPLAY_NAME),
                mimeType = string(MediaStore.MediaColumns.MIME_TYPE),
                size = long(MediaStore.MediaColumns.SIZE),
                dateTaken = long(MediaStore.MediaColumns.DATE_TAKEN),
                dateModified = long(MediaStore.MediaColumns.DATE_MODIFIED),
                generation = long(generationColumn()),
                width = int(MediaStore.MediaColumns.WIDTH),
                height = int(MediaStore.MediaColumns.HEIGHT),
                duration = long(MediaStore.MediaColumns.DURATION),
                relativePath = string(MediaStore.MediaColumns.RELATIVE_PATH)
            )
        }
        return rows
    }

    private companion object {
        const val MAX_PAGE = 500
        const val IN_CHUNK = 200
        val BASE_SELECTION = "(${MediaStore.Files.FileColumns.MEDIA_TYPE} = ${MediaStoreMapping.MEDIA_TYPE_IMAGE} OR " +
            "${MediaStore.Files.FileColumns.MEDIA_TYPE} = ${MediaStoreMapping.MEDIA_TYPE_VIDEO}) AND ${MediaStore.MediaColumns.IS_PENDING} = 0"
        val PROJECTION = arrayOf(
            MediaStore.MediaColumns._ID,
            MediaStore.Files.FileColumns.MEDIA_TYPE,
            MediaStore.MediaColumns.BUCKET_ID,
            MediaStore.MediaColumns.BUCKET_DISPLAY_NAME,
            MediaStore.MediaColumns.DISPLAY_NAME,
            MediaStore.MediaColumns.MIME_TYPE,
            MediaStore.MediaColumns.SIZE,
            MediaStore.MediaColumns.DATE_TAKEN,
            MediaStore.MediaColumns.DATE_MODIFIED,
            MediaStore.MediaColumns.WIDTH,
            MediaStore.MediaColumns.HEIGHT,
            MediaStore.MediaColumns.DURATION,
            MediaStore.MediaColumns.RELATIVE_PATH
        )
    }
}
