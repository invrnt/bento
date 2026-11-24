package dev.bento.update

import android.content.Context
import java.io.File
import java.io.IOException
import java.nio.file.Files
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import okio.Buffer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class UpdateCheckerTest {
    private val server = MockWebServer()
    private val dir: File = Files.createTempDirectory("bento-update").toFile()
    private val key = TestKey()
    private val apk = ByteArray(64_000) { (it % 13).toByte() }

    private class FakePackages : PackageInspector {
        var installedApp = installed120
        var installedSigners: SignerSet? = SignerSet(setOf(CERT), setOf(CERT))
        var archiveSigners = SignerSet(setOf(CERT), setOf(CERT))
        var archiveVersion: Long? = null
        var canInstall = true

        override fun installed() = installedApp
        override fun installedSigners() = installedSigners
        override fun archive(apk: File) = ArchiveInfo(PACKAGE, archiveVersion ?: 1_003_000L, archiveSigners)
        override fun canRequestInstalls() = canInstall
    }

    private class FakeInstaller : UpdateInstaller {
        val installed = mutableListOf<File>()
        override suspend fun install(apk: File) {
            installed += apk
        }
        override fun openUnknownSourcesSettings(context: Context) = Unit
    }

    private class MemoryPreferences : UpdatePreferences {
        override var lastCheckedAt: Long? = null
        override var dismissedVersion: String? = null
    }

    private val packages = FakePackages()
    private val installer = FakeInstaller()
    private val preferences = MemoryPreferences()
    private var feedResult: () -> SignedManifest? = { null }

    @Before
    fun setUp() = server.start()

    @After
    fun tearDown() {
        server.close()
        dir.deleteRecursively()
    }

    private fun signedRelease(version: String = "1.3.0"): SignedManifest {
        val manifest = manifestJson(
            version = version,
            url = server.url("/d/bento-android-$version-universal.apk").toString().replace("localhost", "127.0.0.1"),
            sha256 = sha256Hex(apk),
            size = apk.size.toLong()
        )
        return SignedManifest(version, manifest, key.document(manifest))
    }

    private fun TestScope.checker(keys: List<ByteArray> = listOf(key.raw)) = UpdateChecker(
        config = UpdateConfig(keys, "invrnt/bento", allowLoopbackHttp = true),
        feed = { feedResult() },
        // Blocking IO on the test scheduler so advanceUntilIdle() covers the whole download.
        downloader = ApkDownloader(OkHttpClient(), dir, StandardTestDispatcher(testScheduler)),
        packages = packages,
        installer = installer,
        preferences = preferences,
        scope = TestScope(UnconfinedTestDispatcher(testScheduler)),
        now = { 42L }
    )

    @Test
    fun withoutAKeyTheUpdaterIsUnavailableAndOffline() = runTest {
        var called = false
        feedResult = { called = true; null }
        val checker = checker(keys = emptyList())
        assertEquals(UpdateState.Unavailable, checker.check())
        assertFalse(called)
    }

    @Test
    fun noNewerReleaseIsUpToDate() = runTest {
        feedResult = { signedRelease("1.2.0") }
        assertEquals(UpdateState.Idle(42L, upToDate = true), checker().check())
        feedResult = { null }
        assertEquals(UpdateState.Idle(42L, upToDate = true), checker().check())
    }

    @Test
    fun networkErrorFails() = runTest {
        feedResult = { throw IOException("offline") }
        assertEquals(UpdateState.Failed(UpdateFailure.Network), checker().check())
    }

    @Test
    fun badSignatureFailsWithoutDownloading() = runTest {
        feedResult = { signedRelease().let { SignedManifest(it.tagVersion, it.manifest, TestKey().document(it.manifest)) } }
        assertEquals(UpdateState.Failed(UpdateFailure.Signature), checker().check())
        assertEquals(0, server.requestCount)
    }

    @Test
    fun downloadVerifyAndInstall() = runTest {
        feedResult = { signedRelease() }
        val checker = checker()
        val available = checker.check() as UpdateState.Available
        assertTrue(checker.showCard.value)
        server.enqueue(MockResponse.Builder().body(Buffer().write(apk)).build())
        checker.download()
        advanceUntilIdle()
        assertEquals(UpdateState.Ready(available.release), checker.state.value)
        checker.install()
        advanceUntilIdle()
        assertEquals(UpdateState.Installing(available.release), checker.state.value)
        assertEquals(listOf("bento-android-1.3.0-universal.apk"), installer.installed.map { it.name })
        checker.onInstallResult(InstallResult.Cancelled)
        assertEquals(UpdateState.Ready(available.release, cancelled = true), checker.state.value)
    }

    @Test
    fun signerMismatchDeletesTheApk() = runTest {
        feedResult = { signedRelease() }
        packages.archiveSigners = SignerSet(setOf(OTHER_CERT), setOf(OTHER_CERT))
        val checker = checker()
        val release = (checker.check() as UpdateState.Available).release
        server.enqueue(MockResponse.Builder().body(Buffer().write(apk)).build())
        checker.download()
        advanceUntilIdle()
        assertEquals(UpdateState.Failed(UpdateFailure.Signer, release), checker.state.value)
        assertTrue(dir.listFiles().orEmpty().none { it.name.endsWith(".apk") })
        assertTrue(installer.installed.isEmpty())
    }

    @Test
    fun apkWithAnotherVersionCodeIsRejected() = runTest {
        feedResult = { signedRelease() }
        packages.archiveVersion = 1_004_000L
        val checker = checker()
        val release = (checker.check() as UpdateState.Available).release
        server.enqueue(MockResponse.Builder().body(Buffer().write(apk)).build())
        checker.download()
        advanceUntilIdle()
        assertEquals(UpdateState.Failed(UpdateFailure.Signer, release), checker.state.value)
    }

    @Test
    fun checksumMismatchFailsTheDownload() = runTest {
        feedResult = { signedRelease() }
        val checker = checker()
        val release = (checker.check() as UpdateState.Available).release
        server.enqueue(MockResponse.Builder().body(Buffer().write(apk.copyOf().also { it[0] = 99 })).build())
        checker.download()
        advanceUntilIdle()
        assertEquals(UpdateState.Failed(UpdateFailure.Checksum, release), checker.state.value)
    }

    @Test
    fun unknownSourcesPermissionIsAskedBeforeInstalling() = runTest {
        feedResult = { signedRelease() }
        packages.canInstall = false
        val checker = checker()
        checker.check()
        server.enqueue(MockResponse.Builder().body(Buffer().write(apk)).build())
        checker.download()
        advanceUntilIdle()
        val ready = checker.state.value as UpdateState.Ready
        assertTrue(ready.needsPermission)
        checker.install()
        advanceUntilIdle()
        assertTrue(installer.installed.isEmpty())
        packages.canInstall = true
        checker.refreshPermission()
        assertFalse((checker.state.value as UpdateState.Ready).needsPermission)
    }

    @Test
    fun dismissHidesTheCardForThatVersionOnly() = runTest {
        feedResult = { signedRelease() }
        val checker = checker()
        checker.check()
        checker.dismiss()
        assertFalse(checker.showCard.value)
        assertEquals("1.3.0", preferences.dismissedVersion)
        feedResult = { signedRelease("1.4.0") }
        checker.check()
        assertTrue(checker.showCard.value)
    }

    @Test
    fun alreadyDownloadedApkIsReadyAfterACheck() = runTest {
        feedResult = { signedRelease() }
        val first = checker()
        first.check()
        server.enqueue(MockResponse.Builder().body(Buffer().write(apk)).build())
        first.download()
        advanceUntilIdle()
        val second = checker()
        assertTrue(second.check() is UpdateState.Ready)
        assertEquals(1, server.requestCount)
    }
}
