package dev.bento.feature.onboarding

import androidx.compose.ui.graphics.ImageBitmap
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dev.bento.api.generated.TelegramAccountResponse
import dev.bento.api.generated.VaultStatusResponse
import dev.bento.designsystem.component.QrMatrix
import dev.bento.feature.recovery.Outcome
import dev.bento.feature.recovery.VaultRepository
import dev.bento.feature.recovery.attempt
import dev.bento.feature.recovery.toMatrix
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
import kotlinx.coroutines.launch

/** First-run steps of product/android.md §4.1 (the backup step itself belongs to feature/settings). */
enum class OnboardingStep { Welcome, Reconnect, SignIn, Checking, Creating, Notifications, Kit, Done }

/** One row of "Creando tu nube". */
enum class CreationRow { Channels, Keys, Device }

enum class RowState { Pending, Running, Done, Failed }

/**
 * Progress of `POST /vault` from `GET /vault` `creation.steps` (api/android-endpoints.md §11): the three channels
 * (`files`, `sync`, `inbox`), the signed header with the keys (`header`), and this phone (`device`). Empty until the
 * backend reports steps; rows then follow [done] only.
 */
data class CreatingState(
    val failed: Boolean = false,
    val slow: Boolean = false,
    val done: Boolean = false,
    val steps: Map<String, String> = emptyMap()
) {
    fun row(row: CreationRow): RowState {
        if (done) return RowState.Done
        if (steps.isEmpty()) return if (failed) RowState.Failed else RowState.Running
        val states = CREATION_STEPS.getValue(row).map { steps[it] ?: "pending" }
        return when {
            "failed" in states -> RowState.Failed
            states.all { it == "done" } -> RowState.Done
            states.any { it == "running" || it == "done" } -> RowState.Running
            failed -> RowState.Failed
            else -> RowState.Pending
        }
    }

    /** Channels created so far, of three. */
    val channelsDone: Int get() = CREATION_STEPS.getValue(CreationRow.Channels).count { steps[it] == "done" }

    companion object {
        val CREATION_STEPS: Map<CreationRow, List<String>> = mapOf(
            CreationRow.Channels to listOf("files", "sync", "inbox"),
            CreationRow.Keys to listOf("header"),
            CreationRow.Device to listOf("device")
        )
    }
}

/** The fresh recovery code stays here, in memory only, until the kit step is done. */
data class PendingKit(val code: String, val qr: QrMatrix?, val createdAt: String?)

data class OnboardingState(
    val step: OnboardingStep = OnboardingStep.Welcome,
    val account: TelegramAccountResponse? = null,
    val avatar: ImageBitmap? = null,
    val creating: CreatingState = CreatingState(),
    val kit: PendingKit? = null,
    val localSheet: Boolean = false
)

sealed interface OnboardingEffect {
    /** The account already has a cloud: continue with the join choice (pair, ask, recovery code). */
    data object ExistingVault : OnboardingEffect

    /** Hand off to the phone-backup setup (feature/settings, `Route.BackupSetup`). */
    data object OpenBackupSetup : OnboardingEffect

    /** Setup is over (Listo, local mode, or a reconnect that found the cloud ready). */
    data object Finished : OnboardingEffect

    /** Signed in again only to learn another device removed this phone: explain it and offer to join again. */
    data object RemovedWhileAway : OnboardingEffect
}

