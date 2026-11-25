package dev.bento.feature.activity

import dev.bento.engine.EngineState
import dev.bento.engine.WorkerMode
import dev.bento.feature.files.ImportFailure
import dev.bento.feature.files.ImportFailureLog
import dev.bento.feature.settings.BackupPolicy
import dev.bento.feature.settings.BackupStatus
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject

object ActivityFixtures {
    val ready: EngineState = EngineState.Ready(port = 1, token = "t", serverKey = "k", mode = WorkerMode.FULL)

    fun activity(json: String): ActivityDto = ActivityDto.parse(Json.parseToJsonElement(json).jsonObject)

    const val UPLOADING = """{"summary":"uploading","uploads":{"active":2,"queued":10,"bytes_total":40000000,"bytes_done":12000000,"eta_seconds":170},
        "downloads":{"active":0,"queued":0,"bytes_total":0,"bytes_done":0,"eta_seconds":null},"attention":[]}"""

    const val ATTENTION = """{"summary":"attention","uploads":{"active":0,"queued":0,"bytes_total":0,"bytes_done":0},
        "downloads":{"active":0,"queued":0,"bytes_total":0,"bytes_done":0},"attention":[
        {"id":"upload_failed:j1","kind":"upload_failed","title_key":"activity.attention.upload_failed","params":{"job_id":"j1","asset_id":"a1"},"action":"retry"},
        {"id":"sync_error","kind":"sync_error","title_key":"activity.attention.sync_error","params":{"code":"telegram_session_revoked"},"action":"retry"},
        {"id":"recovery_kit","kind":"recovery_kit","title_key":"activity.attention.recovery_kit","params":{},"action":"save_recovery_kit"},
        {"id":"new_device:d9","kind":"new_device","title_key":"activity.attention.new_device","params":{"device_id":"d9","name":"Pixel 9"},"action":"open_devices"},
        {"id":"clock_skew","kind":"clock_skew","title_key":"activity.attention.clock_skew","params":{"direction":"ahead","skew_seconds":600,"skew_minutes":10},"action":"none"}]}"""

    const val FLOOD = """{"summary":"syncing","attention":[{"id":"flood_wait","kind":"flood_wait",
        "params":{"retry_after_seconds":240,"retry_after_minutes":4},"action":"none"}]}"""

    const val IDLE = """{"summary":"up_to_date"}"""

    val failure = ImportFailure("Factura.pdf", ImportFailureLog.REASON_UNREADABLE, 1)

    fun overview(
        json: String = IDLE,
        backup: BackupStatus? = BackupStatus(),
        policy: BackupPolicy? = BackupPolicy(),
        engine: EngineState = ready,
        imports: List<ImportFailure> = emptyList(),
        backupOn: Boolean = true,
        stalled: Boolean = false
    ) = ActivityOverview(
        loaded = true,
        accountName = "Ana García",
        usageBytes = 1_320_000_000_000,
        devices = 3,
        activity = activity(json),
        backup = backup,
        policy = policy,
        backupOn = backupOn,
        engine = engine,
        importFailures = imports,
        stalled = stalled
    )
}
