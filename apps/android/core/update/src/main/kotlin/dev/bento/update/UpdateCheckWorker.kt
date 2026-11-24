package dev.bento.update

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import java.util.concurrent.TimeUnit

/** Daily background check (unmetered network only). It only checks: downloading and installing are user actions. */
@HiltWorker
class UpdateCheckWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val checker: UpdateChecker
) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        // Failures wait for the next daily run instead of retrying against the feed.
        checker.check()
        return Result.success()
    }
}

/** Arms the daily check; a no-op when the build has no update key. */
class UpdateScheduler(private val config: UpdateConfig, private val workManager: () -> WorkManager) {
    fun ensureScheduled() {
        if (!config.enabled) {
            workManager().cancelUniqueWork(WORK_NAME)
            return
        }
        val request = PeriodicWorkRequestBuilder<UpdateCheckWorker>(1, TimeUnit.DAYS, 6, TimeUnit.HOURS)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.UNMETERED).setRequiresBatteryNotLow(true).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 1, TimeUnit.HOURS)
            .setInitialDelay(1, TimeUnit.HOURS)
            .build()
        workManager().enqueueUniquePeriodicWork(WORK_NAME, ExistingPeriodicWorkPolicy.KEEP, request)
    }

    companion object {
        const val WORK_NAME: String = "bento-update-check"
    }
}
