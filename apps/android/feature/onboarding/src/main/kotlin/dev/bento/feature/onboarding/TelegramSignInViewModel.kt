package dev.bento.feature.onboarding

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dev.bento.api.generated.AccountStatusResponse
import dev.bento.api.generated.TelegramAccountResponse
import dev.bento.feature.recovery.ApiProblem
import dev.bento.feature.recovery.Outcome
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

enum class SignInView { Options, Phone, Code, Password, Qr }

/** Login failures in the few situations a person can act on (web `loginErrors.ts` + flood wait). */
enum class SignInProblem {
    CodeInvalid,
    Expired,
    PasswordInvalid,
    PhoneInvalid,
    Network,
    NotAvailable,
    FloodWait,
    TelegramAppMissing,
    Generic
}

data class SignInState(
    val view: SignInView = SignInView.Options,
    val loading: Boolean = true,
    val busy: Boolean = false,
    /** True after `Continuar con Telegram` handed the login link to the Telegram app. */
    val awaitingTelegramApp: Boolean = false,
    val status: AccountStatusResponse? = null,
    val problem: SignInProblem? = null,
    /** Seconds left of a Telegram flood wait; the last action is retried by itself when it reaches 0. */
    val floodWaitSeconds: Long? = null,
    val country: Country = PhoneNumbers.preselect(null, null),
    val national: String = "",
    /** Seconds until `Reenviar código` is enabled again. */
    val resendSeconds: Int = 0,
    val authorized: TelegramAccountResponse? = null
) {
    /** Digits of the code Telegram sent (`code_length`), when it said; codes are 5 digits otherwise. */
    val codeLength: Int? get() = status?.codeLength?.toInt()?.takeIf { it in TelegramSignInViewModel.CODE_LENGTH_RANGE }

    /** The length that submits the code by itself. */
    val expectedCodeLength: Int get() = codeLength ?: TelegramSignInViewModel.CODE_LENGTH
}

sealed interface SignInEffect {
    /** Open `tg://login?token=…` in the Telegram app. */
    data class OpenTelegramLogin(val url: String) : SignInEffect
}

/**
 * Telegram sign-in state machine (port of apps/web `useTelegramLogin` for the phone): login-token link for the
 * Telegram app on this phone, phone → code → 2FA, or a QR for another phone. Polls `/account` while a token login
 * is pending, refreshes the token before it expires, and turns errors into [SignInProblem]s.
 */
@HiltViewModel
class TelegramSignInViewModel @Inject constructor(private val login: LoginRepository) : ViewModel() {
    private val _state = MutableStateFlow(SignInState())
    val state: StateFlow<SignInState> = _state.asStateFlow()
    private val effects = Channel<SignInEffect>(Channel.BUFFERED)
    val effect: Flow<SignInEffect> = effects.receiveAsFlow()

    private var polling: Job? = null
    private var floodJob: Job? = null
    private var resendJob: Job? = null
    private var lastAction: (suspend () -> Unit)? = null
    private var started = false

    /**
     * Reads the current login once (an interrupted code or 2FA step resumes there). [phoneFirst] opens on the phone
     * number instead of the options (pairing: the Telegram-app link and the QR are already on the pairing screen).
     */
    fun start(simIso: String?, networkIso: String?, phoneFirst: Boolean = false) {
        if (started) return
        started = true
        _state.update {
            it.copy(country = PhoneNumbers.preselect(simIso, networkIso), view = if (phoneFirst) SignInView.Phone else it.view)
        }
        val viewAtStart = _state.value.view
        viewModelScope.launch {
            val result = attempt { login.status() }
            // The engine can take a while on a cold start: once the person picked a way in or sent something, this
            // first read is stale and must not send them back to the options (or drop the code step).
            val stale = _state.value.view != viewAtStart || lastAction != null
            when {
                result is Outcome.Ok && !stale -> apply(result.value, initial = !phoneFirst)
                else -> _state.update { it.copy(loading = false) }
            }
        }
    }

    fun continueWithTelegram() = run(SignInView.Options) {
        val status = login.startQr()
        apply(status)
        val url = status.qrUrl
        if (url != null && status.step == STEP_QR) {
            _state.update { it.copy(awaitingTelegramApp = true) }
            effects.send(SignInEffect.OpenTelegramLogin(url))
            poll()
        }
    }

