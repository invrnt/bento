package dev.bento.feature.settings

import android.Manifest
import android.content.ContentUris
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.MediaStore
import android.util.Size
import androidx.core.content.ContextCompat

/** What Bento may read from the camera roll (product/android.md §6). */
enum class MediaAccess { Full, Partial, Denied }

/** Permission names and the access they add up to, per SDK level (pure; JVM tested). */
object MediaPermissions {
    private const val UPSIDE_DOWN_CAKE = 34
    private const val TIRAMISU = 33

    /** What `Respaldar fotos` requests: images + videos (13+, plus the partial-selection grant on 14+), storage (≤ 12). */
    @android.annotation.SuppressLint("InlinedApi") // each list is only used on the SDK level it is chosen for
    fun media(sdk: Int = Build.VERSION.SDK_INT): List<String> = when {
        sdk >= UPSIDE_DOWN_CAKE -> listOf(
            Manifest.permission.READ_MEDIA_IMAGES,
            Manifest.permission.READ_MEDIA_VIDEO,
            Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED
        )

        sdk >= TIRAMISU -> listOf(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VIDEO)

        else -> listOf(Manifest.permission.READ_EXTERNAL_STORAGE)
    }

    const val LOCATION = Manifest.permission.ACCESS_MEDIA_LOCATION

    @android.annotation.SuppressLint("InlinedApi") // guarded by [sdk]
    fun access(sdk: Int, granted: (String) -> Boolean): MediaAccess = when {
        sdk >= TIRAMISU && granted(Manifest.permission.READ_MEDIA_IMAGES) -> MediaAccess.Full
        sdk >= UPSIDE_DOWN_CAKE && granted(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED) -> MediaAccess.Partial
        sdk < TIRAMISU && granted(Manifest.permission.READ_EXTERNAL_STORAGE) -> MediaAccess.Full
        else -> MediaAccess.Denied
    }

    fun current(context: Context): MediaAccess = access(Build.VERSION.SDK_INT) { granted(context, it) }

    fun location(context: Context): Boolean = granted(context, LOCATION)

    private fun granted(context: Context, permission: String) =
        ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED
}

/** MediaStore reads the backup screens need beyond the backend's bucket list (thumbnails, partial counts, delete). */
object CameraRoll {
    private val files: Uri = MediaStore.Files.getContentUri(MediaStore.VOLUME_EXTERNAL)
    private const val MEDIA_TYPES =
        "(${MediaStore.Files.FileColumns.MEDIA_TYPE}=${MediaStore.Files.FileColumns.MEDIA_TYPE_IMAGE} OR " +
            "${MediaStore.Files.FileColumns.MEDIA_TYPE}=${MediaStore.Files.FileColumns.MEDIA_TYPE_VIDEO})"

    /** The newest visible item of [bucketId] (the bucket row's thumbnail), or null. */
    fun newestIn(context: Context, bucketId: String): Uri? {
        val args = Bundle().apply {
            putString(android.content.ContentResolver.QUERY_ARG_SQL_SELECTION, "$MEDIA_TYPES AND ${MediaStore.MediaColumns.BUCKET_ID}=?")
            putStringArray(android.content.ContentResolver.QUERY_ARG_SQL_SELECTION_ARGS, arrayOf(bucketId))
            putStringArray(android.content.ContentResolver.QUERY_ARG_SORT_COLUMNS, arrayOf(MediaStore.MediaColumns.DATE_MODIFIED))
            putInt(
                android.content.ContentResolver.QUERY_ARG_SORT_DIRECTION,
                android.content.ContentResolver.QUERY_SORT_DIRECTION_DESCENDING
            )
            putInt(android.content.ContentResolver.QUERY_ARG_LIMIT, 1)
        }
        return runCatching {
            context.contentResolver.query(files, arrayOf(MediaStore.MediaColumns._ID, MediaStore.Files.FileColumns.MEDIA_TYPE), args, null)
                ?.use { cursor ->
                    if (!cursor.moveToFirst()) return@use null
                    val id = cursor.getLong(0)
                    val video = cursor.getInt(1) == MediaStore.Files.FileColumns.MEDIA_TYPE_VIDEO
                    ContentUris.withAppendedId(
                        if (video) MediaStore.Video.Media.EXTERNAL_CONTENT_URI else MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                        id
                    )
                }
        }.getOrNull()
    }

    /** How many items the app can see (partial access: "Bento solo ve 12 fotos"). */
    fun visibleCount(context: Context): Int = runCatching {
        context.contentResolver.query(files, arrayOf(MediaStore.MediaColumns._ID), MEDIA_TYPES, null, null)?.use { it.count } ?: 0
    }.getOrDefault(0)

    fun thumbnail(context: Context, uri: Uri, sizePx: Int): Bitmap? =
        runCatching { context.contentResolver.loadThumbnail(uri, Size(sizePx, sizePx), null) }.getOrNull()

    /** Content URIs of the backup file ids still present (batched `_id IN (…)` queries); missing ids are skipped. */
    fun urisFor(context: Context, mediaIds: List<String>): Map<String, Uri> {
        val out = LinkedHashMap<String, Uri>()
        mediaIds.mapNotNull { it.toLongOrNull() }.distinct().chunked(BATCH).forEach { chunk ->
            val selection = "${MediaStore.MediaColumns._ID} IN (${chunk.joinToString(",") { "?" }})"
            runCatching {
                context.contentResolver.query(
                    files,
                    arrayOf(MediaStore.MediaColumns._ID, MediaStore.Files.FileColumns.MEDIA_TYPE),
                    selection,
                    chunk.map(Long::toString).toTypedArray(),
                    null
                )?.use { cursor ->
                    while (cursor.moveToNext()) {
                        val id = cursor.getLong(0)
                        val base = if (cursor.getInt(1) == MediaStore.Files.FileColumns.MEDIA_TYPE_VIDEO) {
                            MediaStore.Video.Media.EXTERNAL_CONTENT_URI
                        } else {
                            MediaStore.Images.Media.EXTERNAL_CONTENT_URI
                        }
                        out[id.toString()] = ContentUris.withAppendedId(base, id)
                    }
                }
            }
        }
        return out
    }

    /** Which of [mediaIds] are gone after the system delete request (only those are reported to the backend). */
    fun deleted(context: Context, mediaIds: List<String>): List<String> {
        val present = urisFor(context, mediaIds).keys
        return mediaIds.filter { it !in present }
    }

    private const val BATCH = 400
}
