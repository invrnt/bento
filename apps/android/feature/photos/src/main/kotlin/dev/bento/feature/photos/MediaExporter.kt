package dev.bento.feature.photos

import android.content.ClipData
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import androidx.core.content.FileProvider
import dagger.hilt.android.qualifiers.ApplicationContext
import dev.bento.api.AssetPaths
import dev.bento.api.BentoHttp
import dev.bento.api.generated.AssetResponse
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Plaintext copies that leave Bento (product/android.md §1.4): a decrypted temporary copy in `cacheDir/share` behind
 * the app's FileProvider (per-URI read grants, deleted after an hour), and `Guardar en el teléfono` into MediaStore
 * `Pictures/Bento` (`Movies/Bento` for videos). The UI always shows the disclosure before calling these.
 */
@Singleton
class MediaExporter @Inject constructor(@ApplicationContext private val context: Context, private val http: BentoHttp) {
    private val shareDir get() = File(context.cacheDir, "share")
    private val authority get() = "${context.packageName}.files"

    /** Decrypts [asset] into a temporary file and returns its content URI. */
    suspend fun temporaryCopy(asset: AssetResponse): Uri = withContext(Dispatchers.IO) {
        pruneOldCopies()
        val dir = File(shareDir, asset.id).apply { mkdirs() }
        val file = File(dir, safeName(asset.filename))
        if (!file.exists() || file.length() != asset.sizeBytes) {
            val tmp = File(dir, ".${file.name}.part")
            http.execute("GET", AssetPaths.download(asset.id)) { response ->
                response.body.byteStream().use { input -> tmp.outputStream().use(input::copyTo) }
            }
            tmp.renameTo(file)
        }
        FileProvider.getUriForFile(context, authority, file)
    }

    /** `Guardar en el teléfono`: streams the original into MediaStore and returns the new item. */
    suspend fun saveToPhone(asset: AssetResponse): Uri = withContext(Dispatchers.IO) {
        val video = MediaFormat.isVideo(asset)
        val collection = if (video) MediaStore.Video.Media.EXTERNAL_CONTENT_URI else MediaStore.Images.Media.EXTERNAL_CONTENT_URI
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, safeName(asset.filename))
            put(MediaStore.MediaColumns.MIME_TYPE, asset.mimeType)
            put(
                MediaStore.MediaColumns.RELATIVE_PATH,
                "${if (video) Environment.DIRECTORY_MOVIES else Environment.DIRECTORY_PICTURES}/Bento"
            )
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val resolver = context.contentResolver
        val uri = resolver.insert(collection, values) ?: error("MediaStore refused the item")
        try {
            http.execute("GET", AssetPaths.download(asset.id)) { response ->
                resolver.openOutputStream(uri)?.use { out -> response.body.byteStream().use { it.copyTo(out) } }
                    ?: error("no output stream")
            }
            resolver.update(uri, ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }, null, null)
            uri
        } catch (error: Exception) {
            resolver.delete(uri, null, null)
            throw error
        }
    }

    fun shareIntent(uris: List<Uri>, mimeTypes: List<String>): Intent {
        val type =
            mimeTypes.distinct().singleOrNull() ?: mimeTypes.map { it.substringBefore('/') }.distinct().singleOrNull()?.let { "$it/*" }
                ?: "*/*"
        val intent = if (uris.size == 1) {
            Intent(Intent.ACTION_SEND).putExtra(Intent.EXTRA_STREAM, uris.single())
        } else {
            Intent(Intent.ACTION_SEND_MULTIPLE).putParcelableArrayListExtra(Intent.EXTRA_STREAM, ArrayList(uris))
        }
        return intent.setType(type).withGrants(uris)
    }

    fun viewIntent(uri: Uri, mimeType: String): Intent = Intent(Intent.ACTION_VIEW).setDataAndType(uri, mimeType).withGrants(listOf(uri))

    /** `Usar como…` (wallpaper, contact photo) through the system chooser. */
    fun attachIntent(uri: Uri, mimeType: String): Intent =
        Intent(Intent.ACTION_ATTACH_DATA).setDataAndType(uri, mimeType).putExtra("mimeType", mimeType).withGrants(listOf(uri))

    private fun Intent.withGrants(uris: List<Uri>): Intent = apply {
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        clipData = ClipData.newRawUri(null, uris.first()).apply { uris.drop(1).forEach { addItem(ClipData.Item(it)) } }
    }

    private fun pruneOldCopies() {
        val cutoff = System.currentTimeMillis() - COPY_TTL_MS
        shareDir.listFiles()?.forEach { dir -> if (dir.lastModified() < cutoff) dir.deleteRecursively() }
    }

    companion object {
        private const val COPY_TTL_MS = 60 * 60 * 1000L

        /** Upload-safe display name: no separators, control characters, or leading dots; bounded length. */
        fun safeName(name: String): String {
            val cleaned = name.substringAfterLast('/').substringAfterLast('\\').filter { it >= ' ' && it != '\u007f' }.trim().trimStart('.')
            return cleaned.take(120).ifEmpty { "bento" }
        }
    }
}
