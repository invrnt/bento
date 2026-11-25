package dev.bento.update

import java.io.File
import java.nio.file.Files
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import okio.Buffer
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

class ApkDownloaderTest {
    private val server = MockWebServer()
    private val dir: File = Files.createTempDirectory("bento-update").toFile()
    private val apk = ByteArray(300_000) { (it * 31 % 251).toByte() }
    private lateinit var downloader: ApkDownloader

    @Before
    fun setUp() {
        server.start()
        downloader = ApkDownloader(OkHttpClient(), dir)
    }

    @After
    fun tearDown() {
        server.close()
        dir.deleteRecursively()
    }

    private fun asset(sha: String = sha256Hex(apk), size: Long = apk.size.toLong()) = UpdateAsset(
        platform = "android",
        arch = "universal",
        kind = "apk",
        filename = "bento-android-1.3.0-universal.apk",
        url = server.url("/download/bento-android-1.3.0-universal.apk").toString(),
        sha256 = sha,
        size = size
    )

    private fun body(bytes: ByteArray) = Buffer().write(bytes)

    @Test
    fun downloadsAndVerifiesSha256() = runTest {
        server.enqueue(MockResponse.Builder().body(body(apk)).build())
        val progress = mutableListOf<Float>()
        val file = downloader.download(asset()) { progress += it }
        assertArrayEquals(apk, file.readBytes())
        assertEquals(1f, progress.last())
        assertFalse(File(dir, file.name + ".part").exists())
        // A second call reuses the verified file without the network.
        assertEquals(file, downloader.download(asset()) {})
        assertEquals(1, server.requestCount)
    }

    @Test
    fun shaMismatchDeletesTheDownload() = runTest {
        server.enqueue(MockResponse.Builder().body(body(apk)).build())
        try {
            downloader.download(asset(sha = "0".repeat(64))) {}
            fail("expected a checksum failure")
        } catch (error: UpdateDownloadException) {
            assertEquals(UpdateFailure.Checksum, error.failure)
        }
        assertTrue(dir.listFiles().orEmpty().none { it.name.endsWith(".apk") || it.name.endsWith(".part") })
    }

    @Test
    fun largerThanSignedSizeIsRejected() = runTest {
        server.enqueue(MockResponse.Builder().body(body(apk + ByteArray(10))).build())
        try {
            downloader.download(asset()) {}
            fail("expected a checksum failure")
        } catch (error: UpdateDownloadException) {
            assertEquals(UpdateFailure.Checksum, error.failure)
        }
    }

    @Test
    fun resumesAPartialDownloadWithRange() = runTest {
        val asset = asset()
        seedPartial(asset, apk.copyOfRange(0, 100_000))
        server.enqueue(
            MockResponse.Builder()
                .code(206)
                .addHeader("Content-Range", "bytes 100000-${apk.size - 1}/${apk.size}")
                .body(body(apk.copyOfRange(100_000, apk.size)))
                .build()
        )
        val file = downloader.download(asset) {}
        assertEquals("bytes=100000-", server.takeRequest().headers["Range"])
        assertArrayEquals(apk, file.readBytes())
    }

    @Test
    fun serverIgnoringRangeRestartsFromZero() = runTest {
        val asset = asset()
        seedPartial(asset, apk.copyOfRange(0, 50_000))
        server.enqueue(MockResponse.Builder().code(200).body(body(apk)).build())
        assertArrayEquals(apk, downloader.download(asset) {}.readBytes())
    }

    @Test
    fun partialOfAnotherReleaseIsDiscarded() = runTest {
        val asset = asset()
        seedPartial(asset, ByteArray(100_000) { 7 }, identity = "other:1:x")
        server.enqueue(MockResponse.Builder().body(body(apk)).build())
        assertArrayEquals(apk, downloader.download(asset) {}.readBytes())
        assertNull(server.takeRequest().headers["Range"])
    }

    @Test
    fun shortCompleteBodyIsASizeMismatch() = runTest {
        val asset = asset()
        server.enqueue(MockResponse.Builder().body(body(apk.copyOfRange(0, 120_000))).build())
        try {
            downloader.download(asset) {}
            fail("expected a size failure")
        } catch (error: UpdateDownloadException) {
            assertEquals(UpdateFailure.Checksum, error.failure)
        }
        assertFalse(File(dir, asset.filename + ".part").exists())
    }

    @Test
    fun networkErrorKeepsThePartForResume() = runTest {
        val asset = asset()
        seedPartial(asset, apk.copyOfRange(0, 100_000))
        server.enqueue(MockResponse.Builder().code(503).build())
        try {
            downloader.download(asset) {}
            fail("expected a network failure")
        } catch (error: java.io.IOException) {
            assertFalse(error is UpdateDownloadException)
        }
        assertEquals(100_000L, File(dir, asset.filename + ".part").length())
    }

    private fun seedPartial(asset: UpdateAsset, bytes: ByteArray, identity: String = "${asset.sha256}:${asset.size}:${asset.url}") {
        File(dir, asset.filename + ".part").writeBytes(bytes)
        File(dir, asset.filename + ".part.id").writeText(identity)
    }
}
