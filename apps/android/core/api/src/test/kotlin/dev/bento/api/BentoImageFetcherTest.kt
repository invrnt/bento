package dev.bento.api

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import coil3.ImageLoader
import coil3.decode.DataSource
import coil3.disk.DiskCache
import coil3.disk.directory
import coil3.fetch.SourceFetchResult
import coil3.network.okhttp.OkHttpNetworkFetcherFactory
import coil3.request.Options
import coil3.size.Size
import dev.bento.engine.EngineState
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.OkHttpClient
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

/** Cold start: cached thumbnails must not wait for the engine (TTFD, product/android.md §13). */
@RunWith(RobolectricTestRunner::class)
class BentoImageFetcherTest {
    private val context: Context = ApplicationProvider.getApplicationContext()
    private val loader = ImageLoader.Builder(context)
        .diskCache { DiskCache.Builder().directory(context.cacheDir.resolve("images-test")).maxSizeBytes(1L shl 20).build() }
        .build()

    /** The engine never becomes ready. */
    private val http = BentoHttp(
        OkHttpClient(),
        object : EndpointProvider {
            override suspend fun ready(): EngineState.Ready = awaitCancellation()

            override fun reportStall() = Unit
        }
    )
    private val factory = BentoImageFetcher.Factory(http, OkHttpNetworkFetcherFactory())
    private val options = Options(context, size = Size(256, 256))

    private fun store(key: String, bytes: ByteArray) {
        val cache = loader.diskCache!!
        val editor = cache.openEditor(key)!!
        // Coil's network fetcher stores response headers (metadata) next to the body; an entry needs both.
        cache.fileSystem.write(editor.metadata) { writeUtf8("") }
        cache.fileSystem.write(editor.data) { write(bytes) }
        editor.commit()
    }

    @Test
    fun `an etag thumbnail in the disk cache is served without the engine`() = runTest {
        val image = BentoImage.thumbnail("a1", "\"t1\"")
        store(cacheKey(image, ThumbnailSize.atLeast(256)), byteArrayOf(1, 2, 3))

        val result = withTimeoutOrNull(1_000) { factory.create(image, options, loader).fetch() } as SourceFetchResult

        assertEquals(DataSource.DISK, result.dataSource)
        assertEquals(3L, result.source.source().use { it.readByteArray().size.toLong() })
    }

    @Test
    fun `thumbnails without an etag and cache misses still wait for the engine`() = runTest {
        store(cacheKey(BentoImage.thumbnail("a1"), ThumbnailSize.atLeast(256)), byteArrayOf(1))

        assertNull(withTimeoutOrNull(1_000) { factory.create(BentoImage.thumbnail("a1"), options, loader).fetch() })
        assertNull(withTimeoutOrNull(1_000) { factory.create(BentoImage.thumbnail("a2", "\"t2\""), options, loader).fetch() })
    }
}
