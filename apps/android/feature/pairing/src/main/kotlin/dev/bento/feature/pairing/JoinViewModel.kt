package dev.bento.feature.pairing

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dev.bento.api.generated.AccountStatusResponse
import dev.bento.api.generated.PairingResponse
import dev.bento.feature.onboarding.AppGateResolver
import dev.bento.feature.onboarding.LoginRepository
import dev.bento.feature.recovery.Outcome
import dev.bento.feature.recovery.VaultRepository
import dev.bento.feature.recovery.attempt
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/** Steps of joining an existing cloud (product/android.md §4.2; apps/web `JoinScreen`). */
enum class JoinStep { Checking, Entry, Pairing, SignIn, Choose, Recovery, NoVault, Bootstrap, Already }

/** In-app scanner first; typing is one tap away (and the only way without a camera). */
enum class EntryMode { Scan, Type }

data class BootstrapProgress(val done: Long = 0, val total: Long = 0, val finished: Boolean = false) {
    val fraction: Float? get() = if (total > 0) (done.toFloat() / total).coerceIn(0f, 1f) else null
}

/** While the host could not sign this phone in (`needs_telegram_login`): what this phone can still do. */
data class GuestLogin(
    val passwordRequired: Boolean = false,
    val passwordHint: String? = null,
    val loginUrl: String? = null,
    val busy: Boolean = false,
    val passwordInvalid: Boolean = false,
    /**
     * Signing in with the phone number inside the pairing (api/android-endpoints.md §11 Pairing while signing in): the
     * session stays open, stops offering a Telegram QR, and continues by itself once `/account` is authorized.
     */
    val phone: Boolean = false
)

data class JoinState(
    val step: JoinStep = JoinStep.Checking,
    val entryMode: EntryMode = EntryMode.Scan,
    val prefill: String? = null,
    val joining: Boolean = false,
    val joinProblem: PairingProblem? = null,
    val requesting: Boolean = false,
    val requestProblem: PairingProblem? = null,
    val pairing: PairingResponse? = null,
    val confirming: Boolean = false,
    val confirmFailed: Boolean = false,
    val mismatch: Boolean = false,
    val guestLogin: GuestLogin = GuestLogin(),
    val bootstrap: BootstrapProgress = BootstrapProgress(),
    val checkingVault: Boolean = false,
    val recoveryReturn: JoinStep = JoinStep.Choose
)

sealed interface JoinEffect {
    /** Joined (or already a member): land in Fotos while the library fills. */
    data object Done : JoinEffect

    /** Signed in, but the account has no cloud yet: create it (onboarding). */
    data object CreateVault : JoinEffect

    data class OpenTelegramLogin(val url: String) : JoinEffect
}

