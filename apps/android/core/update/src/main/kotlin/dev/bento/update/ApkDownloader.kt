package dev.bento.update

import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.security.MessageDigest
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request

/** The download failed for a reason that is not the network (checksum, size, storage). */
class UpdateDownloadException(val failure: UpdateFailure, message: String) : IOException(message)

/**
 * Downloads a release APK into app-private storage ([directory], under `noBackupFilesDir`), resuming a partial
 * `.part` file with an HTTP Range request, then checks size and SHA-256 against the signed manifest.
 * A sidecar `.part.id` ties the partial file to one asset so a different release never resumes onto it.
 */
class ApkDownloader(
    private val client: OkHttpClient,
    private val directory: File,
    private val io: CoroutineDispatcher = Dispatchers.IO
) {
    fun finalFile(asset: UpdateAsset): File = File(directory, asset.filename)

    private fun partFile(asset: UpdateAsset) = File(directory, asset.filename + ".part")

    private fun idFile(asset: UpdateAsset) = File(directory, asset.filename + ".part.id")

    private fun identity(asset: UpdateAsset) = "${asset.sha256}:${asset.size}:${asset.url}"

    /** A complete, verified APK already on disk for [asset], or `null`. */
    suspend fun existing(asset: UpdateAsset): File? = withContext(io) {
        val file = finalFile(asset)
        if (file.isFile && file.length() == asset.size && sha256(file) == asset.sha256) file else null
    }

    suspend fun download(asset: UpdateAsset, onProgress: (Float) -> Unit): File = withContext(io) {
        existing(asset)?.let { return@withContext it }
        if (!directory.isDirectory && !directory.mkdirs()) throw UpdateDownloadException(UpdateFailure.Storage, "No update directory")
        pruneOthers(asset)
        val part = partFile(asset)
        val id = idFile(asset)
        if (!id.isFile || id.readText() != identity(asset)) {
            part.delete()
            id.writeText(identity(asset))
        }
        if (part.length() > asset.size) part.delete()
        val needed = asset.size - part.length()
        if (directory.usableSpace < needed + FREE_SPACE_MARGIN) throw UpdateDownloadException(UpdateFailure.Storage, "Not enough space")
        if (part.length() < asset.size) fetchInto(asset, part, onProgress)
        if (part.length() != asset.size) {
            part.delete()
            throw UpdateDownloadException(UpdateFailure.Checksum, "Size mismatch")
        }
        if (sha256(part) != asset.sha256) {
            part.delete()
            id.delete()
            throw UpdateDownloadException(UpdateFailure.Checksum, "SHA-256 mismatch")
        }
        val target = finalFile(asset)
        target.delete()
        if (!part.renameTo(target)) throw UpdateDownloadException(UpdateFailure.Storage, "Rename failed")
        id.delete()
        onProgress(1f)
        target
    }

    private suspend fun fetchInto(asset: UpdateAsset, part: File, onProgress: (Float) -> Unit) {
        val offset = part.length()
        val request = Request.Builder()
            .url(asset.url)
            .header("Accept", "application/octet-stream")
            .apply { if (offset > 0) header("Range", "bytes=$offset-") }
            .build()
        client.newCall(request).execute().use { response ->
            val append = when {
                response.code == HTTP_PARTIAL && offset > 0 -> {
                    val start = response.header("Content-Range")?.let(CONTENT_RANGE::find)?.groupValues?.get(1)?.toLongOrNull()
                    if (start != offset) throw IOException("Unexpected Content-Range")
                    true
                }
                response.code == HTTP_RANGE_NOT_SATISFIABLE && offset > 0 -> {
                    // The partial file is either complete or stale; start again next time if it is stale.
                    part.delete()
                    throw IOException("Range not satisfiable")
                }
                response.isSuccessful -> false
                else -> throw IOException("HTTP ${response.code}")
            }
            val body = response.body
            var written = if (append) offset else 0L
            FileOutputStream(part, append).use { out ->
                val source = body.source()
                val buffer = ByteArray(BUFFER)
                while (true) {
                    kotlin.coroutines.coroutineContext.ensureActive()
                    val read = source.read(buffer)
                    if (read == -1) break
                    written += read
                    if (written > asset.size) throw UpdateDownloadException(UpdateFailure.Checksum, "Larger than signed size")
                    out.write(buffer, 0, read)
                    onProgress(written.toFloat() / asset.size)
                }
                out.fd.sync()
            }
        }
    }

    /** Deletes APKs and partial files of other releases. */
    fun pruneOthers(keep: UpdateAsset?) {
        val names = keep?.let { setOf(it.filename, it.filename + ".part", it.filename + ".part.id") }.orEmpty()
        directory.listFiles()?.filter { it.name !in names }?.forEach { it.delete() }
    }

    companion object {
        private const val BUFFER = 64 * 1024
        private const val HTTP_PARTIAL = 206
        private const val HTTP_RANGE_NOT_SATISFIABLE = 416
        private const val FREE_SPACE_MARGIN = 50L * 1024 * 1024
        private val CONTENT_RANGE = Regex("^bytes (\\d+)-\\d+/(?:\\d+|\\*)$")

        fun sha256(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buffer = ByteArray(BUFFER)
                while (true) {
                    val read = input.read(buffer)
                    if (read == -1) break
                    digest.update(buffer, 0, read)
                }
            }
            return digest.digest().toHex()
        }
    }
}
