package dev.bento.engine

/** Engine state observed by the UI and background layers (architecture/android-runtime.md §3). */
sealed interface EngineState {
    /** No holder; the interpreter may still be loaded. */
    data object Stopped : EngineState

    /** Interpreter warm-up, configure, migrations, worker and API start. */
    data object Starting : EngineState

    /** API answering on `127.0.0.1:[port]`; every request needs `Authorization: Bearer [token]`. */
    data class Ready(val port: Int, val token: String, val mode: WorkerMode) : EngineState {
        val baseUrl: String get() = "http://127.0.0.1:$port"

        override fun toString(): String = "Ready(port=$port, mode=$mode, token=<redacted>)"
    }

    /** Running with a problem, or failing to start; [attention] after 3 crashes in 5 minutes. */
    data class Degraded(val reason: DegradedReason, val attention: Boolean = false) : EngineState
}

enum class DegradedReason {
    /** `start()` failed; a retry is scheduled with backoff (1, 5, 30 s). */
    START_FAILED,

    /** A loopback call stalled or the API stopped answering; the API is being restarted. */
    STALLED,

    /** Three start failures within five minutes; surfaced as an attention item. */
    CRASH_LOOP,
}

enum class WorkerMode(val wire: String) {
    /** Normal job loop with Telethon update handlers (a `ui` holder is active). */
    FULL("full"),

    /** No update handlers; background runs drive it with `run_worker_until`. */
    DRAIN("drain"),
}

/** Reference-counted reasons to keep the engine running (architecture/android-runtime.md §3). */
sealed interface EngineHolder {
    val key: String

    /** `MainActivity`/`ShareActivity` started. */
    data object Ui : EngineHolder {
        override val key = "ui"
    }

    /** A WorkManager worker or UIDT job named [name] is running. */
    data class Work(val name: String) : EngineHolder {
        override val key = "work:$name"
    }

    /** An active user-initiated transfer. */
    data object Transfer : EngineHolder {
        override val key = "transfer"
    }
}

/** Released exactly once with [close]; obtained from [BentoEngine.acquire]. */
interface EngineLease : AutoCloseable {
    val holder: EngineHolder

    override fun close()
}

/** `run_worker_until` result; Kotlin re-enqueues background work from it. */
data class WorkerRunResult(
    val ran: Int,
    val remaining: Int,
    val nextEligibleAtEpochMs: Long?,
    val stoppedReason: StopReason,
) {
    enum class StopReason { IDLE, DEADLINE, CONDITIONS, ERROR }
}

/** `migrate()` result. */
data class MigrationResult(val from: String?, val to: String?, val ran: Boolean, val ms: Long)

/** `status()` result (no secrets). */
data class EngineStatus(val apiPort: Int?, val worker: String, val telegram: String, val lastError: String?)
