package dev.bento.update

import java.io.File
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.Signature
import java.util.Base64

/** Signs like apps/desktop/scripts/sign-update-manifest.mjs, with the JDK's own Ed25519 (independent of BouncyCastle). */
class TestKey(private val pair: KeyPair = KeyPairGenerator.getInstance("Ed25519").generateKeyPair()) {
    /** Raw 32-byte public key: the last 32 bytes of the X.509 SubjectPublicKeyInfo. */
    val raw: ByteArray = pair.public.encoded.takeLast(32).toByteArray()
    val base64: String = Base64.getEncoder().encodeToString(raw)
    val keyId: String = MessageDigest.getInstance("SHA-256").digest(raw).toHex().take(16)

    fun signature(manifest: ByteArray): String {
        val signer = Signature.getInstance("Ed25519")
        signer.initSign(pair.private)
        signer.update("bento-update-manifest:v1\u0000".toByteArray() + manifest)
        return Base64.getEncoder().encodeToString(signer.sign())
    }

    fun document(manifest: ByteArray, vararg extra: Pair<String, String>): ByteArray {
        val entries = (listOf(keyId to signature(manifest)) + extra).joinToString(",") { (id, sig) ->
            """{"keyId":"$id","signature":"$sig"}"""
        }
        return """{"schemaVersion":1,"algorithm":"ed25519","signatures":[$entries]}""".toByteArray()
    }
}

val CERT = "a".repeat(64)
val OTHER_CERT = "b".repeat(64)
const val PACKAGE = "dev.bento.app"
const val COMMIT = "0123456789abcdef0123456789abcdef01234567"

fun manifestJson(
    version: String = "1.3.0",
    versionCode: Long = ManifestParser.versionCode(version)!!,
    arch: String = "universal",
    packageName: String = PACKAGE,
    url: String? = null,
    sha256: String = "c".repeat(64),
    size: Long = 1234,
    minSdk: Int = 29,
    certs: List<String> = listOf(CERT),
    repository: String = "invrnt/bento"
): ByteArray {
    val filename = "bento-android-$version-$arch.apk"
    val assetUrl = url ?: "https://github.com/invrnt/bento/releases/download/android-v$version/$filename"
    return """
        {
          "schemaVersion": 1,
          "version": "$version",
          "releaseName": "Bento $version",
          "notes": "Actualización estable de Bento $version.",
          "publishedAt": "2026-11-24T10:00:00.000Z",
          "commit": "$COMMIT",
          "repository": "$repository",
          "target": "android-$arch",
          "assets": [
            {"platform": "android", "arch": "$arch", "kind": "apk", "filename": "$filename", "url": "$assetUrl", "sha256": "$sha256", "size": $size}
          ],
          "android": {"packageName": "$packageName", "versionCode": $versionCode, "minSdk": $minSdk, "signingCertificateSha256": [${certs.joinToString(",") { "\"$it\"" }}]}
        }
    """.trimIndent().toByteArray()
}

val installed120 = InstalledApp(PACKAGE, ManifestParser.versionCode("1.2.0")!!, sdkInt = 35, arch = UpdateArch.Universal)

fun sha256Hex(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).toHex()

fun resource(path: String): File = File(requireNotNull(TestKey::class.java.classLoader!!.getResource(path)).toURI())
