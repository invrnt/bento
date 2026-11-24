package dev.bento.background

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.work.Configuration
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.testing.SynchronousExecutor
import androidx.work.testing.WorkManagerTestInitHelper
import dev.bento.engine.EngineHolder
import dev.bento.engine.WorkerRunResult
import dev.bento.engine.WorkerRunResult.StopReason
import dev.bento.engine.bridge.EngineEvent
import dev.bento.testing.TestEngineHarness
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

class RunPlannerTest {
    private fun result(reason: StopReason, remaining: Int, next: Long? = null) = WorkerRunResult(1, remaining, next, reason)

    @Test
    fun `deadline with work left runs again immediately`() {
        assertEquals(NextRun.Again(0), RunPlanner.next(result(StopReason.DEADLINE, 5), 0))
        assertEquals(NextRun.Done, RunPlanner.next(result(StopReason.DEADLINE, 0), 0))
    }

    @Test
    fun `idle with future eligible jobs waits until then, clamped`() {
        assertEquals(NextRun.Again(60_000), RunPlanner.next(result(StopReason.IDLE, 2, next = 160_000), 100_000))
        assertEquals(NextRun.Again(RunPlanner.MIN_DELAY_MS), RunPlanner.next(result(StopReason.IDLE, 2, next = 100_001), 100_000))
        assertEquals(NextRun.Again(RunPlanner.MAX_DELAY_MS), RunPlanner.next(result(StopReason.IDLE, 2, next = Long.MAX_VALUE), 0))
        assertEquals(NextRun.Done, RunPlanner.next(result(StopReason.IDLE, 0), 0))
    }

    @Test
    fun `conditions wait for constraints and errors retry`() {
        assertEquals(NextRun.Done, RunPlanner.next(result(StopReason.CONDITIONS, 9), 0))
        assertEquals(NextRun.Retry, RunPlanner.next(result(StopReason.ERROR, 9), 0))
    }

    @Test
    fun `transfers continue only while sliced by the deadline`() {
        assertTrue(RunPlanner.continueTransfer(result(StopReason.DEADLINE, 3)))
        assertTrue(!RunPlanner.continueTransfer(result(StopReason.CONDITIONS, 3)))
        assertTrue(!RunPlanner.continueTransfer(result(StopReason.DEADLINE, 0)))
    }
}

class NotificationPolicyTest {
    private var now = 0L
    private val policy = NotificationPolicy { now }

    private fun progress(done: Int, paused: Boolean = false) =
        EngineEvent.TransferProgress(EngineEvent.TransferKind.BACKUP, done, 10, done * 10L, 100, paused)

    @Test
    fun `progress is rate limited to 1 Hz except pause changes`() {
        assertTrue(policy.decide(progress(1)) is NotificationDecision.Progress)
        now = 500
        assertEquals(NotificationDecision.Ignore, policy.decide(progress(2)))
        now = 600
        assertTrue(policy.decide(progress(2, paused = true)) is NotificationDecision.Progress)
        now = 1_700
        assertTrue(policy.decide(progress(3, paused = true)) is NotificationDecision.Progress)
    }

    @Test
    fun `backup completion shows a summary of successful items only`() {
        assertEquals(
            NotificationDecision.Finished(EngineEvent.TransferKind.BACKUP, 17),
            policy.decide(EngineEvent.TransferFinished(EngineEvent.TransferKind.BACKUP, 18, 1)),
        )
        assertEquals(
            NotificationDecision.Finished(EngineEvent.TransferKind.UPLOAD, 0),
            policy.decide(EngineEvent.TransferFinished(EngineEvent.TransferKind.UPLOAD, 3, 0)),
        )
    }

