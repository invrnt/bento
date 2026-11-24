package dev.bento.background

import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import dev.bento.strings.R as StringsR
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Tile appearance for a [BackupTileState] (pure; JVM tested). */
object TileLook {
    fun state(state: BackupTileState?): Int = when {
        state == null || !state.enabled -> Tile.STATE_UNAVAILABLE
        state.paused -> Tile.STATE_INACTIVE
        else -> Tile.STATE_ACTIVE
    }
}

/**
 * Quick Settings tile "Respaldo de Bento" (product/android.md §7): tap pauses/resumes the phone backup, long-press opens
 * Ajustes › Respaldo (MainActivity handles `QS_TILE_PREFERENCES`), the subtitle is the status line. Never a toast.
 */
class BackupTileService : TileService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var refresh: Job? = null
    private var last: BackupTileState? = null

    private val control: BackupControl get() = BackgroundEntryPoint.get(this).backupControl()

    override fun onStartListening() {
        super.onStartListening()
        render(last)
        refresh?.cancel()
        refresh = scope.launch { render(load()) }
    }

    override fun onStopListening() {
        refresh?.cancel()
        super.onStopListening()
    }

    override fun onClick() {
        super.onClick()
        val current = last ?: return
        if (!current.enabled) return
        val next = current.copy(paused = !current.paused)
        render(next)
        scope.launch {
            runCatching { withContext(Dispatchers.IO) { control.setPaused(next.paused) } }
            if (next.paused) TransferScheduler.stop(this@BackupTileService)
            render(load())
        }
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private suspend fun load(): BackupTileState? = runCatching { withContext(Dispatchers.IO) { control.tileState() } }.getOrNull()
        ?: last

    private fun render(state: BackupTileState?) {
        last = state
        val tile = qsTile ?: return
        tile.label = getString(StringsR.string.activity_tile_label)
        tile.state = TileLook.state(state)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) tile.subtitle = state?.subtitle
        tile.stateDescription(state)
        tile.updateTile()
    }

    private fun Tile.stateDescription(state: BackupTileState?) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return
        stateDescription = when {
            state == null || !state.enabled -> getString(StringsR.string.activity_tile_off)
            state.paused -> getString(StringsR.string.activity_tile_paused)
            else -> getString(StringsR.string.activity_tile_on)
        }
    }
}
