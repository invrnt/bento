package dev.bento.app

import android.Manifest
import android.app.NotificationManager
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.Build
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import dev.bento.api.ApiException
import dev.bento.api.BentoHttp
import dev.bento.api.BinaryEndpoints
import dev.bento.api.EngineEndpointProvider
import dev.bento.api.ThumbnailSize
import dev.bento.api.UploadSource
import dev.bento.api.generated.BentoEndpoints
import dev.bento.api.loopbackOkHttp
import dev.bento.background.BentoNotifications
import dev.bento.background.TransferScheduler
import dev.bento.engine.BentoEngine
import dev.bento.engine.EngineHolder
import dev.bento.engine.EngineState
import dev.bento.engine.di.PlatformEntryPoint
import java.io.ByteArrayOutputStream
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.OkHttpClient
import okhttp3.Request
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Real embedded engine on the emulator (fake storage backend, debug build). */
@RunWith(AndroidJUnit4::class)
class EngineSmokeTest {
    @get:Rule
    val notifications: GrantPermissionRule = if (Build.VERSION.SDK_INT >= 33) {
        GrantPermissionRule.grant(Manifest.permission.POST_NOTIFICATIONS)
    } else {
        GrantPermissionRule.grant()
    }

    private val context: Context = ApplicationProvider.getApplicationContext()
    private val platform = PlatformEntryPoint.get(context)
    private val engine: BentoEngine = platform.engine()
    private lateinit var http: BentoHttp
    private val lease = engine.acquire(EngineHolder.Ui)

    @Before
    fun setUp() {
        http = BentoHttp(loopbackOkHttp(engine), EngineEndpointProvider(engine, timeoutMs = 180_000))
    }

    @After
    fun tearDown() = lease.close()

    private fun ready(): EngineState.Ready = runBlocking { engine.awaitReady(180_000) }

    @Test
    fun engineBootsAndHealthNeedsTheToken() = runBlocking {
        val started = System.nanoTime()
        val ready = ready()
        val health = BentoEndpoints(http).health()
        assertEquals("ok", health.status)
        assertEquals("fake", health.storageBackend)
        val anonymous = OkHttpClient().newCall(Request.Builder().url("${ready.baseUrl}/api/health").build()).execute()
        assertEquals(401, anonymous.code)
        anonymous.close()
        InstrumentationRegistry.getInstrumentation().sendStatus(
            0,
            android.os.Bundle().apply { putString("engine_ready_ms", ((System.nanoTime() - started) / 1_000_000).toString()) }
        )
    }

    @Test
    fun thumbnailIsGeneratedThroughTheMediaToolsBridge() = runBlocking {
        ready()
        val before = platform.mediaTools().calls.get()
        val jpeg = testJpeg(4000, 3000)
        val asset = BinaryEndpoints(http).uploadAsset(
            UploadSource("smoke-${System.nanoTime()}.jpg", "image/jpeg", jpeg.size.toLong()) { jpeg.inputStream() },
            mode = "photos"
        )
        val bytes = withTimeout(60_000) {
            var result: ByteArray? = null
            while (result == null) {
                result = try {
                    BinaryEndpoints(http).thumbnailBytes(asset.id, ThumbnailSize.SMALL)
                } catch (pending: ApiException.Http) {
                    delay(250)
                    null
                }
            }
            result
        }
        assertTrue("JPEG magic", bytes.size > 100 && bytes[0] == 0xFF.toByte() && bytes[1] == 0xD8.toByte())
        assertTrue("bridge used", platform.mediaTools().calls.get() > before)
    }

    @Test
    fun userInitiatedTransferShowsItsNotification() = runBlocking {
        assumeTrue("UIDT needs Android 14+", Build.VERSION.SDK_INT >= 34)
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            ready()
            signInWithFakeCloud(BentoEndpoints(http))
            // Pending work keeps the transfer running long enough to observe the notification.
            val size = 256L * 1024 * 1024
            val asset = BinaryEndpoints(http).uploadAsset(
                UploadSource("big-${System.nanoTime()}.bin", "application/octet-stream", size) { GeneratedStream(size) }
            )
            // The storage pipeline enqueues remote_upload asynchronously after ingest.
            withTimeout(60_000) {
                while (BentoEndpoints(http).listJobs(limit = 200).items.none {
                        it.assetId == asset.id &&
                            it.status in setOf("queued", "running")
                    }
                ) {
                    delay(50)
                }
            }
            scenario.onActivity { TransferScheduler.start(it) }
            val manager = context.getSystemService(NotificationManager::class.java)
            val shown = withTimeout(30_000) {
                while (manager.activeNotifications.none { it.id == BentoNotifications.ID_TRANSFER }) delay(50)
                manager.activeNotifications.first { it.id == BentoNotifications.ID_TRANSFER }
            }
            assertEquals(BentoNotifications.CHANNEL_TRANSFERS, shown.notification.channelId)
            assertTrue(shown.notification.flags and android.app.Notification.FLAG_ONGOING_EVENT != 0)
            TransferScheduler.stop(context)
        }
    }

    private fun testJpeg(width: Int, height: Int): ByteArray {
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        Canvas(bitmap).apply {
            drawColor(Color.rgb(200, 120, 40))
            drawCircle(width / 2f, height / 2f, height / 3f, Paint().apply { color = Color.BLUE })
        }
        return ByteArrayOutputStream().use { out ->
            bitmap.compress(Bitmap.CompressFormat.JPEG, 90, out)
            bitmap.recycle()
            out.toByteArray()
        }
    }
}

/** Fake cloud (debug): QR login auto-approves; create the vault and confirm the kit so uploads run. */
internal suspend fun signInWithFakeCloud(api: BentoEndpoints) {
    if (api.vaultStatus().state == "ready") return
    if (api.accountStatus().step != "authorized") {
        api.startQrLogin()
        withTimeout(30_000) { while (api.accountStatus().step != "authorized") delay(200) }
    }
    if (api.vaultStatus().state == "no_vault") {
        val created = api.createVault()
        api.confirmRecoveryKit(dev.bento.api.generated.LastGroupRequest(created.recoveryCode.substringAfterLast('-')))
    }
}

/** Deterministic pseudo-random bytes without holding them in memory. */
private class GeneratedStream(private val size: Long) : java.io.InputStream() {
    private var position = 0L

    override fun read(): Int = if (position >= size) -1 else ((position * 31 + position / 4096) % 251).toInt().also { position++ }

    override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
        if (position >= size) return -1
        val count = minOf(length.toLong(), size - position).toInt()
        for (i in 0 until count) buffer[offset + i] = (((position + i) * 31 + (position + i) / 4096) % 251).toByte()
        position += count
        return count
    }
}

/** AndroidKeystore round trip on a real device (the JVM test covers the format with a software key). */
@RunWith(AndroidJUnit4::class)
class KeystoreWrappingTest {
    @Test
    fun keystoreWrappingKeyIsStable() {
        val context: Context = ApplicationProvider.getApplicationContext()
        val file = java.io.File(context.cacheDir, "wrapping-test.bin").apply { delete() }
        val source = dev.bento.engine.bridge.AndroidKeystoreKeySource(context.packageManager)
        val first = dev.bento.engine.bridge.KeystoreKeyWrapping(file, source).deviceWrappingKey()
        val second = dev.bento.engine.bridge.KeystoreKeyWrapping(file, source).deviceWrappingKey()
        assertTrue(first.contentEquals(second))
        assertEquals(32, first.size)
        file.delete()
    }
}
