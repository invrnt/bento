package dev.bento.feature.activity

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import dev.bento.background.TransferScheduler
import dev.bento.data.ActivityRepository
import dev.bento.data.Invalidations
import dev.bento.data.SessionRepository
import dev.bento.engine.BentoEngine
import dev.bento.engine.EngineState
import dev.bento.engine.di.ApplicationScope
import dev.bento.feature.files.ImportFailure
import dev.bento.feature.files.ImportFailureLog
import dev.bento.feature.recovery.Outcome
import dev.bento.feature.recovery.attempt
import dev.bento.feature.settings.BackupRepository
import dev.bento.feature.settings.Clock
import dev.bento.feature.settings.LocalSettings
import dev.bento.feature.settings.StallDetector
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.channelFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.filterIsInstance
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * The global status every top bar shows (avatar ring) and Cuenta y actividad details. Refreshed when the engine becomes
 * ready, on every server event (jobs/sync stream through [Invalidations]) and on a slow tick while someone is looking;
 * stops when nobody collects it (no background polling).
 */
@Singleton
class ActivityStore @Inject constructor(
    private val activity: ActivityRepository,
    private val backup: BackupRepository,
    private val session: SessionRepository,
    private val engine: BentoEngine,
    private val invalidations: Invalidations,
    private val failures: ImportFailureLog,
    private val local: LocalSettings,
    private val clock: Clock,
    @ApplicationScope scope: CoroutineScope
) {
    private val snapshot = MutableStateFlow(ActivityOverview())
    private val refreshRequests = MutableStateFlow(0)

    @OptIn(FlowPreview::class)
    private val polling = channelFlow {
        launch { engine.state.filterIsInstance<EngineState.Ready>().collect { refreshRequests.update { it + 1 } } }
        launch { invalidations.topics.collect { refreshRequests.update { it + 1 } } }
        launch {
            while (true) {
                delay(TICK_MS)
                refreshRequests.update { it + 1 }
            }
        }
        refreshRequests.debounce(DEBOUNCE_MS).collect { send(load()) }
    }

    val overview: StateFlow<ActivityOverview> = combine(polling, engine.state, failures.entries) { loaded, state, imports ->
        loaded.copy(engine = state, importFailures = imports)
    }.stateIn(scope, SharingStarted.WhileSubscribed(STOP_MS), ActivityOverview())

    fun refresh() = refreshRequests.update { it + 1 }

    private suspend fun load(): ActivityOverview {
        val previous = snapshot.value
        val dto = (attempt { activity.activity() } as? Outcome.Ok)?.value?.let(ActivityDto::parse)
        val status = (attempt { backup.status() } as? Outcome.Ok)?.value
        val policy = (attempt { backup.policy() } as? Outcome.Ok)?.value
        val sources = (attempt { backup.sources() } as? Outcome.Ok)?.value
        val account = if (previous.accountName == null ||
            previous.devices == null
        ) {
            (attempt { session.account() } as? Outcome.Ok)?.value
        } else {
            null
        }
        val vault = (attempt { session.vault() } as? Outcome.Ok)?.value
        val next = previous.copy(
            loaded = dto != null || previous.loaded,
            activity = dto ?: previous.activity,
            backup = status ?: previous.backup,
            policy = policy ?: previous.policy,
            backupOn = sources?.any { it.kind == BackupRepository.MEDIA_STORE && it.enabled } ?: previous.backupOn,
            accountName = account?.account?.displayName ?: previous.accountName,
            usageBytes = vault?.usage?.bytes ?: previous.usageBytes,
            devices = vault?.devicesCount?.toInt() ?: previous.devices
        )
        val stored = local.prefs.first()
        val prefs = StallDetector.track(stored, next.backup?.pending ?: 0, clock.now())
        if (prefs != stored) local.update { prefs }
        val result = next.copy(stalled = StallDetector.stalled(next.backup, next.policy, next.backupOn, prefs, clock.now()))
        snapshot.value = result
        return result
    }

    /** Pausing stops the running transfer too; resuming continues in the background (or now, while visible). */
    suspend fun setPaused(context: Context, paused: Boolean): Boolean {
        if (paused) TransferScheduler.stop(context)
        val ok = attempt { backup.setPaused(paused) } is Outcome.Ok
        if (ok && !paused && (snapshot.value.backup?.pending ?: 0) > 0) TransferScheduler.start(context)
        refresh()
        return ok
    }

    suspend fun retryJob(jobId: String): Boolean = (attempt { activity.retryJob(jobId) } is Outcome.Ok).also { refresh() }

    suspend fun retrySync(): Boolean = (attempt { activity.syncNow() } is Outcome.Ok).also { refresh() }

    fun dismiss(failure: ImportFailure) = failures.dismiss(failure)

    suspend fun dismissStall() {
        local.update { it.copy(stallDismissedAt = clock.now()) }
        refresh()
    }

    private companion object {
        const val TICK_MS = 15_000L
        const val DEBOUNCE_MS = 300L
        const val STOP_MS = 5_000L
    }
}

/** Avatar, sheet and Activity screen state; actions delegate to [ActivityStore]. */
@HiltViewModel
class ActivityViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val store: ActivityStore
) : ViewModel() {
    val overview: StateFlow<ActivityOverview> = store.overview

    private val _busy = MutableStateFlow(false)
    val busy: StateFlow<Boolean> = _busy.asStateFlow()

    fun refresh() = store.refresh()

    fun setPaused(paused: Boolean) = run { store.setPaused(context, paused) }

    fun retry(jobId: String) = run { store.retryJob(jobId) }

    fun retrySync() = run { store.retrySync() }

    fun dismiss(failure: ImportFailure) = store.dismiss(failure)

    fun dismissStall() = run {
        store.dismissStall()
        true
    }

    private fun run(block: suspend () -> Boolean) {
        viewModelScope.launch {
            _busy.value = true
            block()
            _busy.value = false
        }
    }
}
