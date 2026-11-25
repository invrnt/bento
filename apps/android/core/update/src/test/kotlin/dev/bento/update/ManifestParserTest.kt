package dev.bento.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ManifestParserTest {
    private val key = TestKey()

    private fun evaluate(
        manifest: ByteArray,
        signature: ByteArray = key.document(manifest),
        installed: InstalledApp = installed120,
        tag: String? = "1.3.0",
        loopback: Boolean = false
    ) = ManifestParser.evaluate(manifest, signature, listOf(key.raw), installed, "invrnt/bento", tag, loopback)

    @Test
    fun newerSignedReleaseIsAvailable() {
        val verdict = evaluate(manifestJson()) as ManifestVerdict.Newer
        assertEquals("1.3.0", verdict.release.version)
        assertEquals(1_003_000L, verdict.release.versionCode)
        assertEquals(1234L, verdict.release.sizeBytes)
        assertEquals(setOf(CERT), verdict.release.signingCertificates)
    }

    @Test
    fun downgradeAndSameVersionAreUpToDate() {
        assertEquals(ManifestVerdict.UpToDate, evaluate(manifestJson("1.1.9"), tag = "1.1.9"))
        assertEquals(ManifestVerdict.UpToDate, evaluate(manifestJson("1.2.0"), tag = "1.2.0"))
    }

    @Test
    fun signatureIsCheckedBeforeContent() {
        val manifest = manifestJson()
        assertEquals(ManifestVerdict.Rejected(UpdateFailure.Signature), evaluate(manifest, TestKey().document(manifest)))
        val tampered = manifest.decodeToString().replace("\"size\": 1234", "\"size\": 99").toByteArray()
        assertEquals(ManifestVerdict.Rejected(UpdateFailure.Signature), evaluate(tampered, key.document(manifest)))
        assertEquals(
            ManifestVerdict.Rejected(UpdateFailure.Signature),
            ManifestParser.evaluate(manifest, key.document(manifest), emptyList(), installed120, "invrnt/bento", "1.3.0")
        )
    }

    @Test
    fun signedButInvalidContentIsRejected() {
        val manifest = ManifestVerdict.Rejected(UpdateFailure.Manifest)
        assertEquals(manifest, evaluate(manifestJson(), tag = "1.4.0")) // replayed under another release
        assertEquals(manifest, evaluate(manifestJson(arch = "arm64"))) // other target
        assertEquals(manifest, evaluate(manifestJson(packageName = "com.evil"))) // other app
        assertEquals(manifest, evaluate(manifestJson(versionCode = 9_999_999))) // code not derived from version
        assertEquals(manifest, evaluate(manifestJson(repository = "someone/bento")))
        assertEquals(manifest, evaluate(manifestJson(sha256 = "C".repeat(64))))
        assertEquals(manifest, evaluate(manifestJson(certs = emptyList())))
        assertEquals(manifest, evaluate(manifestJson(size = 0)))
        assertEquals(manifest, evaluate(manifestJson(url = "http://github.com/x/bento-android-1.3.0-universal.apk")))
        assertEquals(manifest, evaluate(manifestJson(url = "https://github.com/x/other.apk")))
        assertEquals(manifest, evaluate("{}".toByteArray()))
        assertEquals(manifest, evaluate("""[1,2]""".toByteArray()))
    }

    @Test
    fun newerReleaseForNewerAndroidIsIncompatible() {
        assertEquals(ManifestVerdict.Rejected(UpdateFailure.Incompatible), evaluate(manifestJson(minSdk = 36)))
    }

    @Test
    fun loopbackHttpOnlyForTheDryRunFeed() {
        val local = manifestJson(url = "http://127.0.0.1:8799/download/android-v1.3.0/bento-android-1.3.0-universal.apk")
        assertEquals(ManifestVerdict.Rejected(UpdateFailure.Manifest), evaluate(local))
        assertTrue(evaluate(local, loopback = true) is ManifestVerdict.Newer)
        assertFalse(ManifestParser.isAllowedDownloadUrl("http://10.0.2.2/a.apk", "a.apk", allowLoopbackHttp = true))
        assertFalse(ManifestParser.isAllowedDownloadUrl("https://u:p@github.com/a.apk", "a.apk", allowLoopbackHttp = false))
        assertFalse(ManifestParser.isAllowedDownloadUrl("https://github.com/a.apk?x=1", "a.apk", allowLoopbackHttp = false))
    }

    @Test
    fun versionCodesAreDeterministic() {
        assertEquals(1_002_003L, ManifestParser.versionCode("1.2.3"))
        assertEquals(1_000L, ManifestParser.versionCode("0.1.0"))
        assertEquals(null, ManifestParser.versionCode("1.2"))
        assertEquals(null, ManifestParser.versionCode("01.2.3"))
        assertEquals(null, ManifestParser.versionCode("1.2.3-beta"))
        assertEquals(null, ManifestParser.versionCode("1.1000.0"))
    }
}
