package dev.bento.feature.share

import android.content.ContentResolver
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import androidx.core.content.IntentCompat
import androidx.core.content.pm.ShortcutManagerCompat
import androidx.core.net.toUri
import dev.bento.feature.files.DisplayNames

/** One shared stream (content URI) as the sending app declared it. */
data class SharedItem(val uri: String, val declaredMime: String? = null)

/** What arrived at the share sheet: streams, and/or text (a note when shared alone), and the Direct Share folder. */
data class SharePayload(
    val items: List<SharedItem> = emptyList(),
    val text: String? = null,
    val subject: String? = null,
    /** Direct Share target chosen in the system sheet (`folder:<id>` shortcut), or null. */
    val shortcutFolderId: String? = null
) {
    val empty: Boolean get() = items.isEmpty() && text.isNullOrBlank()
    val noteOnly: Boolean get() = items.isEmpty() && !text.isNullOrBlank()
}

/**
 * `ACTION_SEND` (one stream or text), `ACTION_SEND_MULTIPLE` (many streams, any mix of MIME types) and `ACTION_VIEW`
 * ("Abrir con Bento" of a file). Only `content:` streams are accepted: `file:` URIs from other apps are refused (they
 * would read Bento's own storage) and anything else is ignored.
 */
object ShareIntents {
    const val SHORTCUT_PREFIX = "folder:"

    fun parse(intent: Intent?): SharePayload {
        if (intent == null) return SharePayload()
        val shortcut = intent.getStringExtra(ShortcutManagerCompat.EXTRA_SHORTCUT_ID)?.takeIf { it.startsWith(SHORTCUT_PREFIX) }
            ?.removePrefix(SHORTCUT_PREFIX)?.ifEmpty { null }
        val declared = intent.type
        val items = when (intent.action) {
            Intent.ACTION_SEND -> listOfNotNull(stream(intent))
            Intent.ACTION_SEND_MULTIPLE -> streams(intent)
            Intent.ACTION_VIEW -> listOfNotNull(intent.data)
            else -> emptyList()
        }.filter(::acceptable).distinct().map { SharedItem(it.toString(), declared?.takeUnless { type -> type.endsWith("/*") }) }
        val text = if (intent.action == Intent.ACTION_SEND) intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString() else null
        return SharePayload(items, text?.takeIf { it.isNotBlank() }, intent.getStringExtra(Intent.EXTRA_SUBJECT), shortcut)
    }

    private fun stream(intent: Intent): Uri? = IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java)
        ?: intent.clipData?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.uri

    private fun streams(intent: Intent): List<Uri> {
        val extras = IntentCompat.getParcelableArrayListExtra(intent, Intent.EXTRA_STREAM, Uri::class.java).orEmpty()
        val clip = intent.clipData?.let { clip -> (0 until clip.itemCount).mapNotNull { clip.getItemAt(it).uri } }.orEmpty()
        return extras.ifEmpty { clip }
    }

    private fun acceptable(uri: Uri): Boolean = uri.scheme == ContentResolver.SCHEME_CONTENT
}

/** Name, type and size of a shared item; [readable] is false when the grant was revoked or the provider failed. */
data class SharedDescription(
    val uri: String,
    val name: String,
    val mimeType: String,
    val sizeBytes: Long?,
    val readable: Boolean
) {
    val media: Boolean get() = mimeType.startsWith("image/") || mimeType.startsWith("video/")
}

/** Reads display metadata of shared URIs (ContentResolver on the device; faked in tests). */
fun interface ContentDescriber {
    fun describe(item: SharedItem): SharedDescription
}

class ResolverDescriber(private val resolver: ContentResolver) : ContentDescriber {
    override fun describe(item: SharedItem): SharedDescription {
        val uri = item.uri.toUri()
        return try {
            var name: String? = null
            var size: Long? = null
            resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
                    if (nameIndex >= 0 && !cursor.isNull(nameIndex)) name = cursor.getString(nameIndex)
                    if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) size = cursor.getLong(sizeIndex)
                }
            }
            val mime = resolver.getType(uri) ?: item.declaredMime ?: "application/octet-stream"
            SharedDescription(item.uri, DisplayNames.file(name ?: uri.lastPathSegment), mime, size, readable = true)
        } catch (error: SecurityException) {
            unreadable(item, uri)
        } catch (error: IllegalArgumentException) {
            unreadable(item, uri)
        } catch (error: IllegalStateException) {
            unreadable(item, uri)
        }
    }

    private fun unreadable(item: SharedItem, uri: Uri) =
        SharedDescription(
            item.uri,
            DisplayNames.file(uri.lastPathSegment),
            item.declaredMime ?: "application/octet-stream",
            null,
            readable = false
        )
}