    @Test
    fun `attention at most once per day per code`() {
        assertEquals(NotificationDecision.Attention("kit_pending"), policy.decide(EngineEvent.Attention("kit_pending", 1)))
        now = 60_000
        assertEquals(NotificationDecision.Ignore, policy.decide(EngineEvent.Attention("kit_pending", 2)))
        assertEquals(NotificationDecision.Attention("session_revoked"), policy.decide(EngineEvent.Attention("session_revoked", 1)))
        now = NotificationPolicy.ATTENTION_INTERVAL_MS + 1
        assertEquals(NotificationDecision.Attention("kit_pending"), policy.decide(EngineEvent.Attention("kit_pending", 1)))
    }

    @Test
    fun `device events and unknown events`() {
        assertEquals(NotificationDecision.DeviceRequest("r1", "Portátil"), policy.decide(EngineEvent.PairingRequest("r1", "Portátil", "desktop")))
        assertEquals(NotificationDecision.DeviceAdded("d1", "Tablet"), policy.decide(EngineEvent.NewDevice("d1", "Tablet")))
        assertEquals(NotificationDecision.Ignore, policy.decide(EngineEvent.Unknown("x")))
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class HeldRunTest {
    @Test
    fun `background runs hold work_name for exactly the run`() = runTest {
        val h = TestEngineHarness(this)
        h.runtime.runResult = WorkerRunResult(4, 2, null, StopReason.DEADLINE)
        val next = h.engine.heldRun("backup", budgetMs = 1_000, kinds = null) { 0 }
        assertEquals(NextRun.Again(0), next)
        assertEquals(1, h.runtime.count("runWorkerUntil"))
        assertTrue(h.runtime.calls.contains("startWorker:drain"))
        assertTrue(h.engine.activeHolders().isEmpty())
    }

    @Test
    fun `a failing engine makes the worker retry`() = runTest {
        val h = TestEngineHarness(this, dev.bento.testing.FakeEngineRuntime(failStarts = 100))
        assertEquals(NextRun.Retry, h.engine.heldRun("sync", budgetMs = 1_000, kinds = null) { 0 })
        assertTrue(EngineHolder.Work("sync") !in h.engine.activeHolders())
    }
}

@RunWith(RobolectricTestRunner::class)
class BackgroundSchedulerTest {
    private lateinit var context: Context
    private lateinit var workManager: WorkManager

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        WorkManagerTestInitHelper.initializeTestWorkManager(
            context,
            Configuration.Builder().setExecutor(SynchronousExecutor()).build(),
        )
        workManager = WorkManager.getInstance(context)
    }

    private fun infos(name: String): List<WorkInfo> = workManager.getWorkInfosForUniqueWork(name).get()

    @Test
    fun `app start arms sync, the media trigger and OCR once`() {
        val scheduler = BackgroundScheduler { workManager }
        scheduler.ensureScheduled()
        scheduler.ensureScheduled()
        assertEquals(1, infos(BackgroundScheduler.SYNC).size)
        val trigger = infos(BackgroundScheduler.BACKUP_TRIGGER).single()
        assertEquals(2, trigger.constraints.contentUriTriggers.size)
        val ocr = infos(BackgroundScheduler.OCR).single()
        assertTrue(ocr.constraints.requiresCharging())
        assertTrue(ocr.constraints.requiresDeviceIdle())
    }

    @Test
    fun `periodic sync needs network and battery not low`() {
        BackgroundScheduler { workManager }.ensurePeriodicSync()
        val sync = infos(BackgroundScheduler.SYNC).single()
        assertEquals(androidx.work.NetworkType.CONNECTED, sync.constraints.requiredNetworkType)
        assertTrue(sync.constraints.requiresBatteryNotLow())
        assertEquals(60 * 60_000L, sync.periodicityInfo!!.repeatIntervalMillis)
    }

    @Test
    fun `follow-up runs are appended, not replacing a running one`() {
        val scheduler = BackgroundScheduler { workManager }
        scheduler.enqueueBackupRun(60_000)
        scheduler.enqueueBackupRun(60_000)
        assertTrue(infos(BackgroundScheduler.BACKUP_RUN).isNotEmpty())
    }
}
