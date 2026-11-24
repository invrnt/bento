package dev.bento.feature.settings

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import dev.bento.background.BackupControl
import dev.bento.background.BackupTileState
import dev.bento.engine.BentoEngine
import dev.bento.engine.EngineHolder
import javax.inject.Inject
import javax.inject.Singleton

/**
 * [BackupControl] for the Quick Settings tile and notification actions: runs with a `work:` engine holder so it also
 * works when the app is not open. The tile subtitle is the same status line as Ajustes › Respaldo.
 */
@Singleton
class BackupControlImpl @Inject constructor(
    @ApplicationContext private val context: Context,
    private val engine: BentoEngine,
    private val backup: BackupRepository
) : BackupControl {
    override suspend fun tileState(): BackupTileState = engine.withHolder(EngineHolder.Work(HOLDER)) {
        val sources = backup.sources()
        val on = sources.any { it.kind == BackupRepository.MEDIA_STORE && it.enabled }
        val policy = backup.policy()
        val status = backup.status()
        val header = BackupHeader.of(on, MediaPermissions.current(context), status, policy)
        BackupTileState(enabled = on, paused = policy.paused, subtitle = BackupCopy.header(context, header, System.currentTimeMillis()))
    }

    override suspend fun setPaused(paused: Boolean) {
        engine.withHolder(EngineHolder.Work(HOLDER)) { backup.setPaused(paused) }
    }

    private companion object {
        const val HOLDER = "backup-control"
    }
}
