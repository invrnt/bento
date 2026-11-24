package dev.bento.feature.pairing

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dev.bento.api.generated.PairingResponse
import dev.bento.engine.di.ApplicationScope
import dev.bento.feature.recovery.Outcome
import dev.bento.feature.recovery.attempt
import javax.inject.Inject
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/** Phases of "Añadir dispositivo" with this phone as host (apps/web `AddDeviceDialog`). */
enum class HostPhase { Loading, RelayUnavailable, StartFailed, Code, Approve, Approving, GuestLogin, Completed, Rejected, Expired, Failed }

data class HostState(
    val pairing: PairingResponse? = null,
    val starting: Boolean = true,
    val startProblem: PairingProblem? = null,
    val acting: Boolean = false,
    val actionFailed: Boolean = false,
    val secondsLeft: Long? = null
) {
    val phase: HostPhase
        get() = when {
            starting -> HostPhase.Loading

            startProblem == PairingProblem.RelayUnavailable -> HostPhase.RelayUnavailable

            startProblem != null || pairing == null -> HostPhase.StartFailed

            else -> when (pairing.state) {
                "awaiting_approval" -> HostPhase.Approve

                "approving", "bootstrapping" -> HostPhase.Approving

                "needs_telegram_login" -> HostPhase.GuestLogin

                "completed" -> HostPhase.Completed

                "rejected", "cancelled" -> HostPhase.Rejected

                "expired" -> HostPhase.Expired

                "failed" -> if (pairingProblem(pairing.error?.code) ==
                    PairingProblem.RelayUnavailable
                ) {
                    HostPhase.RelayUnavailable
                } else {
                    HostPhase.Failed
                }

                else -> if (secondsLeft == 0L) HostPhase.Expired else HostPhase.Code
            }
        }
}

@HiltViewModel
class HostPairingViewModel @Inject constructor(
    private val repo: PairingRepository,
    @ApplicationScope private val appScope: CoroutineScope
) : ViewModel() {
    private val _state = MutableStateFlow(HostState())
    val state: StateFlow<HostState> = _state.asStateFlow()
    private var polling: Job? = null
    private var countdown: Job? = null
    private var closed = false

    init {
        start()
    }

    fun start() {
        stop()
        closed = false
        _state.value = HostState()
        viewModelScope.launch {
            when (val result = attempt { repo.host() }) {
                is Outcome.Ok -> {
                    _state.update { it.copy(starting = false, pairing = result.value) }
                    follow()
                }

                is Outcome.Err -> _state.update { it.copy(starting = false, startProblem = pairingProblem(result.problem.code)) }
            }
        }
    }

    fun decide(approve: Boolean) {
        val current = _state.value.pairing ?: return
        if (_state.value.acting) return
        _state.update { it.copy(acting = true, actionFailed = false) }
        viewModelScope.launch {
            when (val result = attempt { if (approve) repo.approve(current.id) else repo.reject(current.id) }) {
                is Outcome.Ok -> _state.update { it.copy(acting = false, pairing = result.value) }
                is Outcome.Err -> _state.update { it.copy(acting = false, actionFailed = true) }
            }
        }
    }

    /** Leaving the screen cancels a session that is still open. */
    fun close() {
        val current = _state.value.pairing
        stop()
        if (closed) return
        closed = true
        if (current != null && !PairingRepository.isTerminal(current)) {
            // Survives this screen's scope: closing must still cancel the session in the engine.
            appScope.launch { attempt { repo.cancel(current.id) } }
        }
    }

    private fun follow() {
        startCountdown()
        val id = _state.value.pairing?.id ?: return
        polling = viewModelScope.launch {
            repo.follow(id, current = { _state.value.pairing }, onUpdate = { next -> _state.update { it.copy(pairing = next) } })
        }
    }

    private fun startCountdown() {
        countdown?.cancel()
        val expires =
            _state.value.pairing?.expiresAt?.let {
                runCatching { java.time.OffsetDateTime.parse(it).toInstant().toEpochMilli() }.getOrNull()
            }
                ?: return
        countdown = viewModelScope.launch {
            var left = ((expires - System.currentTimeMillis()) / TICK_MS).coerceAtLeast(0)
            while (isActive) {
                _state.update { it.copy(secondsLeft = left) }
                if (left == 0L) break
                delay(TICK_MS)
                left--
            }
        }
    }

    private fun stop() {
        polling?.cancel()
        countdown?.cancel()
    }

    override fun onCleared() = close()

    private companion object {
        const val TICK_MS = 1_000L
    }
}
