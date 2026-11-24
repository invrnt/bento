package dev.bento.background

import android.content.Context
import android.content.pm.ServiceInfo
import android.os.Build
import android.provider.MediaStore
import androidx.hilt.work.HiltWorker
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.ForegroundInfo
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import dev.bento.engine.BentoEngine
import dev.bento.engine.EngineHolder
import java.util.concurrent.TimeUnit

/** One background run: hold `work:<name>`, drain until the budget, decide what comes next. */
internal suspend fun BentoEngine.heldRun(
    name: String,
    budgetMs: Long,
    kinds: List<String>?,
    now: () -> Long = System::currentTimeMillis
): NextRun =
    try {
        val result = withHolder(EngineHolder.Work(name)) { runWorkerUntil(now() + budgetMs, kinds) }
        RunPlanner.next(result, now())
    } catch (error: Exception) {
        if (error is kotlinx.coroutines.CancellationException) throw error
        NextRun.Retry
    }

/** Content-URI triggered backup run (new media in the camera roll), re-armed after each run. */
@HiltWorker
class BackupWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val engine: BentoEngine,
    private val scheduler: BackgroundScheduler
) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val next = engine.heldRun("backup", BUDGET_MS, kinds = null)
        scheduler.armBackupTrigger()
        return scheduler.apply(next, BackgroundScheduler.BACKUP_RUN) { delay -> scheduler.enqueueBackupRun(delay) }
    }

    override suspend fun getForegroundInfo(): ForegroundInfo = transferForegroundInfo(applicationContext)
}

/** Periodic sync pull/flush, inbox import, small uploads, reconcile. */
@HiltWorker
class SyncWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val engine: BentoEngine,
    private val scheduler: BackgroundScheduler
) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val next = engine.heldRun("sync", BUDGET_MS, kinds = null)
        return scheduler.apply(next, BackgroundScheduler.SYNC_FOLLOW_UP) { delay -> scheduler.enqueueFlush(delay) }
    }

    override suspend fun getForegroundInfo(): ForegroundInfo = transferForegroundInfo(applicationContext)
}

/** OCR backlog while charging and idle, in batches. */
@HiltWorker
class OcrWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val engine: BentoEngine,
    private val scheduler: BackgroundScheduler
) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val next = engine.heldRun("ocr", BUDGET_MS, kinds = listOf("ocr_index"))
        return scheduler.apply(next, BackgroundScheduler.OCR) { delay -> scheduler.enqueueOcr(delay) }
    }
}

/** WorkManager budget is ~10 min per run; stop draining a minute early. */
internal const val BUDGET_MS = 9 * 60_000L

internal fun transferForegroundInfo(context: Context): ForegroundInfo {
    val notification = BentoNotifications.transfer(context, null)
    return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        ForegroundInfo(BentoNotifications.ID_TRANSFER, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
    } else {
        ForegroundInfo(BentoNotifications.ID_TRANSFER, notification)
    }
}

/** All WorkManager scheduling (architecture/android-runtime.md §6). Never asks for battery exemptions. */
class BackgroundScheduler(private val workManager: () -> WorkManager) {
    /** App start: periodic sync, the media trigger and the OCR backlog are always armed (idempotent). */
    fun ensureScheduled() {
        ensurePeriodicSync()
        armBackupTrigger()
        enqueueOcr(0)
    }

    fun ensurePeriodicSync() {
        val request = PeriodicWorkRequestBuilder<SyncWorker>(1, TimeUnit.HOURS, 15, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).setRequiresBatteryNotLow(true).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 1, TimeUnit.MINUTES)
            .build()
        workManager().enqueueUniquePeriodicWork(SYNC, ExistingPeriodicWorkPolicy.KEEP, request)
    }

    /** Content-URI trigger on images and videos; appended so a running backup is never cancelled. */
    fun armBackupTrigger() {
        val constraints = Constraints.Builder()
            .addContentUriTrigger(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, true)
            .addContentUriTrigger(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, true)
            .setTriggerContentUpdateDelay(5, TimeUnit.SECONDS)
            .setTriggerContentMaxDelay(1, TimeUnit.MINUTES)
            .build()
        val request = OneTimeWorkRequestBuilder<BackupWorker>().setConstraints(constraints).build()
        workManager().enqueueUniqueWork(BACKUP_TRIGGER, ExistingWorkPolicy.KEEP, request)
    }

    fun enqueueBackupRun(delayMs: Long) = enqueue<BackupWorker>(BACKUP_RUN, delayMs, expedited = delayMs == 0L)

    /** After a local change in the UI: an expedited flush within seconds. */
    fun enqueueFlush(delayMs: Long = 0) = enqueue<SyncWorker>(SYNC_FOLLOW_UP, delayMs, expedited = delayMs == 0L)

    fun enqueueOcr(delayMs: Long) {
        val constraints = Constraints.Builder().setRequiresCharging(true).setRequiresDeviceIdle(true).build()
        val request = OneTimeWorkRequestBuilder<OcrWorker>()
            .setConstraints(constraints)
            .setInitialDelay(delayMs, TimeUnit.MILLISECONDS)
            .build()
        workManager().enqueueUniqueWork(OCR, ExistingWorkPolicy.KEEP, request)
    }

    /** Maps a [NextRun] to the worker result, enqueuing a follow-up with [enqueue] when needed. */
    fun apply(next: NextRun, @Suppress("UNUSED_PARAMETER") name: String, enqueue: (Long) -> Unit): androidx.work.ListenableWorker.Result =
        when (next) {
            NextRun.Done -> androidx.work.ListenableWorker.Result.success()

            is NextRun.Again -> {
                enqueue(next.delayMs)
                androidx.work.ListenableWorker.Result.success()
            }

            NextRun.Retry -> androidx.work.ListenableWorker.Result.retry()
        }

    private inline fun <reified W : CoroutineWorker> enqueue(name: String, delayMs: Long, expedited: Boolean) {
        val builder = OneTimeWorkRequestBuilder<W>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
        if (expedited) {
            builder.setExpedited(
                OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST
            )
        } else {
            builder.setInitialDelay(delayMs, TimeUnit.MILLISECONDS)
        }
        workManager().enqueueUniqueWork(name, ExistingWorkPolicy.APPEND_OR_REPLACE, builder.build())
    }

    companion object {
        const val SYNC = "bento-sync"
        const val SYNC_FOLLOW_UP = "bento-sync-follow-up"
        const val BACKUP_TRIGGER = "bento-backup-trigger"
        const val BACKUP_RUN = "bento-backup-run"
        const val OCR = "bento-ocr"
    }
}
