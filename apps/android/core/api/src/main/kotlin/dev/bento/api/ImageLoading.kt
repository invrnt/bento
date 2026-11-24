package dev.bento.api

import android.content.Context
import coil3.ImageLoader
import coil3.disk.DiskCache
import coil3.disk.directory
import coil3.fetch.Fetcher
import coil3.key.Keyer
import coil3.memory.MemoryCache
import coil3.network.NetworkFetcher
import coil3.network.okhttp.OkHttpNetworkFetcherFactory
import coil3.request.Options
import coil3.size.pxOrElse
import coil3.toUri

/**
 * Coil model for Bento images. Use it directly in `AsyncImage(model = BentoImage.thumbnail(id))`.
 * [etag] (`thumbnail_etag` from the timeline) is part of the cache key, so a regenerated thumbnail is
 * fetched again while unchanged ones are served from cache across engine restarts (the port changes).
 */
data class BentoImage(val assetId: String, val kind: Kind, val etag: String? = null) {
    enum class Kind { THUMBNAIL, PREVIEW, ORIGINAL }

    companion object {
        fun thumbnail(assetId: String, etag: String? = null) = BentoImage(assetId, Kind.THUMBNAIL, etag)

        fun preview(assetId: String) = BentoImage(assetId, Kind.PREVIEW)

        /** Full-resolution bytes (`/content`): the viewer's last progressive step; Telephoto subsamples it from disk cache. */
        fun original(assetId: String, etag: String? = null) = BentoImage(assetId, Kind.ORIGINAL, etag)
    }
}

/** Requested pixel size → `?size=` hint (thumbnails only). */
internal fun sizeHint(options: Options): ThumbnailSize {
    val width = options.size.width.pxOrElse { 0 }
    val height = options.size.height.pxOrElse { 0 }
    val longest = maxOf(width, height).takeIf { it > 0 } ?: ThumbnailSize.SMALL.px
    return ThumbnailSize.atLeast(longest)
}

internal fun cacheKey(image: BentoImage, size: ThumbnailSize?): String =
    listOfNotNull("bento", image.kind.name.lowercase(), image.assetId, size?.px?.toString(), image.etag).joinToString(":")

class BentoImageKeyer : Keyer<BentoImage> {
    override fun key(data: BentoImage, options: Options): String =
        cacheKey(data, if (data.kind == BentoImage.Kind.THUMBNAIL) sizeHint(options) else null)
}

/**
 * Resolves [BentoImage] to the loopback URL at fetch time (awaiting the engine) and delegates to Coil's
 * OkHttp network fetcher with a port-independent disk cache key.
 */
class BentoImageFetcher(
    private val image: BentoImage,
    private val options: Options,
    private val loader: ImageLoader,
    private val http: BentoHttp,
    private val network: NetworkFetcher.Factory
) : Fetcher {
    override suspend fun fetch() = run {
        val size = if (image.kind == BentoImage.Kind.THUMBNAIL) sizeHint(options) else null
        val path = when (image.kind) {
            BentoImage.Kind.THUMBNAIL -> AssetPaths.thumbnail(image.assetId)
            BentoImage.Kind.PREVIEW -> AssetPaths.preview(image.assetId)
            BentoImage.Kind.ORIGINAL -> AssetPaths.content(image.assetId)
        }
        val url = http.url(path, listOfNotNull(size?.let { "size" to it.px.toString() })).toString()
        val keyed = options.copy(diskCacheKey = cacheKey(image, size))
        val delegate = network.create(url.toUri(), keyed, loader) ?: error("network fetcher unavailable")
        delegate.fetch()
    }

    class Factory(private val http: BentoHttp, private val network: NetworkFetcher.Factory) : Fetcher.Factory<BentoImage> {
        override fun create(data: BentoImage, options: Options, imageLoader: ImageLoader): Fetcher =
            BentoImageFetcher(data, options, imageLoader, http, network)
    }
}

/** App image loader: memory cache 20 % of the app heap, disk cache in `cacheDir/images`. */
fun bentoImageLoader(context: Context, http: BentoHttp, client: okhttp3.OkHttpClient): ImageLoader {
    val network = OkHttpNetworkFetcherFactory(callFactory = { client })
    return ImageLoader.Builder(context)
        .memoryCache { MemoryCache.Builder().maxSizePercent(context, 0.20).build() }
        .diskCache { DiskCache.Builder().directory(context.cacheDir.resolve("images")).maxSizePercent(0.02).build() }
        .components {
            add(BentoImageKeyer())
            add(BentoImageFetcher.Factory(http, network))
        }
        .build()
}
