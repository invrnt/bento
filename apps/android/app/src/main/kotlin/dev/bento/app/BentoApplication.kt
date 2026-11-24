package dev.bento.app

import android.app.Application
import android.content.Intent
import androidx.hilt.work.HiltWorkerFactory
import androidx.tracing.trace
import androidx.work.Configuration
import dagger.hilt.android.HiltAndroidApp
import dev.bento.background.BackgroundScheduler
import dev.bento.background.BentoNotifications
import dev.bento.background.NotificationDriver
import dev.bento.data.Invalidations
import dev.bento.engine.BentoEngine
import javax.inject.Inject

@HiltAndroidApp
class BentoApplication : Application(), Configuration.Provider {
    @Inject lateinit var engine: BentoEngine

    @Inject lateinit var workerFactory: HiltWorkerFactory

    @Inject lateinit var scheduler: BackgroundScheduler

    /** Injected so Notifier events are collected for the app's lifetime. */
    @Inject lateinit var notificationDriver: NotificationDriver

    /** Injected so server events start invalidating repositories. */
    @Inject lateinit var invalidations: Invalidations

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder().setWorkerFactory(workerFactory).setMinimumLoggingLevel(android.util.Log.WARN).build()

    override fun onCreate() {
        super.onCreate()
        trace("bento.app.onCreate") {
            // Interpreter warm-up on a background thread; the first frame never waits for it.
            engine.warmUp()
            BentoNotifications.createChannels(this)
            BentoNotifications.launchIntent = { context ->
                Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            }
            scheduler.ensureScheduled()
        }
    }
}
