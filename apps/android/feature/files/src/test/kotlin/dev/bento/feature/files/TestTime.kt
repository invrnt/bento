package dev.bento.feature.files

/** Runs pending work including `backgroundScope` (which `advanceUntilIdle` skips) up to a minute of virtual time. */
internal fun kotlinx.coroutines.test.TestScope.settle(ms: Long = 60_000) {
    testScheduler.advanceTimeBy(ms)
    testScheduler.runCurrent()
}

/** Waits (real time) for IO-dispatched work, settling virtual time in between. */
internal fun kotlinx.coroutines.test.TestScope.awaitUntil(timeoutMs: Long = 5_000, condition: () -> Boolean) {
    val end = System.currentTimeMillis() + timeoutMs
    while (System.currentTimeMillis() < end) {
        settle()
        if (condition()) return
        Thread.sleep(20)
    }
    settle()
}