@HiltViewModel
class OnboardingViewModel @Inject constructor(
    private val vault: VaultRepository,
    private val login: LoginRepository,
    private val gate: AppGateResolver
) : ViewModel() {
    private val _state = MutableStateFlow(OnboardingState())
    val state: StateFlow<OnboardingState> = _state.asStateFlow()
    private val effects = Channel<OnboardingEffect>(Channel.BUFFERED)
    val effect: Flow<OnboardingEffect> = effects.receiveAsFlow()
    private var creatingJob: Job? = null
    private var initialized = false

    fun begin(reconnect: Boolean) {
        if (initialized) return
        initialized = true
        if (reconnect) _state.update { it.copy(step = OnboardingStep.Reconnect) }
    }

    fun start() = go(OnboardingStep.SignIn)

    fun showLocalSheet(show: Boolean) = _state.update { it.copy(localSheet = show) }

    fun confirmLocalMode() {
        gate.chooseLocalMode()
        _state.update { it.copy(localSheet = false) }
        effects.trySend(OnboardingEffect.Finished)
    }

    /** Back from sign-in returns to the welcome (or reconnect) screen. */
    fun backToStart(reconnect: Boolean) = go(if (reconnect) OnboardingStep.Reconnect else OnboardingStep.Welcome)

    fun authorized(account: TelegramAccountResponse) {
        _state.update { it.copy(account = account, step = OnboardingStep.Creating) }
        viewModelScope.launch { login.avatar()?.let { image -> _state.update { it.copy(avatar = image) } } }
        create()
    }

    /** Creating a vault is not idempotent: one attempt at a time, retried only by the person. */
    fun create() {
        if (creatingJob?.isActive == true) return
        _state.update { it.copy(creating = CreatingState()) }
        creatingJob = viewModelScope.launch {
            val slow = launch {
                delay(SLOW_AFTER_MS)
                _state.update { it.copy(creating = it.creating.copy(slow = true)) }
            }
            val current = settledStatus()
            if (current?.reason == "device_removed") {
                slow.cancel()
                effects.send(OnboardingEffect.RemovedWhileAway)
                return@launch
            }
            when (current?.state) {
                "locked" -> {
                    slow.cancel()
                    effects.send(OnboardingEffect.ExistingVault)
                    return@launch
                }

                "ready", "bootstrapping" -> {
                    slow.cancel()
                    _state.update { it.copy(creating = CreatingState(done = true)) }
                    toBackup()
                    return@launch
                }
            }
            // `POST /vault` blocks until it is over; `GET /vault` reports its steps meanwhile.
            val progress = launch {
                while (true) {
                    delay(PROGRESS_POLL_MS)
                    val steps = (attempt { vault.status() } as? Outcome.Ok)?.value?.creation?.steps ?: continue
                    _state.update { it.copy(creating = it.creating.copy(steps = steps.associate { s -> s.step to s.state })) }
                }
            }
            val created = attempt { vault.create() }
            progress.cancel()
            when (created) {
                is Outcome.Ok -> {
                    val value = created.value
                    _state.update {
                        it.copy(
                            creating = it.creating.copy(done = true, slow = false),
                            kit = PendingKit(value.recoveryCode, value.recoveryQr.toMatrix(), value.vault.createdAt)
                        )
                    }
                    delay(DONE_PAUSE_MS)
                    toBackup()
                }

                is Outcome.Err -> if (created.problem.code == "vault_already_exists") {
                    effects.send(OnboardingEffect.ExistingVault)
                } else {
                    _state.update { it.copy(creating = it.creating.copy(failed = true, slow = false)) }
                }
            }
            slow.cancel()
        }
    }

    private suspend fun toBackup() {
        // The backup screen returns here; the next step is already set so back/return both continue.
        _state.update { it.copy(step = OnboardingStep.Notifications) }
        effects.send(OnboardingEffect.OpenBackupSetup)
    }

    /** After the notification step (granted, denied or skipped). */
    fun notificationsDone() = go(if (_state.value.kit != null) OnboardingStep.Kit else OnboardingStep.Done)

    /** Kit confirmed or `Más tarde`: forget the code. */
    fun kitDone() = _state.update { it.copy(kit = null, step = OnboardingStep.Done) }

    fun finish() {
        gate.finishedSetup()
        effects.trySend(OnboardingEffect.Finished)
    }

    /**
     * Reconnect: signed in again; the cloud decides where to go. After a lost session `/vault` says `bootstrapping`
     * until one sync pull ran, so a removal posted meanwhile is found before the library opens (§11 Removed devices).
     */
    fun reconnected() {
        go(OnboardingStep.Checking)
        viewModelScope.launch {
            val status = settledStatus()
            when {
                status?.reason == "device_removed" -> effects.send(OnboardingEffect.RemovedWhileAway)
                status?.state == "locked" -> effects.send(OnboardingEffect.ExistingVault)
                status?.state == "no_vault" -> go(OnboardingStep.Creating).also { create() }
                else -> finish()
            }
        }
    }

    private fun go(step: OnboardingStep) = _state.update { it.copy(step = step) }

    /** `/vault`, waiting (up to [SETTLE_MS]) while it is `bootstrapping`; null when it cannot be read. */
    private suspend fun settledStatus(): VaultStatusResponse? {
        var waited = 0L
        while (true) {
            val status = (attempt { vault.status() } as? Outcome.Ok)?.value ?: return null
            if (status.state != "bootstrapping" || waited >= SETTLE_MS) return status
            delay(SETTLE_POLL_MS)
            waited += SETTLE_POLL_MS
        }
    }

    private companion object {
        const val SLOW_AFTER_MS = 10_000L
        const val PROGRESS_POLL_MS = 400L
        const val SETTLE_POLL_MS = 1_000L
        const val SETTLE_MS = 30_000L
        const val DONE_PAUSE_MS = 600L
    }
}
