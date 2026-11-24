package dev.bento.testing

import dev.bento.engine.EngineConfig
import dev.bento.engine.EngineRuntime
import dev.bento.engine.EngineStatus
import dev.bento.engine.MigrationResult
import dev.bento.engine.WorkerMode
import dev.bento.engine.WorkerRunResult
import java.util.concurrent.CopyOnWriteArrayList

/** Fake interpreter for engine lifecycle tests: records every call; can fail the next N starts. */
class FakeEngineRuntime(
    var nextPort: Int = 41_000,
    var failStarts: Int = 0
) : EngineRuntime {
    val calls = CopyOnWriteArrayList<String>()
    val events = CopyOnWriteArrayList<Pair<String, String>>()
    var configuredWith: EngineConfig? = null
        private set
    var configuredToken: String? = null
        private set
    var configuredKeySize: Int = 0
        private set
    var apiPort: Int? = null
    var workerMode: WorkerMode? = null
        private set
    var runResult = WorkerRunResult(ran = 0, remaining = 0, nextEligibleAtEpochMs = null, stoppedReason = WorkerRunResult.StopReason.IDLE)

    override fun warmUp() {
        calls += "warmUp"
    }

    override fun configure(config: EngineConfig, wrappingKey: ByteArray, apiToken: String) {
        calls += "configure"
        configuredWith = config
        configuredToken = apiToken
        configuredKeySize = wrappingKey.size
    }

    override fun migrate(): MigrationResult {
        calls += "migrate"
        if (failStarts > 0) {
            failStarts -= 1
            throw IllegalStateException("migration failed (fake)")
        }
        return MigrationResult(from = "0006", to = "0006", ran = false, ms = 1)
    }

    override fun startWorker(mode: WorkerMode) {
        calls += "startWorker:${mode.wire}"
        workerMode = mode
    }

    override fun startApi(): Int {
        calls += "startApi"
        val port = nextPort++
        apiPort = port
        return port
    }

    override fun runWorkerUntil(deadlineEpochMs: Long, kinds: List<String>?): WorkerRunResult {
        calls += "runWorkerUntil"
        return runResult
    }

    override fun stop(timeoutMs: Long) {
        calls += "stop"
        apiPort = null
        workerMode = null
    }

    override fun onEvent(kind: String, payloadJson: String) {
        events += kind to payloadJson
    }

    override fun status(): EngineStatus = EngineStatus(apiPort, workerMode?.wire ?: "stopped", "disconnected", null)

    fun count(call: String): Int = calls.count { it == call }
}
