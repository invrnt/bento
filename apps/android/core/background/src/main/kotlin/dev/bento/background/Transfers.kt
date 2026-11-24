package dev.bento.background

import android.app.Service
import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import dagger.hilt.android.AndroidEntryPoint
import dev.bento.engine.BentoEngine
import dev.bento.engine.EngineHolder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import javax.inject.Inject

/** Whether a user-initiated transfer is running (the ongoing notification exists only then). */
object TransferState {
    @Volatile
    var active: Boolean = false
        internal set
}

/** The transfer itself: hold `transfer` and drain in 5-minute slices while work remains. */
internal suspend fun runTransfer(engine: BentoEngine, slices: Int = MAX_SLICES) {
    TransferState.active = true
    try {
        engine.withHolder(EngineHolder.Transfer) {
            repeat(slices) {
                val result = engine.runWorkerUntil(System.currentTimeMillis() + SLICE_MS)
                if (!RunPlanner.continueTransfer(result)) return@withHolder
            }
        }
    } finally {
        TransferState.active = false
    }
}

private const val SLICE_MS = 5 * 60_000L
private const val MAX_SLICES = 72 // 6 h (Android 15 dataSync limit on the ≤ 13 path is never reached there)

/**
 * Starts user-initiated transfers (initial backup, share-to-Bento copies, transfers > 50 MB, "Respaldar ahora").
 * Android 14+: a user-initiated data transfer job (must be called while the app is visible).
 * Android 13 and older: the `dataSync` foreground service.
 */
object TransferScheduler {
    const val JOB_ID = 7001

    fun start(context: Context, estimatedBytes: Long = JobInfo.NETWORK_BYTES_UNKNOWN.toLong()) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            val job = JobInfo.Builder(JOB_ID, ComponentName(context, TransferJobService::class.java))
                .setUserInitiated(true)
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setEstimatedNetworkBytes(estimatedBytes, JobInfo.NETWORK_BYTES_UNKNOWN.toLong())
                .build()
            context.getSystemService(JobScheduler::class.java).schedule(job)
        } else {
            ContextCompat.startForegroundService(context, Intent(context, TransferForegroundService::class.java))
        }
    }

    /** `Pausar`: stop the running transfer (the backlog stays queued for the next run). */
    fun stop(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            context.getSystemService(JobScheduler::class.java).cancel(JOB_ID)
        } else {
            context.stopService(Intent(context, TransferForegroundService::class.java))
        }
    }

    fun isScheduled(context: Context): Boolean =
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE &&
            context.getSystemService(JobScheduler::class.java).getPendingJob(JOB_ID) != null
}

/** Android 14+ user-initiated data transfer job with its required notification. */
@AndroidEntryPoint
class TransferJobService : JobService() {
    @Inject lateinit var engine: BentoEngine

    @Inject lateinit var notifications: NotificationDriver

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var running: Job? = null

    override fun onStartJob(params: JobParameters): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            setNotification(
                params,
                BentoNotifications.ID_TRANSFER,
                BentoNotifications.transfer(this, notifications.lastProgress),
                JOB_END_NOTIFICATION_POLICY_REMOVE,
            )
        }
        running = scope.launch {
            val ok = runCatching { runTransfer(engine) }.isSuccess
            jobFinished(params, !ok)
        }
        return true
    }

    override fun onStopJob(params: JobParameters): Boolean {
        running?.cancel()
        // Rescheduled unless the user paused it (cancel() does not call onStopJob with a reschedule request).
        return params.stopReason != JobParameters.STOP_REASON_CANCELLED_BY_APP
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }
}

/** Android 13 and older: the same transfer as a `dataSync` foreground service. */
@AndroidEntryPoint
class TransferForegroundService : Service() {
    @Inject lateinit var engine: BentoEngine

    @Inject lateinit var notifications: NotificationDriver

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var running: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0
        ServiceCompat.startForeground(this, BentoNotifications.ID_TRANSFER, BentoNotifications.transfer(this, notifications.lastProgress), type)
        if (running?.isActive != true) {
            running = scope.launch {
                runCatching { runTransfer(engine) }
                ServiceCompat.stopForeground(this@TransferForegroundService, ServiceCompat.STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
        return START_NOT_STICKY
    }

    override fun onTimeout(startId: Int, fgsType: Int) {
        running?.cancel()
        stopSelf()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }
}

/** Notification actions (`Pausar`). */
class TransferActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == ACTION_PAUSE) TransferScheduler.stop(context)
    }

    companion object {
        const val ACTION_PAUSE = "dev.bento.background.action.PAUSE_TRANSFER"

        fun pauseIntent(context: Context): android.app.PendingIntent = android.app.PendingIntent.getBroadcast(
            context,
            0,
            Intent(context, TransferActionReceiver::class.java).setAction(ACTION_PAUSE),
            android.app.PendingIntent.FLAG_IMMUTABLE,
        )
    }
}
