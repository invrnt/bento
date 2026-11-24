package dev.bento.background

import android.content.Context
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.components.SingletonComponent

/** What the Quick Settings tile shows: [subtitle] is the status line ("Quedan 340 · esperando Wi-Fi"). */
data class BackupTileState(val enabled: Boolean, val paused: Boolean, val subtitle: String?)

/**
 * Pause/resume of the phone backup for surfaces outside the UI (Quick Settings tile, notification actions). Implemented
 * by feature/settings (bound with Hilt) so core/background does not depend on a feature; calls start the engine with a
 * `work:` holder when the app is not running.
 */
interface BackupControl {
    suspend fun tileState(): BackupTileState

    suspend fun setPaused(paused: Boolean)
}

/** Access for components Hilt cannot inject (TileService, BroadcastReceiver). */
@EntryPoint
@InstallIn(SingletonComponent::class)
interface BackgroundEntryPoint {
    fun backupControl(): BackupControl

    fun scheduler(): BackgroundScheduler

    companion object {
        fun get(context: Context): BackgroundEntryPoint =
            EntryPointAccessors.fromApplication(context.applicationContext, BackgroundEntryPoint::class.java)
    }
}
