package dev.bento.testing

import dev.bento.api.ApiErrors
import dev.bento.api.BentoJson
import dev.bento.api.generated.ApiTransport
import dev.bento.api.generated.BentoEndpoints
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.serialization.KSerializer

/** A recorded call to [FakeApiTransport]. */
data class FakeCall(val method: String, val path: String, val query: Map<String, String>, val body: String?)

/**
 * In-memory [ApiTransport]: route handlers return JSON text (decoded with the real [BentoJson] and generated
 * serializers, so DTO drift breaks tests too). Unrouted calls fail like a 404.
 */
class FakeApiTransport : ApiTransport {
    private val routes = LinkedHashMap<String, (FakeCall) -> String>()
    val calls = CopyOnWriteArrayList<FakeCall>()

    /** Route `"GET /api/photos/timeline"`; [handler] returns the JSON body. */
    fun on(route: String, handler: (FakeCall) -> String) {
        routes[route] = handler
    }

    /** Route that answers with an error body (`{"error": {...}}`). */
    fun fail(route: String, status: Int, code: String) {
        routes[route] = { throw ApiErrors.from(status, """{"error":{"code":"$code","message":"$code"}}""") }
    }

    fun endpoints(): BentoEndpoints = BentoEndpoints(this)

    fun count(route: String): Int = calls.count { "${it.method} ${it.path}" == route }

    override suspend fun <B, R> call(
        method: String,
        path: String,
        query: List<Pair<String, String?>>,
        body: B?,
        bodySerializer: KSerializer<B>?,
        responseSerializer: KSerializer<R>
    ): R {
        val call = FakeCall(
            method = method,
            path = path,
            query = query.mapNotNull { (k, v) -> v?.let { k to it } }.toMap(),
            body = if (body != null && bodySerializer != null) BentoJson.encodeToString(bodySerializer, body) else null
        )
        calls += call
        val handler = routes["$method $path"] ?: throw ApiErrors.from(404, """{"error":{"code":"not_found","message":"$path"}}""")
        return BentoJson.decodeFromString(responseSerializer, handler(call))
    }

    override fun encodePath(value: String): String = value
}
