package dev.bento.feature.photos

import android.content.Context
import coil3.ImageLoader
import coil3.test.FakeImageLoaderEngine
import dev.bento.api.BentoHttp
import dev.bento.api.BentoJson
import dev.bento.api.EndpointProvider
import dev.bento.api.generated.AssetResponse
import dev.bento.data.AlbumsRepository
import dev.bento.data.DriveRepository
import dev.bento.data.Invalidations
import dev.bento.data.TelegramMediaRepository
import dev.bento.data.TimelineRepository
import dev.bento.data.UiCache
import dev.bento.testing.FakeApiTransport
import java.io.File
import kotlinx.coroutines.CoroutineScope
import okhttp3.OkHttpClient

/**
 * Real repositories and [MediaActions] over [FakeApiTransport] (generated DTOs, real optimistic overlay), so UI tests
 * exercise undo end to end without an engine.
 */
class MediaTestHarness(context: Context, scope: CoroutineScope) {
    val transport = FakeApiTransport()
    private val api = transport.endpoints()
    private val invalidations = Invalidations()
    private val uiCache = UiCache(File(context.cacheDir, "ui-cache-test"), "test")
    val timeline = TimelineRepository(api, invalidations, uiCache, scope)
    private val albums = AlbumsRepository(api, invalidations, scope)
    private val drive = DriveRepository(api, invalidations, uiCache, scope)
    private val telegram = TelegramMediaRepository(api, invalidations)
    private val exporter = MediaExporter(context, BentoHttp(OkHttpClient(), EndpointProvider { error("no engine in JVM tests") }))
    private val prefs = MediaPreferences(context)
    val actions: MediaActions = MediaActions(timeline, albums, drive, telegram, exporter, prefs).bind(scope)

    init {
        transport.on("POST /api/trash/restore") { """{"restored":1}""" }
        MediaSamples.library.forEach { asset ->
            transport.on("DELETE /api/assets/${asset.id}") { json(asset) }
            transport.on("POST /api/photos/${asset.id}/favorite") { call -> json(asset.copy(favorite = call.body?.contains("true") == true)) }
        }
    }

    private fun json(asset: AssetResponse) = BentoJson.encodeToString(AssetResponse.serializer(), asset)
}

/** Coil loader that answers every Bento image with a flat color (screenshots show filled tiles, deterministically). */
fun fakeImageLoader(context: Context): ImageLoader {
    val palette = intArrayOf(0xFF6E8BA8.toInt(), 0xFFB9A27A.toInt(), 0xFF8AA67F.toInt(), 0xFFC98A6B.toInt(), 0xFF7E7AA8.toInt(), 0xFFA8B5BF.toInt())
    val engine = FakeImageLoaderEngine.Builder()
        .default(
            coil3.intercept.Interceptor { chain ->
                val id = (chain.request.data as? dev.bento.api.BentoImage)?.assetId.orEmpty()
                coil3.request.SuccessResult(
                    image = coil3.test.FakeImage(width = 64, height = 64, color = palette[Math.floorMod(id.hashCode(), palette.size)]),
                    request = chain.request,
                    dataSource = coil3.decode.DataSource.MEMORY
                )
            }
        )
        .build()
    return ImageLoader.Builder(context)
        .components { add(engine) }
        .coroutineContext(kotlinx.coroutines.Dispatchers.Unconfined)
        .build()
}
