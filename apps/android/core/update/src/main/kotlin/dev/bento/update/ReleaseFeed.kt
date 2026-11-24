package dev.bento.update

import java.io.IOException
import java.net.URI
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request

/** The signed manifest of the newest Android release, as published (bytes are verified by [ManifestParser]). */
class SignedManifest(val tagVersion: String, val manifest: ByteArray, val signature: ByteArray)

fun interface ReleaseFeed {
    /** `null` when no Android release carries a manifest for [arch]. Throws [IOException] on network errors. */
    suspend fun latest(arch: UpdateArch): SignedManifest?
}

/**
 * GitHub releases of the repository: picks the highest `android-vX.Y.Z` release (not draft, not prerelease) and
 * downloads its `bento-update-android-<arch>.json` and `.sig` assets. Android releases are published with
 * `--latest=false`, so the desktop updater (which reads `releases/latest`) never sees them.
 */
class GitHubReleaseFeed(
    private val client: OkHttpClient,
    private val releasesUrl: String,
    private val allowLoopbackHttp: Boolean = false
) : ReleaseFeed {
    @Serializable
    private data class Release(
        @SerialName("tag_name") val tagName: String = "",
        val draft: Boolean = false,
        val prerelease: Boolean = false,
        val assets: List<Asset> = emptyList()
    )

    @Serializable
    private data class Asset(
        val name: String = "",
        val state: String = "uploaded",
        @SerialName("browser_download_url") val url: String = ""
    )

    private val json = Json { ignoreUnknownKeys = true }

    override suspend fun latest(arch: UpdateArch): SignedManifest? = withContext(Dispatchers.IO) {
        val listing = fetch("$releasesUrl?per_page=$PAGE", MAX_LISTING_BYTES, api = true)
        val releases = try {
            json.decodeFromString<List<Release>>(listing.decodeToString())
        } catch (error: SerializationException) {
            throw IOException("Unexpected releases listing", error)
        } catch (error: IllegalArgumentException) {
            throw IOException("Unexpected releases listing", error)
        }
        val release = releases
            .filter { !it.draft && !it.prerelease }
            .mapNotNull { release -> tagVersion(release.tagName)?.let { version -> release to version } }
            .maxByOrNull { (_, version) -> ManifestParser.versionCode(version) ?: -1 }
            ?: return@withContext null
        val (selected, version) = release
        val manifest = selected.assets.singleOrNull { it.name == arch.manifestName && it.state == "uploaded" } ?: return@withContext null
        val signature = selected.assets.singleOrNull { it.name == arch.manifestName + UpdateSignature.SUFFIX && it.state == "uploaded" }
            ?: return@withContext null
        SignedManifest(
            tagVersion = version,
            manifest = fetch(manifest.url, ManifestParser.MAX_MANIFEST_BYTES, api = false),
            signature = fetch(signature.url, UpdateSignature.MAX_SIGNATURE_BYTES, api = false)
        )
    }

    private fun fetch(url: String, maximum: Int, api: Boolean): ByteArray {
        if (!isAllowed(url)) throw IOException("Refusing update URL")
        val request = Request.Builder()
            .url(url)
            .header("Accept", if (api) "application/vnd.github+json" else "application/octet-stream")
            .apply { if (api) header("X-GitHub-Api-Version", "2022-11-28") }
            .build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) throw IOException("HTTP ${response.code}")
            if (!isAllowed(response.request.url.toString())) throw IOException("Refusing redirect")
            val body = response.body
            val length = body.contentLength()
            if (length > maximum) throw IOException("Response too large")
            val source = body.source()
            if (source.request(maximum.toLong() + 1)) throw IOException("Response too large")
            return source.buffer.readByteArray()
        }
    }

    private fun isAllowed(url: String): Boolean {
        val uri = runCatching { URI(url) }.getOrNull() ?: return false
        return when (uri.scheme) {
            "https" -> !uri.host.isNullOrEmpty() && uri.userInfo == null
            "http" -> allowLoopbackHttp && uri.host == "127.0.0.1"
            else -> false
        }
    }

    companion object {
        const val PAGE: Int = 30
        const val MAX_LISTING_BYTES: Int = 4 * 1024 * 1024
        private val TAG = Regex("^android-v(\\d+\\.\\d+\\.\\d+)$")

        fun tagVersion(tag: String): String? = TAG.matchEntire(tag)?.groupValues?.get(1)?.takeIf { ManifestParser.versionCode(it) != null }

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .followSslRedirects(false)
            .build()
    }
}
