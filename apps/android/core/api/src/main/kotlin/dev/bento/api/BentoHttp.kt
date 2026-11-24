package dev.bento.api

import dev.bento.api.generated.ApiTransport
import dev.bento.engine.BentoEngine
import dev.bento.engine.EngineState
import dev.bento.engine.EngineUnavailableException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.IOException
import java.io.InterruptedIOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** Where the local API is: the engine's current port + token. Suspends until [EngineState.Ready]. */
fun interface EndpointProvider {
    suspend fun ready(): EngineState.Ready

    /** Called when a loopback call stalls; the engine checks/restarts the API. */
    fun reportStall() = Unit
}

class EngineEndpointProvider(private val engine: BentoEngine, private val timeoutMs: Long = BentoEngine.READY_TIMEOUT_MS) :
    EndpointProvider {
    override suspend fun ready(): EngineState.Ready = try {
        engine.awaitReady(timeoutMs)
    } catch (unavailable: EngineUnavailableException) {
        throw ApiException.EngineUnavailable(unavailable)
    }

    override fun reportStall() = engine.reportStall()
}

/** Shared JSON configuration for generated DTOs. */
val BentoJson: Json = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    encodeDefaults = false
    coerceInputValues = true
}

/**
 * Attaches the bearer token only to the engine's own loopback origin; any other host never sees it.
 * The token is read per request because the port and token change on every engine start.
 */
class LoopbackAuthInterceptor(private val current: () -> EngineState.Ready?) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val ready = current()
        val url = request.url
        val ours = ready != null && url.host == LOOPBACK && url.port == ready.port && url.scheme == "http"
        val authorized = if (ours) request.newBuilder().header("Authorization", "Bearer ${ready!!.token}").build() else request
        return chain.proceed(authorized)
    }

    companion object {
        const val LOOPBACK = "127.0.0.1"
    }
}

/** OkHttp client for the loopback API (short connect timeout: a frozen or dead engine fails fast). */
fun loopbackOkHttp(engine: BentoEngine, base: OkHttpClient = OkHttpClient()): OkHttpClient = base.newBuilder()
    .addInterceptor(LoopbackAuthInterceptor { engine.state.value as? EngineState.Ready })
    .connectTimeout(3, TimeUnit.SECONDS)
    .readTimeout(30, TimeUnit.SECONDS)
    .writeTimeout(5, TimeUnit.MINUTES)
    .retryOnConnectionFailure(true)
    .build()

/**
 * [ApiTransport] for the generated [dev.bento.api.generated.BentoEndpoints]: builds loopback URLs from the
 * engine state, encodes/decodes with [BentoJson], and maps every failure to [ApiException].
 */
class BentoHttp(
    private val client: OkHttpClient,
    private val endpoints: EndpointProvider,
    private val json: Json = BentoJson,
) : ApiTransport {
    override suspend fun <B, R> call(
        method: String,
        path: String,
        query: List<Pair<String, String?>>,
        body: B?,
        bodySerializer: KSerializer<B>?,
        responseSerializer: KSerializer<R>,
    ): R {
        val requestBody: RequestBody? = when {
            body != null && bodySerializer != null -> json.encodeToString(bodySerializer, body).toRequestBody(JSON)
            method in BODY_METHODS -> ByteArray(0).toRequestBody(null)
            else -> null
        }
        val text = execute(method, path, query, requestBody) { response -> response.body.string() }
        return try {
            json.decodeFromString(responseSerializer, text.ifEmpty { "null" })
        } catch (error: SerializationException) {
            throw ApiException.Decoding(error)
        } catch (error: IllegalArgumentException) {
            throw ApiException.Decoding(error)
        }
    }

    override fun encodePath(value: String): String = HttpUrl.Builder().scheme("http").host("x").addPathSegment(value).build()
        .encodedPathSegments.single()

    /** Absolute URL for [path] on the current engine port (for Coil/Media3 and downloads). */
    suspend fun url(path: String, query: List<Pair<String, String?>> = emptyList()): HttpUrl = buildUrl(endpoints.ready(), path, query)

    /** Runs a request and hands the successful response to [read] (still on the IO dispatcher). */
    suspend fun <T> execute(
        method: String,
        path: String,
        query: List<Pair<String, String?>> = emptyList(),
        body: RequestBody? = null,
        read: (Response) -> T,
    ): T {
        val ready = endpoints.ready()
        val request = Request.Builder().url(buildUrl(ready, path, query)).method(method, body).build()
        return withContext(Dispatchers.IO) {
            val response = try {
                client.newCall(request).await()
            } catch (timeout: InterruptedIOException) {
                endpoints.reportStall()
                throw ApiException.Stalled(timeout)
            } catch (io: IOException) {
                if (io is java.net.ConnectException) endpoints.reportStall()
                throw ApiException.Network(io)
            }
            response.use {
                if (!it.isSuccessful) throw ApiErrors.from(it.code, it.body.string(), it.header("Retry-After"))
                try {
                    read(it)
                } catch (timeout: InterruptedIOException) {
                    endpoints.reportStall()
                    throw ApiException.Stalled(timeout)
                }
            }
        }
    }

    private fun buildUrl(ready: EngineState.Ready, path: String, query: List<Pair<String, String?>>): HttpUrl {
        val builder = (ready.baseUrl + path).toHttpUrl().newBuilder()
        query.forEach { (key, value) -> if (value != null) builder.addQueryParameter(key, value) }
        return builder.build()
    }

    private companion object {
        val JSON = "application/json".toMediaType()
        val BODY_METHODS = setOf("POST", "PUT", "PATCH")
    }
}

internal suspend fun Call.await(): Response = suspendCancellableCoroutine { continuation ->
    enqueue(
        object : Callback {
            override fun onResponse(call: Call, response: Response) = continuation.resume(response)

            override fun onFailure(call: Call, e: IOException) {
                if (!continuation.isCancelled) continuation.resumeWithException(e)
            }
        },
    )
    continuation.invokeOnCancellation { runCatching { cancel() } }
}
