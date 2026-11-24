package dev.bento.engine

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
    tokenFactory: () -> String = ApiTokens::generate,
    private val listeners: Set<EngineLifecycleListener> = emptySet(),
    private val log: EngineLog = EngineLog.None,
    private val idleStopMs: Long = IDLE_STOP_MS,
    private val backoffMs: List<Long> = BACKOFF_MS
) {
    private val _state = MutableStateFlow<EngineState>(EngineState.Stopped)

    /** Observed by repositories (network calls suspend on [EngineState.Ready]) and background workers. */
    val state: StateFlow<EngineState> = _state.asStateFlow()

    /** Per-process API token: 32 random bytes, base64url, passed to Python in memory only. */
    private val apiToken: String by lazy(tokenFactory)

    private val holders = LinkedHashMap<String, Pair<EngineHolder, Int>>()
    private var configured = false
    private var running = false
    private var runningMode: WorkerMode? = null
    private var idleStop: Job? = null
    private var retry: Job? = null
    private val failures = ArrayDeque<Long>()
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
     * A loopback call stalled or failed at the transport level. Checks the API and restarts it on a new
     * port if it is gone; the UI client treats the stall as [EngineState.Degraded] meanwhile.
     */
    fun reportStall() {
        scope.launch(engineDispatcher) {
            val ready = _state.value as? EngineState.Ready ?: return@launch
            _state.value = EngineState.Degraded(DegradedReason.STALLED)
            val status = runCatching { runtime.status() }.getOrNull()
            val port = if (status?.apiPort == null) runCatching { runtime.startApi() }.getOrNull() else status.apiPort
            _state.value = if (port != null) ready.copy(port = port) else EngineState.Degraded(DegradedReason.STALLED)
        }
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
                _state.value = EngineState.Stopped
                processKeeper.release()
            }
            return
        }
        idleStop?.cancel()
        idleStop = null
        when {
            !running && retry?.isActive != true -> startNow(desired)
            running && runningMode == WorkerMode.DRAIN && desired == WorkerMode.FULL -> switchMode(desired)
        }
    }

    private fun startNow(mode: WorkerMode) {
        _state.value = EngineState.Starting
        processKeeper.keepAlive()
        try {
            runtime.warmUp()
            if (!configured) {
                Redaction.register(apiToken)
                val key = wrappingKey()
                try {
                    runtime.configure(config(), key, apiToken)
                } finally {
                    key.fill(0)
                }
                configured = true
            }
            val migration = runtime.migrate()
            log.info("migrations ran=${migration.ran} to=${migration.to} in ${migration.ms} ms")
            runtime.startWorker(mode)
            val port = runtime.startApi()
            running = true
            runningMode = mode
            _state.value = EngineState.Ready(port, apiToken, mode)
            listeners.forEach { listener -> runCatching { listener.onEngineRunning() } }
        } catch (error: Throwable) {
            log.error("engine start failed", error)
            runCatching { runtime.stop(STOP_TIMEOUT_MS) }
            running = false
            runningMode = null
            onStartFailure()
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

    private fun switchMode(mode: WorkerMode) {
        runCatching { runtime.startWorker(mode) }
            .onSuccess {
                runningMode = mode
                (_state.value as? EngineState.Ready)?.let { _state.value = it.copy(mode = mode) }
            }
            .onFailure { log.error("worker mode switch failed", it) }
    }

    private fun stopNow() {
        listeners.forEach { listener -> runCatching { listener.onEngineStopping() } }
        runCatching { runtime.stop(STOP_TIMEOUT_MS) }.onFailure { log.warn("engine stop failed", it) }
        running = false
        runningMode = null
        _state.value = EngineState.Stopped
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
