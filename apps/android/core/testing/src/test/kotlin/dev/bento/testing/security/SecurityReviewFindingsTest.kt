package dev.bento.testing.security

import dev.bento.engine.BentoEngine
import dev.bento.engine.EngineHolder
import dev.bento.engine.EngineState
import dev.bento.engine.Redaction
import dev.bento.testing.FakeEngineRuntime
import dev.bento.testing.FakeKeyWrapping
import dev.bento.testing.FakeProcessKeeper
import dev.bento.testing.testEngineConfig
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Stage 22 security review regressions (orchestration/execution/android-security-review.md), SEC-01: the API
 * token and server key rotate on every API start, and the engine leaves Ready before a port can be freed.
 * Client-side proof checks are in `core/api` (`BentoHttpTest`).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class SecurityReviewFindingsTest {
    private fun TestScope.engine(runtime: FakeEngineRuntime): BentoEngine {
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
        assertNotEquals(before.serverKey, after.serverKey)
        assertNotEquals(after.token, after.serverKey)
        assertEquals(after.token, runtime.apiCredentials.last().token)
        assertEquals("secrets are registered for log redaction", "x <redacted>", Redaction.redact("x ${after.serverKey}"))
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

    @Test
    fun `SEC-01 a stall with the API still alive keeps its port and credentials`() = runTest {
        val runtime = FakeEngineRuntime()
        val engine = engine(runtime)
        engine.acquire(EngineHolder.Ui)
        runCurrent()
        val before = engine.state.value as EngineState.Ready
        val seen = mutableListOf<EngineState>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { engine.state.collect { seen += it } }
        engine.reportStall()
        runCurrent()
        assertTrue("no request may use the port while it is checked: $seen", seen.any { it is EngineState.Degraded })
        assertSame(before, engine.state.value)
        assertEquals(1, runtime.count("startApi"))
    }

    @Test
    fun `SEC-01 the engine leaves Ready before the API listener closes`() = runTest {
        val runtime = FakeEngineRuntime()
        val engine = engine(runtime)
        val states = mutableListOf<EngineState>()
        runtime.onStop = { states += engine.state.value }
        val lease = engine.acquire(EngineHolder.Ui)
        runCurrent()
        lease.close()
        runCurrent()
        advanceTimeBy(BentoEngine.IDLE_STOP_MS + 1)
        runCurrent()
        assertEquals(1, runtime.count("stop"))
        assertTrue("state during stop: $states", states.none { it is EngineState.Ready })
    }

    @Test
    fun `SEC-01 an unverified server stops the port at once and restarts with new credentials`() = runTest {
        val runtime = FakeEngineRuntime()
        val engine = engine(runtime)
        engine.acquire(EngineHolder.Ui)
        runCurrent()
        val before = engine.state.value as EngineState.Ready
        engine.reportUnverifiedServer(before.port + 1) // a stale port: ignored
        assertSame(before, engine.state.value)
        engine.reportUnverifiedServer(before.port)
        assertFalse("synchronously out of Ready", engine.state.value is EngineState.Ready)
        runCurrent()
        val after = engine.state.value as EngineState.Ready
        assertNotEquals(before.port, after.port)
        assertNotEquals(before.token, after.token)
        assertNotEquals(before.serverKey, after.serverKey)
    }
}