    /** The Telegram app could not be opened: phone number becomes the way in. */
    fun telegramAppMissing() = _state.update {
        it.copy(awaitingTelegramApp = false, view = SignInView.Phone, problem = SignInProblem.TelegramAppMissing)
    }

    fun showQr() {
        _state.update { it.copy(view = SignInView.Qr, problem = null) }
        run(SignInView.Qr) {
            apply(login.startQr())
            poll()
        }
    }

    fun usePhone() {
        stopPolling()
        _state.update { it.copy(view = SignInView.Phone, problem = null, awaitingTelegramApp = false) }
    }

    fun selectCountry(country: Country) = _state.update { it.copy(country = country, problem = null) }

    fun editNational(value: String) = _state.update { it.copy(national = PhoneNumbers.nationalDigits(value, it.country), problem = null) }

    fun submitPhone() {
        val current = _state.value
        if (!PhoneNumbers.isPlausible(current.country, current.national)) {
            _state.update { it.copy(problem = SignInProblem.PhoneInvalid) }
            return
        }
        run(SignInView.Phone) {
            val status = login.startPhone(PhoneNumbers.e164(current.country, current.national))
            apply(status)
            if (status.step == STEP_CODE && status.error == null) startResendCountdown()
        }
    }

    fun resendCode() {
        if (_state.value.resendSeconds > 0) return
        submitPhone()
    }

    fun changeNumber() = _state.update { it.copy(view = SignInView.Phone, problem = null) }

    fun submitCode(code: String) {
        val digits = code.filter(Char::isDigit)
        if (digits.length < (_state.value.codeLength ?: CODE_MIN) || _state.value.busy) return
        run(SignInView.Code) { apply(login.submitCode(digits)) }
    }

    fun submitPassword(password: String) {
        if (password.isEmpty() || _state.value.busy) return
        run(SignInView.Password) { apply(login.submitPassword(password)) }
    }

    fun clearProblem() = _state.update { if (it.problem == SignInProblem.FloodWait) it else it.copy(problem = null) }

    /** Back inside the sign-in steps; returns false when the caller should leave the screen. */
    fun back(): Boolean {
        val view = _state.value.view
        stopPolling()
        _state.update {
            it.copy(
                view = when (view) {
                    SignInView.Code -> SignInView.Phone
                    else -> SignInView.Options
                },
                awaitingTelegramApp = false,
                problem = null
            )
        }
        return view != SignInView.Options
    }

    /** Coming back to Bento from Telegram: check right away instead of waiting for the next poll. */
    fun onResume() {
        if (!_state.value.awaitingTelegramApp && _state.value.view != SignInView.Qr) return
        viewModelScope.launch { (attempt { login.status() } as? Outcome.Ok)?.let { apply(it.value) } }
    }

    private fun run(view: SignInView, action: suspend () -> Unit) {
        lastAction = action
        floodJob?.cancel()
        _state.update { it.copy(busy = true, problem = null, floodWaitSeconds = null) }
        viewModelScope.launch {
            val result = attempt { action() }
            _state.update { it.copy(busy = false) }
            if (result is Outcome.Err) fail(result.problem, view)
        }
    }

    private fun apply(status: AccountStatusResponse, initial: Boolean = false) {
        val account = status.account
        if (status.step == STEP_AUTHORIZED && account != null) {
            stopPolling()
            _state.update { it.copy(loading = false, status = status, authorized = account, awaitingTelegramApp = false) }
            return
        }
        _state.update { current ->
            val keepQr = status.step == STEP_QR && status.qr == null && current.status?.qr != null
            val merged = if (keepQr) status.copy(qr = current.status?.qr, qrExpiresAt = current.status?.qrExpiresAt) else status
            current.copy(
                loading = false,
                status = merged,
                view = when (status.step) {
                    STEP_CODE -> SignInView.Code
                    STEP_PASSWORD -> SignInView.Password
                    else -> if (initial) SignInView.Options else current.view
                }
            )
        }
        status.error?.let { fail(ApiProblem.fromBody(it.code, it.details), _state.value.view) }
    }

