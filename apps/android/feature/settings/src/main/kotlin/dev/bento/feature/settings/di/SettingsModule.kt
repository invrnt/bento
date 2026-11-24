package dev.bento.feature.settings.di

import android.content.Context
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.preferencesDataStoreFile
import dagger.Binds
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import dev.bento.background.BackupControl
import dev.bento.feature.settings.AndroidPhoneMedia
import dev.bento.feature.settings.AppLockState
import dev.bento.feature.settings.BackupControlImpl
import dev.bento.feature.settings.Clock
import dev.bento.feature.settings.LocalSettings
import dev.bento.feature.settings.PhoneMedia
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object SettingsModule {
    @Provides
    @Singleton
    fun localSettings(@ApplicationContext context: Context): LocalSettings =
        LocalSettings(PreferenceDataStoreFactory.create { context.preferencesDataStoreFile(LocalSettings.FILE) })

    /** Locked before the first frame of a cold start when the lock is on. */
    @Provides
    @Singleton
    fun appLock(local: LocalSettings): AppLockState = AppLockState(initiallyLocked = local.current().lockEnabled)

    @Provides
    fun clock(): Clock = Clock(System::currentTimeMillis)
}

@Module
@InstallIn(SingletonComponent::class)
interface SettingsBindings {
    @Binds
    fun phoneMedia(impl: AndroidPhoneMedia): PhoneMedia

    /** Quick Settings tile and notification actions (core/background) pause/resume through this. */
    @Binds
    fun backupControl(impl: BackupControlImpl): BackupControl
}

/** For code that runs before Hilt injects an activity (MainActivity.attachBaseContext: in-app language ≤ Android 12). */
@dagger.hilt.EntryPoint
@InstallIn(SingletonComponent::class)
interface SettingsEntryPoint {
    fun localSettings(): LocalSettings

    companion object {
        fun get(context: Context): SettingsEntryPoint =
            dagger.hilt.android.EntryPointAccessors.fromApplication(context.applicationContext, SettingsEntryPoint::class.java)
    }
}
