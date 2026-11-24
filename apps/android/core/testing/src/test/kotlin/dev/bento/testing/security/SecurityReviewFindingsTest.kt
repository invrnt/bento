package dev.bento.testing.security

import dev.bento.engine.BentoEngine
import dev.bento.engine.EngineHolder
import dev.bento.engine.EngineState
import dev.bento.testing.FakeEngineRuntime
import dev.bento.testing.FakeKeyWrapping
import dev.bento.testing.FakeProcessKeeper
import dev.bento.testing.testEngineConfig
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertNotEquals
import org.junit.Test

/**
 * Stage 22 security review (orchestration/execution/android-security-review.md).
 * These tests are EXPECTED TO FAIL until the finding they name is fixed; delete this note when green.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class SecurityReviewFindingsTest {
    private fun kotlinx.coroutines.test.TestScope.engine(runtime: FakeEngineRuntime): BentoEngine {
        val counter = AtomicInteger()
        val dispatcher = StandardTestDispatcher(testScheduler)
        return BentoEngine(
            runtime = runtime,
            config = { testEngineConfig },
            wrappingKey = FakeKeyWrapping()::deviceWrappingKey,
            processKeeper = FakeProcessKeeper(),
            scope = backgroundScope,
            engineDispatcher = dispatcher,
            blockingDispatcher = dispatcher,
            clock = { testScheduler.currentTime },
            tokenFactory = { "sec-review-token-${counter.incrementAndGet()}-0123456789abcdef" }
        )
    }

    /** SEC-01: a token sent to a squatted (freed) port must be useless for the next API start. */
    @Test
    fun `SEC-01 the API token rotates when the engine restarts`() = runTest {
        val runtime = FakeEngineRuntime()
        val engine = engine(runtime)
        val first = engine.acquire(EngineHolder.Ui)
        runCurrent()
        val before = engine.state.value as EngineState.Ready
        first.close()
        runCurrent()
        advanceTimeBy(BentoEngine.IDLE_STOP_MS + 1)
        runCurrent()
        engine.acquire(EngineHolder.Ui)
        runCurrent()
        val after = engine.state.value as EngineState.Ready
        assertNotEquals("port changed but the bearer token is reused", before.token, after.token)
    }

    /** SEC-01: the stall path restarts the API on a new port; the old token must not stay valid. */
    @Test
    fun `SEC-01 the API token rotates when a stalled API is restarted on a new port`() = runTest {
        val runtime = FakeEngineRuntime()
        val engine = engine(runtime)
        engine.acquire(EngineHolder.Ui)
        runCurrent()
        val before = engine.state.value as EngineState.Ready
        runtime.apiPort = null // the API thread died; its port is free for any app to bind
        engine.reportStall()
        runCurrent()
        val after = engine.state.value as EngineState.Ready
        assertNotEquals(before.port, after.port)
        assertNotEquals("API restarted on a new port with the same bearer token", before.token, after.token)
    }
}