@HiltViewModel
class JoinViewModel @Inject constructor(
    private val pairing: PairingRepository,
    private val vault: VaultRepository,
    private val login: LoginRepository,
    private val gate: AppGateResolver
) : ViewModel() {
    private val _state = MutableStateFlow(JoinState())
    val state: StateFlow<JoinState> = _state.asStateFlow()
    private val effects = Channel<JoinEffect>(Channel.BUFFERED)
    val effect: Flow<JoinEffect> = effects.receiveAsFlow()
    private var polling: Job? = null
    private var bootstrapJob: Job? = null
    private var started = false

    /** [code] comes from `bento://join` / App Links (prefilled, never auto-joined); [choose] starts at the join choice. */
    fun start(code: String?, choose: Boolean) {
        if (started) return
        started = true
        val prefill = code?.let {
            PairingCodes.fromScanOrPaste(it)
                ?: dev.bento.designsystem.component.CrockfordCode.normalize(it).take(PairingCodes.LENGTH)
        }
        _state.update { it.copy(prefill = prefill, entryMode = if (prefill != null) EntryMode.Type else EntryMode.Scan) }
        viewModelScope.launch {
            val status = (attempt { vault.status() } as? Outcome.Ok)?.value
            val step = when {
                choose -> JoinStep.Choose
                status?.state == "ready" || status?.state == "bootstrapping" -> JoinStep.Already
                else -> JoinStep.Entry
            }
            _state.update { it.copy(step = step) }
        }
    }

    fun setEntryMode(mode: EntryMode) = _state.update { it.copy(entryMode = mode, joinProblem = null) }

    fun clearJoinProblem() = _state.update { it.copy(joinProblem = null) }

    fun join(code: String) {
        val normalized = dev.bento.designsystem.component.CrockfordCode.normalize(code)
        if (normalized.length != PairingCodes.LENGTH || _state.value.joining) return
        _state.update { it.copy(joining = true, joinProblem = null) }
        viewModelScope.launch {
            when (val result = attempt { pairing.join(PairingCodes.format(normalized)) }) {
                is Outcome.Ok -> follow(result.value)
                is Outcome.Err -> _state.update { it.copy(joining = false, joinProblem = pairingProblem(result.problem.code)) }
            }
        }
    }

    fun noOtherDevice() = leavePairing(JoinStep.SignIn)

    /** After Telegram sign-in: the account's cloud decides the next step. */
    fun signedIn() {
        _state.update { it.copy(checkingVault = true) }
        viewModelScope.launch {
            val status = (attempt { vault.status() } as? Outcome.Ok)?.value
            _state.update { it.copy(checkingVault = false) }
            when (status?.state) {
                "no_vault" -> _state.update { it.copy(step = JoinStep.NoVault) }
                "ready" -> finish()
                "bootstrapping" -> toBootstrap()
                else -> _state.update { it.copy(step = JoinStep.Choose) }
            }
        }
    }

    fun requestAccess() {
        if (_state.value.requesting) return
        _state.update { it.copy(requesting = true, requestProblem = null) }
        viewModelScope.launch {
            when (val result = attempt { pairing.request() }) {
                is Outcome.Ok -> follow(result.value)
                is Outcome.Err -> _state.update { it.copy(requesting = false, requestProblem = pairingProblem(result.problem.code)) }
            }
        }
    }

    fun openRecovery(from: JoinStep) = _state.update { it.copy(step = JoinStep.Recovery, recoveryReturn = from) }

    fun recoveryBack() = _state.update { it.copy(step = it.recoveryReturn) }

    fun unlocked() = toBootstrap()

    fun haveCode() = _state.update { it.copy(step = JoinStep.Entry) }

    fun createVault() {
        effects.trySend(JoinEffect.CreateVault)
    }

    /** `Coinciden`: only now does this phone accept the access granted by the device behind these emojis. */
    fun confirmMatch() {
        val current = _state.value.pairing ?: return
        if (_state.value.confirming) return
        _state.update { it.copy(confirming = true, confirmFailed = false) }
        viewModelScope.launch {
            when (val result = attempt { pairing.confirm(current.id) }) {
                is Outcome.Ok -> _state.update { it.copy(confirming = false, pairing = result.value) }
                is Outcome.Err -> _state.update { it.copy(confirming = false, confirmFailed = true) }
            }
        }
    }

    /** `No coinciden`: stop here; without a confirmation the engine never installs a grant, even if this call fails. */
    fun rejectMatch() {
        val current = _state.value.pairing ?: return
        stopPolling()
        _state.update { it.copy(mismatch = true) }
        viewModelScope.launch {
            (attempt { pairing.cancel(current.id) } as? Outcome.Ok)?.let { ok -> _state.update { it.copy(pairing = ok.value) } }
        }
    }

    /** Leaves the pairing (cancelling it if still running) for [next]. */
    fun leavePairing(next: JoinStep) {
        val current = _state.value.pairing
        stopPolling()
        if (current != null && !PairingRepository.isTerminal(current)) {
            viewModelScope.launch { attempt { pairing.cancel(current.id) } }
        }
        _state.update { it.copy(step = next, pairing = null, mismatch = false, confirmFailed = false, joining = false, requesting = false) }
    }

    fun retry() = leavePairing(if (_state.value.pairing?.transport == "telegram") JoinStep.Choose else JoinStep.Entry)

    // needs_telegram_login -----------------------------------------------------------------------------------

    fun continueWithTelegram() {
        viewModelScope.launch {
            val status = (attempt { login.status() } as? Outcome.Ok)?.value
            val url = status?.qrUrl ?: (attempt { login.startQr() } as? Outcome.Ok)?.value?.qrUrl
            url?.let { effects.send(JoinEffect.OpenTelegramLogin(it)) }
        }
    }

    fun submitPassword(password: String) {
        if (password.isEmpty() || _state.value.guestLogin.busy) return
        _state.update { it.copy(guestLogin = it.guestLogin.copy(busy = true, passwordInvalid = false)) }
        viewModelScope.launch {
            val result = attempt { login.submitPassword(password) }
            val status = (result as? Outcome.Ok)?.value
            _state.update {
                it.copy(
                    guestLogin = it.guestLogin.copy(
                        busy = false,
                        passwordInvalid =
                            status?.error?.code == "telegram_password_invalid" || result is Outcome.Err
                    )
                )
            }
        }
    }

    /** `Usar mi número de teléfono` while the pairing waits for a Telegram login: keep the pairing, sign in here. */
    fun usePhoneDuringPairing() = _state.update { it.copy(guestLogin = it.guestLogin.copy(phone = true)) }

    /** Back from the phone sign-in (the pairing still waits), or it finished: the pairing screen takes over again. */
    fun phoneLoginClosed() = _state.update { it.copy(guestLogin = it.guestLogin.copy(phone = false)) }

    fun bootstrapContinue() = finish()

    // internals ---------------------------------------------------------------------------------------------

    private fun follow(initial: PairingResponse) {
        _state.update { it.copy(step = JoinStep.Pairing, pairing = initial, joining = false, requesting = false, mismatch = false) }
        onPairing(initial)
        stopPolling()
        polling = viewModelScope.launch {
            pairing.follow(initial.id, current = { _state.value.pairing }, onUpdate = { next ->
                _state.update { it.copy(pairing = next) }
                onPairing(next)
            })
        }
    }

    private fun onPairing(p: PairingResponse) {
        when (p.state) {
            "bootstrapping", "completed" -> if (p.role == "guest") toBootstrap()
            "needs_telegram_login" -> refreshGuestLogin()
        }
    }

    private fun refreshGuestLogin() {
        viewModelScope.launch {
            val status: AccountStatusResponse = (attempt { login.status() } as? Outcome.Ok)?.value ?: return@launch
            _state.update {
                it.copy(
                    guestLogin = it.guestLogin.copy(
                        passwordRequired = status.step == "password_required",
                        passwordHint = status.passwordHint,
                        loginUrl = status.qrUrl,
                        // A phone login already in flight (e.g. after the screen was recreated) resumes at its code.
                        phone = it.guestLogin.phone || status.step == "code_required"
                    )
                )
            }
        }
    }

    private fun toBootstrap() {
        if (bootstrapJob?.isActive == true || _state.value.step == JoinStep.Bootstrap) return
        stopPolling()
        _state.update { it.copy(step = JoinStep.Bootstrap) }
        bootstrapJob = viewModelScope.launch {
            var elapsed = 0L
            while (isActive) {
                val status = (attempt { pairing.syncStatus() } as? Outcome.Ok)?.value
                val done = status?.bootstrap?.done ?: 0
                val total = status?.bootstrap?.total ?: 0
                val running = status?.state == "bootstrapping" || (total > 0 && done < total)
                _state.update { it.copy(bootstrap = BootstrapProgress(done, total, finished = status != null && !running)) }
                // "Descargando tu biblioteca…" for at most 2 s, then Fotos fills progressively (§4.2).
                if (_state.value.bootstrap.finished || elapsed >= BOOTSTRAP_HOLD_MS) break
                delay(BOOTSTRAP_POLL_MS)
                elapsed += BOOTSTRAP_POLL_MS
            }
            finish()
        }
    }

    private fun finish() {
        gate.finishedSetup()
        effects.trySend(JoinEffect.Done)
    }

    private fun stopPolling() {
        polling?.cancel()
        polling = null
    }

    companion object {
        const val BOOTSTRAP_POLL_MS = 500L
        const val BOOTSTRAP_HOLD_MS = 2_000L
    }
}
