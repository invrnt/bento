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
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

@HiltAndroidApp
class BentoApplication : Application(), Configuration.Provider {
    @Inject lateinit var engine: BentoEngine

    @Inject lateinit var workerFactory: HiltWorkerFactory

    @Inject lateinit var scheduler: BackgroundScheduler

    /** Injected so Notifier events are collected for the app's lifetime. */
    @Inject lateinit var notificationDriver: NotificationDriver

    /** Injected so server events start invalidating repositories. */
    @Inject lateinit var invalidations: Invalidations

    @Inject lateinit var shareCacheJanitor: ShareCacheJanitor

    /** Daily, check-only update poll; a no-op in builds without an update key. */
    @Inject lateinit var updates: dev.bento.update.UpdateScheduler

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder().setWorkerFactory(workerFactory).setMinimumLoggingLevel(android.util.Log.WARN).build()

    override fun onCreate() {
        super.onCreate()
        // Async trace slice from process start to the first Ready (Macrobenchmark "engine ready").
        androidx.tracing.Trace.beginAsyncSection(ENGINE_READY_SECTION, 0)
        kotlinx.coroutines.MainScope().launch {
            engine.state.first { it is dev.bento.engine.EngineState.Ready }
            androidx.tracing.Trace.endAsyncSection(ENGINE_READY_SECTION, 0)
        }
        trace("bento.app.onCreate") {
            // Interpreter warm-up on a background thread; the first frame never waits for it.
            engine.warmUp()
            BentoNotifications.createChannels(this)
            BentoNotifications.launchIntent = { context ->
                Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            }
            scheduler.ensureScheduled()
            shareCacheJanitor.start()
            updates.ensureScheduled()
        }
    }

    private companion object {
        const val ENGINE_READY_SECTION = "bento.engine.ready"
    }
}
