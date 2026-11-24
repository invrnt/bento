package dev.bento.engine

import dev.bento.engine.bridge.DeviceKeyLostException
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.filterIsInstance
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout

/**
 * Application-scoped owner of the embedded backend (architecture/android-runtime.md §3).
 *
 * Holders are reference counted. The first holder starts the engine (`configure` → `migrate` → worker → API →
 * [EngineState.Ready]); a `ui` holder runs the worker in [WorkerMode.FULL], background holders in
 * [WorkerMode.DRAIN]. When the last holder is released the engine waits [idleStopMs], then stops; the
 * interpreter stays loaded. While any holder is active, [processKeeper] keeps the process out of the cached
 * (frozen) state — spike finding §4.1: an unheld engine process is frozen mid-request.
 *
 * All state transitions run on [engineDispatcher] (one thread), so the class needs no locks beyond the
 * holder table.
 */
class BentoEngine(
    private val runtime: EngineRuntime,
    private val config: () -> EngineConfig,
    private val wrappingKey: () -> ByteArray,
    private val processKeeper: ProcessKeeper,
    private val scope: CoroutineScope,
    private val engineDispatcher: CoroutineDispatcher,
    private val blockingDispatcher: CoroutineDispatcher = Dispatchers.IO,
    private val clock: () -> Long = System::currentTimeMillis,
    private val tokenFactory: () -> String = ApiTokens::generate,
    private val listeners: Set<EngineLifecycleListener> = emptySet(),
    private val log: EngineLog = EngineLog.None,
    private val idleStopMs: Long = IDLE_STOP_MS,
    private val backoffMs: List<Long> = BACKOFF_MS
) {
    private val _state = MutableStateFlow<EngineState>(EngineState.Stopped)

    /** Observed by repositories (network calls suspend on [EngineState.Ready]) and background workers. */
    val state: StateFlow<EngineState> = _state.asStateFlow()

    private val holders = LinkedHashMap<String, Pair<EngineHolder, Int>>()
    private var configured = false
    private var running = false
    private var runningMode: WorkerMode? = null
    private var idleStop: Job? = null
    private var retry: Job? = null
    private val failures = ArrayDeque<Long>()
    private var keyLost = false
    private val warmUpStarted = AtomicBoolean(false)

    /** `Application.onCreate`: start the interpreter and warm-up imports in the background; never blocks. */
    fun warmUp() {
        if (!warmUpStarted.compareAndSet(false, true)) return
        scope.launch(engineDispatcher) {
            runCatching { runtime.warmUp() }.onFailure { log.error("warm-up failed", it) }
        }
    }

    /** Acquire [holder]; the engine starts (or switches to full mode) if needed. Close the lease to release. */
    fun acquire(holder: EngineHolder): EngineLease {
        synchronized(holders) {
            val (_, count) = holders[holder.key] ?: (holder to 0)
            holders[holder.key] = holder to count + 1
        }
        reconcile()
        return Lease(holder)
    }

    /** Run [block] while holding [holder], with the engine ready. */
    suspend fun <T> withHolder(holder: EngineHolder, timeoutMs: Long = READY_TIMEOUT_MS, block: suspend (EngineState.Ready) -> T): T =
        acquire(holder).use { block(awaitReady(timeoutMs)) }

    /** Suspends until [EngineState.Ready]; throws [EngineUnavailableException] after [timeoutMs]. */
    suspend fun awaitReady(timeoutMs: Long = READY_TIMEOUT_MS): EngineState.Ready = try {
        withTimeout(timeoutMs) { state.filterIsInstance<EngineState.Ready>().first() }
    } catch (timeout: kotlinx.coroutines.TimeoutCancellationException) {
        throw EngineUnavailableException(state.value, timeout)
    }

    /**
     * Background run (architecture/android-runtime.md §6): drain eligible jobs until [deadlineEpochMs].
     * The caller must hold a `work:` or `transfer` holder for the whole call.
     */
    suspend fun runWorkerUntil(deadlineEpochMs: Long, kinds: List<String>? = null): WorkerRunResult {
        check(activeHolders().isNotEmpty()) { "runWorkerUntil needs an active holder" }
        awaitReady()
        return withContext(blockingDispatcher) { runtime.runWorkerUntil(deadlineEpochMs, kinds) }
    }

    /** Kotlin → Python notification (`media_changed`, `conditions`, `access_changed`, `low_memory`). */
    fun onEvent(kind: String, payloadJson: String) {
        if (!running) return
        runCatching { runtime.onEvent(kind, payloadJson) }.onFailure { log.warn("on_event($kind) failed", it) }
    }

    /**
     * A loopback call stalled or failed at the transport level. The state leaves [EngineState.Ready] first, so no
     * request (and no token) goes to the port while it is checked. A live API keeps its port and credentials; a
     * dead one restarts on a new port with new credentials (SEC-01: the old token dies with its server).
     */
    fun reportStall() {
        scope.launch(engineDispatcher) {
            val ready = _state.value as? EngineState.Ready ?: return@launch
            _state.value = EngineState.Degraded(DegradedReason.STALLED)
            val status = runCatching { runtime.status() }.getOrNull()
            _state.value = if (status?.apiPort == ready.port) ready else restartApi(ready)
        }
    }

    /**
     * A response from [port] did not carry a valid `X-Bento-Proof`: something other than this API answered (another
     * app bound a port Bento freed). Stop using the port at once and restart the API with new credentials.
     */
    fun reportUnverifiedServer(port: Int) {
        val ready = _state.value as? EngineState.Ready ?: return
        if (ready.port != port) return
        _state.compareAndSet(ready, EngineState.Degraded(DegradedReason.STALLED))
        scope.launch(engineDispatcher) {
            if (_state.value != EngineState.Degraded(DegradedReason.STALLED) || !running) return@launch
            log.warn("loopback server identity not verified; restarting the API")
            _state.value = restartApi(ready)
        }
    }

    private fun restartApi(ready: EngineState.Ready): EngineState {
        val credentials = newCredentials()
        val port = runCatching { runtime.startApi(credentials) }.onFailure { log.warn("API restart failed", it) }.getOrNull()
            ?: return EngineState.Degraded(DegradedReason.STALLED)
        return EngineState.Ready(port, credentials.token, credentials.serverKey, ready.mode)
    }

    private fun newCredentials(): ApiCredentials {
        val credentials = ApiCredentials(tokenFactory(), tokenFactory())
        Redaction.register(credentials.token)
        Redaction.register(credentials.serverKey)
        return credentials
    }

    fun activeHolders(): Set<EngineHolder> = synchronized(holders) { holders.values.map { it.first }.toSet() }

    private fun release(holder: EngineHolder) {
        synchronized(holders) {
            val (_, count) = holders[holder.key] ?: return
            if (count <= 1) holders.remove(holder.key) else holders[holder.key] = holder to count - 1
        }
        reconcile()
    }

    private fun reconcile() {
        scope.launch(engineDispatcher) { reconcileNow() }
    }

    private fun desiredMode(): WorkerMode? {
        val active = activeHolders()
        return when {
            active.isEmpty() -> null
            EngineHolder.Ui in active -> WorkerMode.FULL
            else -> WorkerMode.DRAIN
        }
    }

    private suspend fun reconcileNow() {
        val desired = desiredMode()
        if (desired == null) {
            if (running && idleStop?.isActive != true) {
                idleStop = scope.launch(engineDispatcher) {
                    delay(idleStopMs)
                    if (desiredMode() == null) stopNow()
                }
            }
            retry?.cancel()
            if (!running && _state.value is EngineState.Degraded) {
                if (!keyLost) _state.value = EngineState.Stopped // a lost key stays visible until the reset
                processKeeper.release()
            }
            return
        }
        idleStop?.cancel()
        idleStop = null
        when {
            keyLost -> _state.value = EngineState.Degraded(DegradedReason.KEY_LOST, attention = true)
            !running && retry?.isActive != true -> startNow(desired)
            running && runningMode == WorkerMode.DRAIN && desired == WorkerMode.FULL -> switchMode(desired)
        }
    }

    private fun startNow(mode: WorkerMode) {
        _state.value = EngineState.Starting
        processKeeper.keepAlive()
        val startedNs = System.nanoTime()
        try {
            runtime.warmUp()
            if (!configured) {
                val key = wrappingKey()
                try {
                    runtime.configure(config(), key)
                } finally {
                    key.fill(0)
                }
                configured = true
            }
            val migration = runtime.migrate()
            log.info("migrations ran=${migration.ran} to=${migration.to} in ${migration.ms} ms")
            runtime.startWorker(mode)
            val credentials = newCredentials()
            val port = runtime.startApi(credentials)
            running = true
            runningMode = mode
            _state.value = EngineState.Ready(port, credentials.token, credentials.serverKey, mode)
            log.info("engine ready (${mode.wire}) in ${(System.nanoTime() - startedNs) / NANOS_PER_MS} ms")
            listeners.forEach { listener -> runCatching { listener.onEngineRunning() } }
        } catch (error: Throwable) {
            log.error("engine start failed", error)
            runCatching { runtime.stop(STOP_TIMEOUT_MS) }
            running = false
            runningMode = null
            if (generateSequence(error) { it.cause }.any { it is DeviceKeyLostException }) {
                keyLost = true // permanent: retrying would loop forever (SEC-11)
                _state.value = EngineState.Degraded(DegradedReason.KEY_LOST, attention = true)
            } else {
                onStartFailure()
            }
        }
    }

    private fun onStartFailure() {
        val now = clock()
        failures.addLast(now)
        while (failures.isNotEmpty() && now - failures.first() > CRASH_WINDOW_MS) failures.removeFirst()
        val crashLoop = failures.size >= CRASH_LOOP_COUNT
        _state.value = EngineState.Degraded(
            if (crashLoop) DegradedReason.CRASH_LOOP else DegradedReason.START_FAILED,
            attention = crashLoop
        )
        val wait = backoffMs[(failures.size - 1).coerceIn(0, backoffMs.lastIndex)]
        retry = scope.launch(engineDispatcher) {
            delay(wait)
            retry = null
            val desired = desiredMode()
            if (desired == null) {
                _state.value = EngineState.Stopped
                processKeeper.release()
            } else if (!running) {
                startNow(desired)
            }
        }
    }

    /**
     * After [DegradedReason.KEY_LOST]: [wipe] removes this phone's unreadable local state (wrapped key, catalog,
     * caches) while nothing is running, then [onDone] runs (the app restarts into onboarding: link again or recover).
     */
    fun resetAfterKeyLoss(wipe: () -> Unit, onDone: (Result<Unit>) -> Unit) {
        scope.launch(engineDispatcher) {
            if (!keyLost) return@launch onDone(Result.failure(IllegalStateException("the device key is not lost")))
            runCatching { runtime.stop(STOP_TIMEOUT_MS) }
            val result = runCatching(wipe)
            if (result.isSuccess) {
                keyLost = false
                failures.clear()
                _state.value = EngineState.Stopped
            }
            onDone(result)
            if (result.isSuccess) reconcileNow() // current holders start a fresh engine (new key, empty catalog)
        }
    }

    private fun switchMode(mode: WorkerMode) {
        runCatching { runtime.startWorker(mode) }
            .onSuccess {
                runningMode = mode
                (_state.value as? EngineState.Ready)?.let { _state.value = it.copy(mode = mode) }
            }
            .onFailure { log.error("worker mode switch failed", it) }
    }

    private fun stopNow() {
        // Leave Ready before the listener closes: no request may reach the port once another app could bind it.
        _state.value = EngineState.Stopped
        listeners.forEach { listener -> runCatching { listener.onEngineStopping() } }
        runCatching { runtime.stop(STOP_TIMEOUT_MS) }.onFailure { log.warn("engine stop failed", it) }
        running = false
        runningMode = null
        processKeeper.release()
    }

    private inner class Lease(override val holder: EngineHolder) : EngineLease {
        private val closed = AtomicBoolean(false)

        override fun close() {
            if (closed.compareAndSet(false, true)) release(holder)
        }
    }

    companion object {
        const val IDLE_STOP_MS = 60_000L
        const val READY_TIMEOUT_MS = 60_000L
        const val STOP_TIMEOUT_MS = 10_000L
        private const val NANOS_PER_MS = 1_000_000L
        const val CRASH_WINDOW_MS = 5 * 60_000L
        const val CRASH_LOOP_COUNT = 3
        val BACKOFF_MS = listOf(1_000L, 5_000L, 30_000L)
    }
}

/** Keeps the process un-frozen while the engine runs (Android: [EngineService]). */
interface ProcessKeeper {
    fun keepAlive()

    fun release()

    object None : ProcessKeeper {
        override fun keepAlive() = Unit

        override fun release() = Unit
    }
}

/** Hooks for components that live exactly as long as the running engine (observers, callbacks). */
interface EngineLifecycleListener {
    fun onEngineRunning()

    fun onEngineStopping()
}

class EngineUnavailableException(val state: EngineState, cause: Throwable? = null) :
    IllegalStateException("engine not ready: $state", cause)
