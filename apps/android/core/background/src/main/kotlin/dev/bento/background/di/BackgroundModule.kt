package dev.bento.background.di

import android.content.Context
import androidx.work.WorkManager
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import dev.bento.background.BackgroundScheduler
import dev.bento.background.NotificationDriver
import dev.bento.engine.bridge.NotifierHub
import dev.bento.engine.di.ApplicationScope
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach

@Module
@InstallIn(SingletonComponent::class)
object BackgroundModule {
    @Provides
    @Singleton
    fun scheduler(@ApplicationContext context: Context): BackgroundScheduler = BackgroundScheduler { WorkManager.getInstance(context) }

    /** Collects backend Notifier events for the app's lifetime. */
    @Provides
    @Singleton
    fun notificationDriver(
        @ApplicationContext context: Context,
        hub: NotifierHub,
        @ApplicationScope scope: CoroutineScope
    ): NotificationDriver =
        NotificationDriver(context).also { driver -> hub.events.onEach(driver::handle).launchIn(scope) }
}
