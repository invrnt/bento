package dev.bento.feature.files

import android.content.ContentResolver
import android.net.Uri
import dev.bento.api.AssetPaths
import dev.bento.api.BentoHttp
import java.io.File
import java.io.InputStream
import java.io.OutputStream
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Decrypting downloads from the local API (`GET /api/assets/{id}/content`, served plaintext by the engine).
 * Plaintext copies that leave Bento (`Abrir con…`, `Compartir`) live only in `cacheDir/share/` (FileProvider path),
 * one random directory per copy, and are deleted after [MAX_AGE_MS] or at the next start.
 */
class ContentFiles(
    private val http: BentoHttp,
    private val shareDir: File,
    private val clock: () -> Long = System::currentTimeMillis,
    /** Called for every file just before [prune] deletes it: revokes its FileProvider grants (SEC-04). */
    private val onExpired: (File) -> Unit = {}
) {
    /** Streams the original into [sink]; [onProgress] gets (bytesDone, bytesTotal or -1). */
    suspend fun stream(assetId: String, sink: OutputStream, onProgress: (Long, Long) -> Unit = { _, _ -> }) {
        http.execute("GET", AssetPaths.content(assetId)) { response ->
            val total = response.body.contentLength()
            response.body.byteStream().use { input -> copy(input, sink, total, onProgress) }
        }
    }

    /** A plaintext copy for another app, named like the original (sanitized). */
    suspend fun plaintextCopy(assetId: String, fileName: String, onProgress: (Long, Long) -> Unit = { _, _ -> }): File {
        prune()
        val dir = File(shareDir, UUID.randomUUID().toString()).apply { mkdirs() }
        val target = File(dir, DisplayNames.file(fileName))
        try {
            withContext(Dispatchers.IO) { target.outputStream().use { out -> stream(assetId, out, onProgress) } }
        } catch (error: Throwable) {
            dir.deleteRecursively()
            throw error
        }
        return target
    }

    /** `Descargar al teléfono` into a SAF document the person created. */
    suspend fun saveTo(resolver: ContentResolver, target: Uri, assetId: String, onProgress: (Long, Long) -> Unit = { _, _ -> }) {
        withContext(Dispatchers.IO) {
            val out = resolver.openOutputStream(target, "wt") ?: error("cannot open target")
            out.use { stream(assetId, it, onProgress) }
        }
    }

    /** Text for the in-app viewer; null when larger than [limit]. */
    suspend fun text(assetId: String, limit: Long = TEXT_LIMIT): String? = http.execute("GET", AssetPaths.content(assetId)) { response ->
        val length = response.body.contentLength()
        if (length > limit) return@execute null
        val out = java.io.ByteArrayOutputStream()
        val tooLarge = response.body.byteStream().use { input ->
            val buffer = ByteArray(BUFFER)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                out.write(buffer, 0, read)
                if (out.size() > limit) return@use true
            }
            false
        }
        if (tooLarge) null else out.toString(Charsets.UTF_8.name())
    }

    /** A temporary file the in-app PDF reader renders (never shared; deleted when the reader closes). */
    suspend fun readerCopy(
        assetId: String,
        onProgress: (Long, Long) -> Unit = { _, _ -> }
    ): File = plaintextCopy(assetId, "$assetId.pdf", onProgress)

    /**
     * Deletes copies older than [MAX_AGE_MS] (all of them with [everything], at app start), revoking their URI
     * grants first. Covers every copy in `cacheDir/share`, including the photo exporter's. Runs at start, at every
     * new copy, and periodically while the process lives (`ShareCacheJanitor` in `:app`).
     */
    fun prune(everything: Boolean = false) {
        val now = clock()
        shareDir.listFiles()?.forEach { dir ->
            if (everything || now - dir.lastModified() > MAX_AGE_MS) {
                dir.walkBottomUp().filter { it.isFile }.forEach { file -> runCatching { onExpired(file) } }
                dir.deleteRecursively()
            }
        }
    }

    fun discard(file: File) {
        val parent = file.parentFile
        if (parent != null && parent.parentFile == shareDir) parent.deleteRecursively() else file.delete()
    }

    private fun copy(input: InputStream, output: OutputStream, total: Long, onProgress: (Long, Long) -> Unit) {
        val buffer = ByteArray(BUFFER)
        var done = 0L
        var lastReport = 0L
        while (true) {
            val read = input.read(buffer)
            if (read < 0) break
            output.write(buffer, 0, read)
            done += read
            if (done - lastReport >= REPORT_STEP) {
                lastReport = done
                onProgress(done, total)
            }
        }
        onProgress(done, total)
    }

    companion object {
        const val TEXT_LIMIT = 2L * 1024 * 1024
        const val MAX_AGE_MS = 60 * 60_000L
        private const val BUFFER = 64 * 1024
        private const val REPORT_STEP = 256 * 1024L
    }
}
