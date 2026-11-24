package dev.bento.update

import java.net.URI
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json

/**
 * Per-target Android manifest `bento-update-android-<arch>.json`: the desktop manifest schema (schemaVersion 1,
 * version, releaseName, notes, publishedAt, commit, repository, target, assets) plus an `android` block. It is produced
 * by `apps/android/scripts/release/update-manifest.mjs` and signed with the desktop's Ed25519 key.
 */
@Serializable
data class UpdateManifest(
    val schemaVersion: Int,
    val version: String,
    val releaseName: String,
    val notes: String,
    val publishedAt: String,
    val commit: String,
    val repository: String,
    val target: String,
    val assets: List<UpdateAsset>,
    val android: AndroidRelease
)

@Serializable
data class UpdateAsset(
    val platform: String,
    val arch: String,
    val kind: String,
    val filename: String,
    val url: String,
    val sha256: String,
    val size: Long
)

@Serializable
data class AndroidRelease(
    val packageName: String,
    val versionCode: Long,
    val minSdk: Int,
    /** SHA-256 (lowercase hex) of each APK signing certificate. */
    val signingCertificateSha256: List<String>
)

/** What the installed app needs to judge a manifest. */
data class InstalledApp(val packageName: String, val versionCode: Long, val sdkInt: Int, val arch: UpdateArch)

enum class UpdateArch(val id: String) {
    Arm64("arm64"),
    Universal("universal");

    val target: String get() = "android-$id"
    val manifestName: String get() = "bento-update-android-$id.json"
}

/** A verified, newer release the UI can show. */
data class UpdateRelease(
    val version: String,
    val versionCode: Long,
    val notes: String,
    val sizeBytes: Long,
    val asset: UpdateAsset,
    val signingCertificates: Set<String>
)

sealed interface ManifestVerdict {
    data class Newer(val release: UpdateRelease) : ManifestVerdict
    data object UpToDate : ManifestVerdict
    data class Rejected(val failure: UpdateFailure) : ManifestVerdict
}

object ManifestParser {
    const val MAX_MANIFEST_BYTES: Int = 64 * 1024
    const val MAX_APK_BYTES: Long = 1024L * 1024 * 1024

    private val json = Json { ignoreUnknownKeys = true }
    private val SEMVER = Regex("^(0|[1-9]\\d{0,2})\\.(0|[1-9]\\d{0,2})\\.(0|[1-9]\\d{0,2})$")
    private val SHA256 = Regex("^[a-f0-9]{64}$")
    private val COMMIT = Regex("^[a-f0-9]{40}$")
    private val FILENAME = Regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\\.apk$")

    /** The deterministic versionCode of `X.Y.Z` (same formula as app/build.gradle.kts): X·10⁶ + Y·10³ + Z. */
    fun versionCode(version: String): Long? {
        val match = SEMVER.matchEntire(version) ?: return null
        val (major, minor, patch) = match.destructured
        return major.toLong() * 1_000_000 + minor.toLong() * 1_000 + patch.toLong()
    }

    /**
     * Verifies the signature first, then the content. [tagVersion] is the version of the GitHub release the manifest
     * was attached to (`android-vX.Y.Z`), so an old signed manifest cannot be replayed under a newer release.
     */
    fun evaluate(
        manifestBytes: ByteArray,
        signatureBytes: ByteArray,
        publicKeys: List<ByteArray>,
        installed: InstalledApp,
        repository: String,
        tagVersion: String?,
        allowLoopbackHttp: Boolean = false
    ): ManifestVerdict {
        if (manifestBytes.isEmpty() || manifestBytes.size > MAX_MANIFEST_BYTES) return ManifestVerdict.Rejected(UpdateFailure.Manifest)
        if (publicKeys.isEmpty() || !UpdateSignature.verify(manifestBytes, signatureBytes, publicKeys)) {
            return ManifestVerdict.Rejected(UpdateFailure.Signature)
        }
        val manifest = decodeUtf8(manifestBytes)?.let { text ->
            try {
                json.decodeFromString(UpdateManifest.serializer(), text)
            } catch (_: SerializationException) {
                null
            } catch (_: IllegalArgumentException) {
                null
            }
        } ?: return ManifestVerdict.Rejected(UpdateFailure.Manifest)
        val release = validate(manifest, installed, repository, tagVersion, allowLoopbackHttp)
            ?: return ManifestVerdict.Rejected(UpdateFailure.Manifest)
        if (release.versionCode <= installed.versionCode) return ManifestVerdict.UpToDate
        if (manifest.android.minSdk > installed.sdkInt) return ManifestVerdict.Rejected(UpdateFailure.Incompatible)
        return ManifestVerdict.Newer(release)
    }

    private fun validate(
        manifest: UpdateManifest,
        installed: InstalledApp,
        repository: String,
        tagVersion: String?,
        allowLoopbackHttp: Boolean
    ): UpdateRelease? {
        val code = versionCode(manifest.version) ?: return null
        val android = manifest.android
        val headerValid = manifest.schemaVersion == 1 &&
            (tagVersion == null || tagVersion == manifest.version) &&
            manifest.repository == repository &&
            manifest.target == installed.arch.target &&
            COMMIT.matches(manifest.commit) &&
            manifest.releaseName.length <= 200 &&
            manifest.notes.length <= 4000 &&
            android.packageName == installed.packageName &&
            android.versionCode == code &&
            android.minSdk in 21..100 &&
            android.signingCertificateSha256.size in 1..4 &&
            android.signingCertificateSha256.all(SHA256::matches)
        if (!headerValid || manifest.assets.size != 1) return null
        val asset = manifest.assets.single()
        val assetValid = asset.platform == "android" &&
            asset.arch == installed.arch.id &&
            asset.kind == "apk" &&
            FILENAME.matches(asset.filename) &&
            asset.filename.contains(manifest.version) &&
            SHA256.matches(asset.sha256) &&
            asset.size in 1..MAX_APK_BYTES &&
            isAllowedDownloadUrl(asset.url, asset.filename, allowLoopbackHttp)
        if (!assetValid) return null
        return UpdateRelease(
            version = manifest.version,
            versionCode = code,
            notes = manifest.notes,
            sizeBytes = asset.size,
            asset = asset,
            signingCertificates = android.signingCertificateSha256.toSet()
        )
    }

    /** HTTPS URL ending in the asset's file name; plain HTTP only to 127.0.0.1 for the local release dry run. */
    fun isAllowedDownloadUrl(url: String, filename: String, allowLoopbackHttp: Boolean): Boolean {
        val uri = runCatching { URI(url) }.getOrNull() ?: return false
        if (uri.userInfo != null || uri.rawQuery != null || uri.rawFragment != null) return false
        val schemeOk = when (uri.scheme) {
            "https" -> !uri.host.isNullOrEmpty()
            "http" -> allowLoopbackHttp && uri.host == "127.0.0.1"
            else -> false
        }
        return schemeOk && uri.rawPath?.substringAfterLast('/') == filename
    }
}
