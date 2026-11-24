package dev.bento.background

import dev.bento.engine.WorkerRunResult

/** What a background run does next with a `run_worker_until` result (pure; JVM tested). */
sealed interface NextRun {
    /** Nothing eligible left; the trigger/periodic constraints bring the next run. */
    data object Done : NextRun

    /** Enqueue again after [delayMs] (0 = immediately, more work is eligible now). */
    data class Again(val delayMs: Long) : NextRun

    /** The run failed; let WorkManager retry with its backoff. */
    data object Retry : NextRun
}

object RunPlanner {
    const val MIN_DELAY_MS = 15_000L
    const val MAX_DELAY_MS = 6 * 60 * 60_000L

    fun next(result: WorkerRunResult, nowEpochMs: Long): NextRun = when (result.stoppedReason) {
        WorkerRunResult.StopReason.ERROR -> NextRun.Retry
        WorkerRunResult.StopReason.DEADLINE -> if (result.remaining > 0) NextRun.Again(0) else NextRun.Done
        WorkerRunResult.StopReason.CONDITIONS -> NextRun.Done
        WorkerRunResult.StopReason.IDLE -> {
            val next = result.nextEligibleAtEpochMs
            if (result.remaining > 0 && next != null) {
                NextRun.Again((next - nowEpochMs).coerceIn(MIN_DELAY_MS, MAX_DELAY_MS))
            } else {
                NextRun.Done
            }
        }
    }

    /** User-initiated transfers keep going while work remains and progress is possible. */
    fun continueTransfer(result: WorkerRunResult): Boolean =
        result.remaining > 0 && result.stoppedReason == WorkerRunResult.StopReason.DEADLINE
}
