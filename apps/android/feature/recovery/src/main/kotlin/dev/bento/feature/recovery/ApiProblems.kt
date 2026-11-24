package dev.bento.feature.recovery

import dev.bento.api.ApiErrorKind
import dev.bento.api.ApiException
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull

/**
 * What a trust screen needs to know about a failed call: the backend error `code` (api/error-model.md) and, for
 * Telegram flood waits, how long to wait. Shared by onboarding, pairing, recovery and devices.
 */
data class ApiProblem(val code: String, val retryAfterSeconds: Long? = null, val status: Int? = null) {
    val isNetwork: Boolean get() = code == NETWORK || code == "telegram_network"

    companion object {
        const val NETWORK = "network_error"
        const val ENGINE = "engine_unavailable"
        const val UNKNOWN = "request_failed"

        fun from(error: Throwable): ApiProblem = when (error) {
            is ApiException.Http -> ApiProblem(
                code = error.code,
                retryAfterSeconds = error.retryAfterSeconds
                    ?: (error.details?.get("retry_after_seconds") as? JsonPrimitive)?.longOrNull,
                status = error.status
            )

            is ApiException.Network, is ApiException.Stalled -> ApiProblem(NETWORK)

            is ApiException.EngineUnavailable -> ApiProblem(ENGINE)

            else -> ApiProblem(UNKNOWN)
        }

        /** An error carried inside a 200 response (`AccountStatus.error`, `Pairing.error`). */
        fun fromBody(code: String, details: Map<String, kotlinx.serialization.json.JsonElement>?): ApiProblem =
            ApiProblem(code, (details?.get("retry_after_seconds") as? JsonPrimitive)?.longOrNull)
    }
}

/** Runs [block], turning API failures into [ApiProblem]s; cancellation still propagates. */
suspend fun <T> attempt(block: suspend () -> T): Outcome<T> = try {
    Outcome.Ok(block())
} catch (cancel: kotlinx.coroutines.CancellationException) {
    throw cancel
} catch (error: ApiException) {
    Outcome.Err(ApiProblem.from(error))
}

/** A call's outcome, so screen state machines handle both branches explicitly. */
sealed interface Outcome<out T> {
    data class Ok<T>(val value: T) : Outcome<T>

    data class Err(val problem: ApiProblem) : Outcome<Nothing>
}

/** True for a 409 conflict (already exists / wrong state). */
fun ApiException.isConflict(): Boolean = this is ApiException.Http && kind == ApiErrorKind.CONFLICT
