package dev.bento.feature.pairing

import dev.bento.api.generated.BentoEndpoints
import dev.bento.api.generated.PairingJoinRequest
import dev.bento.api.generated.PairingRequestItem
import dev.bento.api.generated.PairingResponse
import dev.bento.api.generated.SyncStatusResponse
import javax.inject.Inject
import javax.inject.Singleton

/**
 * `/api/pairing*` (api/telegram-first-endpoints.md § Pairing). Sessions live in the engine's memory; a restarted
 * engine forgets them (`GET` answers 404, shown as "Este código ya no es válido").
 */
@Singleton
class PairingRepository @Inject constructor(private val api: BentoEndpoints) {
    // Host (this phone shows the code).
    suspend fun host(): PairingResponse = api.hostPairing()

    suspend fun approve(id: String): PairingResponse = api.approvePairing(id)

    suspend fun reject(id: String): PairingResponse = api.rejectPairing(id)

    // Guest (this phone joins).
    suspend fun join(codeOrLink: String): PairingResponse = api.joinPairing(PairingJoinRequest(codeOrLink))

    /** Sync-channel fallback ("Pedir acceso a mis otros dispositivos"); needs Telegram sign-in. */
    suspend fun request(): PairingResponse = api.requestPairing()

    /** Fallback guest pressed `Coinciden`. */
    suspend fun confirm(id: String): PairingResponse = api.confirmPairing(id)

    suspend fun get(id: String): PairingResponse = api.getPairing(id)

    /** Cancel ("No coinciden", leaving the screen). */
    suspend fun cancel(id: String): PairingResponse = api.cancelPairing(id)

    // Fallback requests seen by this phone as host.
    suspend fun requests(): List<PairingRequestItem> = api.listPairingRequests().items

    suspend fun review(requestId: String): PairingResponse = api.reviewPairingRequest(requestId)

    suspend fun approveRequest(requestId: String): PairingResponse = api.approvePairingRequest(requestId)

    suspend fun rejectRequest(requestId: String): PairingResponse = api.rejectPairingRequest(requestId)

    suspend fun syncStatus(): SyncStatusResponse = api.syncStatus()

    /**
     * Follows `GET /pairing/{id}` every [intervalMs] until the session ends. [current] is the screen's latest copy:
     * a late poll never undoes a local decision that already ended it. A 404 (engine restarted) ends it as
     * `failed` / `pairing_not_found`; other errors are retried on the next tick.
     */
    suspend fun follow(id: String, current: () -> PairingResponse?, onUpdate: (PairingResponse) -> Unit, intervalMs: Long = POLL_MS) {
        while (true) {
            kotlinx.coroutines.delay(intervalMs)
            val local = current() ?: return
            if (isTerminal(local)) return
            val next = fetch(id, local)
            if (next != null) {
                onUpdate(next)
                if (isTerminal(next)) return
            }
        }
    }

    private suspend fun fetch(id: String, local: PairingResponse): PairingResponse? = try {
        get(id)
    } catch (cancel: kotlinx.coroutines.CancellationException) {
        throw cancel
    } catch (error: dev.bento.api.ApiException) {
        if (error is dev.bento.api.ApiException.Http && error.status == HTTP_NOT_FOUND) {
            local.copy(state = "failed", error = dev.bento.api.generated.PairingErrorResponse("pairing_not_found", ""))
        } else {
            null
        }
    }

    companion object {
        const val POLL_MS = 1_000L
        private const val HTTP_NOT_FOUND = 404
        val TERMINAL = setOf("completed", "rejected", "failed", "expired", "cancelled")

        fun isTerminal(pairing: PairingResponse): Boolean = pairing.state in TERMINAL

        /** A Sync-channel guest must confirm the emojis itself before any access is accepted. */
        fun needsGuestConfirmation(p: PairingResponse): Boolean =
            p.role == "guest" && p.transport == "telegram" && p.state == "awaiting_approval" && p.sas != null
    }
}

/** Backend/relay error codes grouped into what a person can act on (apps/web `pairingErrors.ts`). */
enum class PairingProblem {
    WrongCode,
    NotFound,
    RelayUnavailable,
    RateLimited,
    TelegramLogin,
    Network,
    RequestTaken,
    VaultAmbiguous,
    DeviceRemoved,
    Generic
}

@Suppress("CyclomaticComplexMethod")
fun pairingProblem(code: String?): PairingProblem {
    val value = code.orEmpty().lowercase()
    return when {
        value.isEmpty() -> PairingProblem.Generic
        value == "pairing_request_taken" -> PairingProblem.RequestTaken
        value == "pairing_vault_ambiguous" -> PairingProblem.VaultAmbiguous
        value == "pairing_device_removed" -> PairingProblem.DeviceRemoved
        "relay" in value || value == "pairing_unavailable" || value == "storage_unavailable" -> PairingProblem.RelayUnavailable
        "rate_limit" in value || "flood" in value -> PairingProblem.RateLimited
        "room_not_found" in value || "not_found" in value || "expired" in value -> PairingProblem.NotFound
        "telegram_login" in value || "login_failed" in value -> PairingProblem.TelegramLogin
        "network" in value || "timeout" in value || "offline" in value || value == "engine_unavailable" -> PairingProblem.Network
        listOf("code", "mismatch", "confirm", "spake", "protocol").any { it in value } -> PairingProblem.WrongCode
        else -> PairingProblem.Generic
    }
}

fun pairingProblemText(problem: PairingProblem): Int = when (problem) {
    PairingProblem.WrongCode -> dev.bento.strings.R.string.pairing_problem_wrong_code
    PairingProblem.NotFound -> dev.bento.strings.R.string.pairing_problem_not_found
    PairingProblem.RelayUnavailable -> dev.bento.strings.R.string.pairing_problem_relay
    PairingProblem.RateLimited -> dev.bento.strings.R.string.pairing_problem_rate_limited
    PairingProblem.TelegramLogin -> dev.bento.strings.R.string.pairing_problem_telegram_login
    PairingProblem.Network -> dev.bento.strings.R.string.pairing_problem_network
    PairingProblem.RequestTaken -> dev.bento.strings.R.string.pairing_problem_request_taken
    PairingProblem.VaultAmbiguous -> dev.bento.strings.R.string.pairing_problem_vault_ambiguous
    PairingProblem.DeviceRemoved -> dev.bento.strings.R.string.pairing_problem_device_removed
    PairingProblem.Generic -> dev.bento.strings.R.string.pairing_problem_generic
}
