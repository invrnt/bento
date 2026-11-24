package dev.bento.engine

import dev.bento.testing.FakeEngineRuntime
import dev.bento.testing.TestEngineHarness
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class BentoEngineTest {
    @Test
    fun `first holder starts the engine in contract order`() = runTest {
        val h = TestEngineHarness(this)
        h.engine.acquire(EngineHolder.Ui)
        runCurrent()
        assertEquals(listOf("warmUp", "configure", "migrate", "startWorker:full", "startApi"), h.runtime.calls)
        val ready = h.engine.state.value as EngineState.Ready
        assertEquals(41_000, ready.port)
        assertEquals("test-token-0123456789", ready.token)
        assertEquals(WorkerMode.FULL, ready.mode)
        assertTrue(h.keeper.kept)
        assertEquals(32, h.runtime.configuredKeySize)
        assertEquals("http://127.0.0.1:41000", ready.baseUrl)
        assertFalse("token must not appear in toString", ready.toString().contains("test-token"))
    }

    @Test
    fun `background holder runs drain mode and ui switches to full`() = runTest {
        val h = TestEngineHarness(this)
        h.engine.acquire(EngineHolder.Work("backup"))
        runCurrent()
        assertEquals(WorkerMode.DRAIN, (h.engine.state.value as EngineState.Ready).mode)
        h.engine.acquire(EngineHolder.Ui)
        runCurrent()
        assertEquals(WorkerMode.FULL, (h.engine.state.value as EngineState.Ready).mode)
        assertEquals(1, h.runtime.count("startApi"))
        assertTrue(h.runtime.calls.contains("startWorker:full"))
    }

    @Test
    fun `engine stops 60 s after the last holder is released`() = runTest {
        val h = TestEngineHarness(this)
        val ui = h.engine.acquire(EngineHolder.Ui)
        val work = h.engine.acquire(EngineHolder.Work("sync"))
        runCurrent()
        ui.close()
        runCurrent()
        advanceTimeBy(120_000)
        assertTrue("still held by work", h.engine.state.value is EngineState.Ready)
        work.close()
        runCurrent()
        advanceTimeBy(59_000)
        runCurrent()
        assertTrue(h.engine.state.value is EngineState.Ready)
        advanceTimeBy(1_001)
        runCurrent()
        assertEquals(EngineState.Stopped, h.engine.state.value)
        assertEquals(1, h.runtime.count("stop"))
        assertFalse(h.keeper.kept)
    }

    @Test
    fun `reacquiring during the idle window cancels the stop`() = runTest {
        val h = TestEngineHarness(this)
        val first = h.engine.acquire(EngineHolder.Ui)
        runCurrent()
        first.close()
        runCurrent()
        advanceTimeBy(30_000)
        h.engine.acquire(EngineHolder.Transfer)
        runCurrent()
        advanceTimeBy(120_000)
        runCurrent()
        assertTrue(h.engine.state.value is EngineState.Ready)
        assertEquals(0, h.runtime.count("stop"))
    }

    @Test
    fun `restart after stop configures only once and gets a new port`() = runTest {
        val h = TestEngineHarness(this)
        val first = h.engine.acquire(EngineHolder.Ui)
        runCurrent()
        first.close()
        runCurrent()
        advanceTimeBy(61_000)
        runCurrent()
        h.engine.acquire(EngineHolder.Ui)
        runCurrent()
        assertEquals(1, h.runtime.count("configure"))
        assertEquals(2, h.runtime.count("migrate"))
        assertEquals(41_001, (h.engine.state.value as EngineState.Ready).port)
    }

    @Test
    fun `acquire and immediate release never starts the engine`() = runTest {
        val h = TestEngineHarness(this)
        h.engine.acquire(EngineHolder.Ui).close()
        runCurrent()
        assertEquals(EngineState.Stopped, h.engine.state.value)
        assertTrue(h.runtime.calls.isEmpty())
    }

    @Test
    fun `lease close is idempotent and reference counted`() = runTest {
        val h = TestEngineHarness(this)
        val a = h.engine.acquire(EngineHolder.Ui)
        val b = h.engine.acquire(EngineHolder.Ui)
        runCurrent()
        a.close()
        a.close()
        assertEquals(setOf<EngineHolder>(EngineHolder.Ui), h.engine.activeHolders())
        b.close()
        assertTrue(h.engine.activeHolders().isEmpty())
    }

    @Test
    fun `start failure retries with backoff`() = runTest {
        val h = TestEngineHarness(this, FakeEngineRuntime(failStarts = 1))
        h.engine.acquire(EngineHolder.Ui)
        runCurrent()
        assertEquals(EngineState.Degraded(DegradedReason.START_FAILED), h.engine.state.value)
        advanceTimeBy(999)
        runCurrent()
        assertTrue(h.engine.state.value is EngineState.Degraded)
        advanceTimeBy(2)
        runCurrent()
        assertTrue(h.engine.state.value is EngineState.Ready)
    }

    @Test
    fun `three failures within five minutes surface a crash loop attention item`() = runTest {
        val h = TestEngineHarness(this, FakeEngineRuntime(failStarts = 3))
        h.engine.acquire(EngineHolder.Ui)
        runCurrent()
        advanceTimeBy(1_001) // retry 1 fails
        runCurrent()
        assertEquals(EngineState.Degraded(DegradedReason.START_FAILED), h.engine.state.value)
        advanceTimeBy(5_001) // retry 2 fails → third failure
        runCurrent()
        assertEquals(EngineState.Degraded(DegradedReason.CRASH_LOOP, attention = true), h.engine.state.value)
        advanceTimeBy(30_001)
        runCurrent()
        assertTrue(h.engine.state.value is EngineState.Ready)
    }

    @Test
    fun `releasing every holder while degraded stops retrying`() = runTest {
        val h = TestEngineHarness(this, FakeEngineRuntime(failStarts = 5))
        val lease = h.engine.acquire(EngineHolder.Ui)
        runCurrent()
        lease.close()
        runCurrent()
        advanceTimeBy(60_000)
        runCurrent()
        assertEquals(EngineState.Stopped, h.engine.state.value)
        assertEquals(1, h.runtime.count("migrate"))
    }

    @Test
    fun `awaitReady times out with EngineUnavailableException`() = runTest {
        val h = TestEngineHarness(this)
        try {
            h.engine.awaitReady(timeoutMs = 1_000)
            fail("expected EngineUnavailableException")
        } catch (expected: EngineUnavailableException) {
            assertEquals(EngineState.Stopped, expected.state)
        }
    }

    @Test
    fun `withHolder waits for ready and releases afterwards`() = runTest {
        val h = TestEngineHarness(this)
        val port = h.engine.withHolder(EngineHolder.Work("ocr")) { it.port }
        assertEquals(41_000, port)
        assertTrue(h.engine.activeHolders().isEmpty())
    }

    @Test
    fun `stall with the API gone restarts it on a new port`() = runTest {
        val h = TestEngineHarness(this)
        h.engine.acquire(EngineHolder.Ui)
        runCurrent()
        h.runtime.apiPort = null
        h.engine.reportStall()
        runCurrent()
        assertEquals(41_001, (h.engine.state.value as EngineState.Ready).port)
    }

    @Test
    fun `runWorkerUntil requires a holder and forwards to the runtime`() = runTest {
        val h = TestEngineHarness(this)
        try {
            h.engine.runWorkerUntil(deadlineEpochMs = 1)
            fail("expected IllegalStateException")
        } catch (expected: IllegalStateException) {
            assertTrue(expected.message!!.contains("holder"))
        }
        h.engine.acquire(EngineHolder.Work("backup"))
        val result = h.engine.runWorkerUntil(deadlineEpochMs = 10_000)
        assertEquals(WorkerRunResult.StopReason.IDLE, result.stoppedReason)
        assertEquals(1, h.runtime.count("runWorkerUntil"))
    }

    @Test
    fun `events are forwarded only while running`() = runTest {
        val h = TestEngineHarness(this)
        h.engine.onEvent("media_changed", "{}")
        assertTrue(h.runtime.events.isEmpty())
        h.engine.acquire(EngineHolder.Ui)
        runCurrent()
        h.engine.onEvent("conditions", "{\"online\":true}")
        assertEquals(listOf("conditions" to "{\"online\":true}"), h.runtime.events)
    }
}