    private fun fail(problem: ApiProblem, view: SignInView) {
        val mapped = problemOf(problem)
        _state.update {
            it.copy(
                problem = mapped,
                busy = false,
                awaitingTelegramApp =
                    it.awaitingTelegramApp && mapped != SignInProblem.Expired
            )
        }
        if (mapped == SignInProblem.FloodWait) startFloodWait(problem.retryAfterSeconds ?: DEFAULT_FLOOD_SECONDS, view)
    }

    private fun startFloodWait(seconds: Long, view: SignInView) {
        floodJob?.cancel()
        floodJob = viewModelScope.launch {
            var left = seconds
            while (left > 0 && isActive) {
                _state.update { it.copy(floodWaitSeconds = left) }
                delay(TICK_MS)
                left--
            }
            _state.update { it.copy(floodWaitSeconds = null, problem = null) }
            // "Lo intentaremos solo": repeat the step that Telegram slowed down.
            lastAction?.let { action -> if (_state.value.view == view) run(view, action) }
        }
    }

    private fun startResendCountdown() {
        resendJob?.cancel()
        resendJob = viewModelScope.launch {
            var left = RESEND_SECONDS
            while (left > 0 && isActive) {
                _state.update { it.copy(resendSeconds = left) }
                delay(TICK_MS)
                left--
            }
            _state.update { it.copy(resendSeconds = 0) }
        }
    }

    private fun poll() {
        if (polling?.isActive == true) return
        polling = viewModelScope.launch {
            var keepGoing = true
            while (isActive && keepGoing) {
                delay(POLL_MS)
                keepGoing = pollOnce()
            }
        }
    }

    /** One check of a pending token login; false once it is over (authorized, password needed, or abandoned). */
    private suspend fun pollOnce(): Boolean {
        val pending = _state.value
        if (!pending.awaitingTelegramApp && pending.view != SignInView.Qr) return false
        val status = (attempt { login.status() } as? Outcome.Ok)?.value ?: return true // transient; retry next tick
        if (status.step == STEP_AUTHORIZED || status.step == STEP_PASSWORD) {
            apply(status)
            if (status.step == STEP_PASSWORD) _state.update { it.copy(awaitingTelegramApp = false) }
            return false
        }
        // Login tokens last ~30 s: refresh shortly before expiry (or when Telegram reports it expired).
        if (status.step != STEP_QR || expiresSoon(status)) {
            (attempt { login.startQr() } as? Outcome.Ok)?.let { apply(it.value) }
        } else {
            apply(status)
        }
        return true
    }

    private fun expiresSoon(status: AccountStatusResponse): Boolean {
        val expires =
            status.qrExpiresAt?.let { runCatching { java.time.OffsetDateTime.parse(it).toInstant().toEpochMilli() }.getOrNull() }
                ?: return false
        return expires - System.currentTimeMillis() < REFRESH_BEFORE_MS
    }

    private fun stopPolling() {
        polling?.cancel()
        polling = null
    }

    companion object {
        const val STEP_AUTHORIZED = "authorized"
        const val STEP_QR = "qr_pending"
        const val STEP_CODE = "code_required"
        const val STEP_PASSWORD = "password_required"
        const val POLL_MS = 1_500L
        const val TICK_MS = 1_000L
        const val RESEND_SECONDS = 60
        const val CODE_LENGTH = 5
        val CODE_LENGTH_RANGE = 3..12
        private const val CODE_MIN = 5
        private const val REFRESH_BEFORE_MS = 3_000L
        private const val DEFAULT_FLOOD_SECONDS = 60L

        fun problemOf(problem: ApiProblem): SignInProblem = when (problem.code) {
            "telegram_code_invalid" -> SignInProblem.CodeInvalid
            "telegram_login_expired" -> SignInProblem.Expired
            "telegram_password_invalid" -> SignInProblem.PasswordInvalid
            "telegram_phone_invalid" -> SignInProblem.PhoneInvalid
            "telegram_flood_wait" -> SignInProblem.FloodWait
            "telegram_not_available" -> SignInProblem.NotAvailable
            "telegram_network", ApiProblem.NETWORK, ApiProblem.ENGINE -> SignInProblem.Network
            else -> SignInProblem.Generic
        }
    }
}
