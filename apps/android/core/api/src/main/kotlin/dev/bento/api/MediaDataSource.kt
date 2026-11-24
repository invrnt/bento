package dev.bento.api

import android.net.Uri
import androidx.annotation.OptIn
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.ResolvingDataSource
import androidx.media3.datasource.okhttp.OkHttpDataSource
import dev.bento.engine.EngineState
import okhttp3.OkHttpClient

/**
 * Media3 data source for `bento://asset/<id>` URIs: resolved to the loopback `/content` route (Range
 * requests) at open time, with the token added by [LoopbackAuthInterceptor]. Use
 * `MediaItem.fromUri(BentoMediaUris.asset(id))` with `DefaultMediaSourceFactory(bentoDataSourceFactory(...))`.
 */
object BentoMediaUris {
    const val SCHEME = "bento"

    fun asset(assetId: String): Uri = Uri.Builder().scheme(SCHEME).authority("asset").appendPath(assetId).build()
}

/** Pure resolution (JVM tested): returns the loopback URL or null when the URI is not ours. */
fun resolveBentoMediaUri(uri: String, ready: EngineState.Ready?): String? {
    val prefix = "${BentoMediaUris.SCHEME}://asset/"
    if (!uri.startsWith(prefix)) return null
    val id = uri.removePrefix(prefix).substringBefore('?').substringBefore('#')
    val state = ready ?: throw ApiException.EngineUnavailable()
    return state.baseUrl + AssetPaths.content(id)
}

@OptIn(UnstableApi::class)
fun bentoDataSourceFactory(client: OkHttpClient, current: () -> EngineState.Ready?): DataSource.Factory =
    ResolvingDataSource.Factory(OkHttpDataSource.Factory(client)) { spec: DataSpec ->
        resolveBentoMediaUri(spec.uri.toString(), current())?.let { spec.withUri(Uri.parse(it)) } ?: spec
    }
