package dev.bento.api

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** Machine-readable error categories (api/error-model.md HTTP mapping). UI maps `code` to localized copy. */
enum class ApiErrorKind {
    BAD_REQUEST,
    UNAUTHORIZED,
    NOT_FOUND,
    CONFLICT,
    PAYLOAD_TOO_LARGE,
    UNSUPPORTED_MEDIA,
    VALIDATION,
    RATE_LIMITED,
    SERVER,
    UNAVAILABLE
}

/** Every failure a repository can see from the local API. */
sealed class ApiException(message: String, cause: Throwable? = null) : Exception(message, cause) {
    /** The backend answered with an error body (`{"error": {code, message, details, request_id}}`). */
    class Http(
        val status: Int,
        val kind: ApiErrorKind,
        val code: String,
        val detailMessage: String,
        val details: JsonObject?,
        val requestId: String?,
        val retryAfterSeconds: Long?
    ) : ApiException("HTTP $status $code")

    /** The engine is not running (no holder, starting too long, or crash loop). */
    class EngineUnavailable(cause: Throwable? = null) : ApiException("engine unavailable", cause)

    /** The loopback call stalled (read/call timeout); the engine was asked to check the API. */
    class Stalled(cause: Throwable? = null) : ApiException("loopback call stalled", cause)

    /** Transport failure other than a timeout. */
    class Network(cause: Throwable) : ApiException("network error", cause)

    /** The body did not match the generated DTO (snapshot drift). */
    class Decoding(cause: Throwable) : ApiException("response decoding failed", cause)

    val isRetryable: Boolean
        get() = when (this) {
            is Http -> kind == ApiErrorKind.RATE_LIMITED || kind == ApiErrorKind.UNAVAILABLE || kind == ApiErrorKind.SERVER
            is EngineUnavailable, is Stalled, is Network -> true
            is Decoding -> false
        }
}

/** Pure mapping from an HTTP error response to [ApiException.Http] (JVM tested). */
object ApiErrors {
    private val json = Json { ignoreUnknownKeys = true }

    fun kindFor(status: Int): ApiErrorKind = when (status) {
        401, 403 -> ApiErrorKind.UNAUTHORIZED
        404 -> ApiErrorKind.NOT_FOUND
        409 -> ApiErrorKind.CONFLICT
        413 -> ApiErrorKind.PAYLOAD_TOO_LARGE
        415 -> ApiErrorKind.UNSUPPORTED_MEDIA
        422 -> ApiErrorKind.VALIDATION
        429 -> ApiErrorKind.RATE_LIMITED
        503 -> ApiErrorKind.UNAVAILABLE
        in 500..599 -> ApiErrorKind.SERVER
        else -> ApiErrorKind.BAD_REQUEST
    }

    fun from(status: Int, body: String?, retryAfter: String? = null): ApiException.Http {
        val root = body?.takeIf { it.isNotBlank() }?.let { runCatching { json.parseToJsonElement(it).jsonObject }.getOrNull() }
        val error = root?.get("error") as? JsonObject
        val detail = root?.get("detail")
        val code = error?.string("code")
            ?: if (status == 422 && detail is JsonArray) "validation_failed" else defaultCode(status)
        val message = error?.string("message") ?: (detail?.let { (it as? kotlinx.serialization.json.JsonPrimitive)?.contentOrNull }) ?: code
        return ApiException.Http(
            status = status,
            kind = kindFor(status),
            code = code,
            detailMessage = message,
            details = error?.get("details") as? JsonObject,
            requestId = error?.string("request_id"),
            retryAfterSeconds = retryAfter?.trim()?.toLongOrNull()
                ?: (error?.get("details") as? JsonObject)?.string("retry_after")?.toLongOrNull()
        )
    }

    private fun defaultCode(status: Int): String = when (status) {
        401 -> "api_token_required"
        404 -> "not_found"
        else -> "http_$status"
    }

    private fun JsonObject.string(key: String): String? = (this[key] as? kotlinx.serialization.json.JsonPrimitive)?.contentOrNull
}
