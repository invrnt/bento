package dev.bento.feature.activity

import dev.bento.api.BentoJson
import dev.bento.designsystem.component.AvatarStatus
import dev.bento.engine.EngineState
import dev.bento.feature.files.ImportFailure
import dev.bento.feature.settings.BackupPolicy
import dev.bento.feature.settings.BackupStatus
import dev.bento.feature.settings.WaitReason
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull

/*
 * `GET /api/activity` declares no response model in the OpenAPI schema, so no DTO is generated; these mirror
 * `routes_activity.py` (read leniently) until it does (listed in the handoff).
 */

@Serializable
data class TransferStatsDto(
    val active: Int = 0,
    val queued: Int = 0,
    @SerialName("bytes_total") val bytesTotal: Long = 0,
    @SerialName("bytes_done") val bytesDone: Long = 0,
    @SerialName("eta_seconds") val etaSeconds: Long? = null
) {
    val count: Int get() = active + queued
    val fraction: Float? get() = if (bytesTotal > 0) (bytesDone.toFloat() / bytesTotal).coerceIn(0f, 1f) else null
}

@Serializable
data class AttentionDto(
    val id: String,
    val kind: String,
    @SerialName("title_key") val titleKey: String? = null,
    val params: JsonObject = JsonObject(emptyMap()),
    val action: String = "none"
) {
    fun string(key: String): String? = (params[key] as? JsonPrimitive)?.takeIf { it.isString || it.content != "null" }?.content

    fun int(key: String): Int? = (params[key] as? JsonPrimitive)?.intOrNull

    fun long(key: String): Long? = (params[key] as? JsonPrimitive)?.longOrNull
}

@Serializable
data class ActivityDto(
    val summary: String = "up_to_date",
    val uploads: TransferStatsDto = TransferStatsDto(),
    val downloads: TransferStatsDto = TransferStatsDto(),
    val attention: List<AttentionDto> = emptyList()
) {
    companion object {
        fun parse(
            json: JsonObject
        ): ActivityDto = runCatching { BentoJson.decodeFromJsonElement(serializer(), json) }.getOrDefault(ActivityDto())
    }
}

/** One thing that needs the person, with at most one action (product/android.md §7). */
sealed interface AttentionEntry {
    val key: String

    data class Backend(val item: AttentionDto, val action: AttentionAction) : AttentionEntry {
        override val key = "backend:${item.id}"
    }

    /** A share/upload that never made it in (agent 40's `ImportFailureLog`), reported with its file name. */
    data class ImportFailed(val failure: ImportFailure) : AttentionEntry {
        override val key = "import:${failure.name}:${failure.atMs}"
    }
}

/** The single action of an attention item. */
enum class AttentionAction { Retry, RetrySync, Reconnect, SaveKit, ReviewDevice, ReviewRemoved, Dismiss, None }

object AttentionActions {
    private val SIGNED_OUT =
        setOf("telegram_session_revoked", "session_revoked", "telegram_signed_out", "signed_out", "telegram_auth_required")

    fun of(item: AttentionDto): AttentionAction = when (item.kind) {
        "upload_failed" -> if (item.string("job_id") != null) AttentionAction.Retry else AttentionAction.None
        "sync_error" -> if (item.string("code") in SIGNED_OUT) AttentionAction.Reconnect else AttentionAction.RetrySync
        "recovery_kit" -> AttentionAction.SaveKit
        "new_device" -> if (item.string("device_id") != null) AttentionAction.ReviewDevice else AttentionAction.None
        "device_removed" -> AttentionAction.ReviewRemoved
        else -> AttentionAction.None
    }
}

/** The status line of the sheet and the TalkBack text of the avatar ("Todo al día ✓", "Subiendo 12 archivos · 3 min"…). */
sealed interface StatusLine {
    data object UpToDate : StatusLine

    data class Uploading(val count: Int, val etaSeconds: Long?) : StatusLine

    data class Downloading(val count: Int) : StatusLine

    data object Syncing : StatusLine

    data object Offline : StatusLine

    data class FloodWait(val minutes: Int) : StatusLine

    data class Paused(val lowBattery: Boolean) : StatusLine

    data class Waiting(val pending: Int, val reason: WaitReason) : StatusLine

    data class Attention(val count: Int) : StatusLine

    data object Starting : StatusLine
}

/** Everything the avatar, the sheet, the tile and Activity show, derived from the backend answers (pure; JVM tested). */
data class ActivityOverview(
    val loaded: Boolean = false,
    val accountName: String? = null,
    val usageBytes: Long? = null,
    val devices: Int? = null,
    val activity: ActivityDto = ActivityDto(),
    val backup: BackupStatus? = null,
    val policy: BackupPolicy? = null,
    val backupOn: Boolean = false,
    val engine: EngineState = EngineState.Stopped,
    val importFailures: List<ImportFailure> = emptyList(),
    /** OEM background killer suspected (feature/settings `StallDetector`). */
    val stalled: Boolean = false
) {
    val attention: List<AttentionEntry>
        // A Telegram wait is the status line itself ("Telegram pidió esperar 4 min"), not something to act on.
        get() = activity.attention.filter { it.kind != "flood_wait" }
            .map { AttentionEntry.Backend(it, AttentionActions.of(it)) } +
            importFailures.sortedByDescending { it.atMs }.map { AttentionEntry.ImportFailed(it) }

    val paused: Boolean get() = policy?.paused == true

    val offline: Boolean get() = activity.summary == "offline" || engine is EngineState.Degraded

    val status: StatusLine get() = StatusLines.of(this)

    val avatar: AvatarStatus get() = StatusLines.avatar(this)

    /** Determinate ring while uploading with known bytes. */
    val progress: Float? get() = if (avatar == AvatarStatus.Syncing) activity.uploads.fraction ?: activity.downloads.fraction else null
}

object StatusLines {
    // The status-line precedence of product/android.md §7, one branch per line so it reads against the spec.
    @Suppress("CyclomaticComplexMethod")
    fun of(o: ActivityOverview): StatusLine {
        val a = o.activity
        val flood = a.attention.firstOrNull { it.kind == "flood_wait" }
        return when {
            !o.loaded && o.engine !is EngineState.Ready -> StatusLine.Starting

            o.offline -> StatusLine.Offline

            flood != null -> StatusLine.FloodWait(
                flood.int("retry_after_minutes") ?: ((flood.long("retry_after_seconds") ?: 60) / 60).toInt()
            )

            o.paused -> StatusLine.Paused(lowBattery = false)

            a.uploads.count > 0 -> StatusLine.Uploading(a.uploads.count, a.uploads.etaSeconds)

            a.downloads.count > 0 -> StatusLine.Downloading(a.downloads.count)

            o.policy?.effectivePaused == true -> StatusLine.Paused(lowBattery = true)

            o.backupOn && (o.backup?.pending ?: 0) > 0 && o.backup?.waitReason != null ->
                if (o.backup.waitReason ==
                    WaitReason.Battery
                ) {
                    StatusLine.Paused(true)
                } else {
                    StatusLine.Waiting(o.backup.pending, o.backup.waitReason!!)
                }

            a.summary == "syncing" -> StatusLine.Syncing

            o.attention.isNotEmpty() -> StatusLine.Attention(o.attention.size)

            else -> StatusLine.UpToDate
        }
    }

    /** Ring states of product/android.md §7: offline > attention > paused > syncing > none. */
    fun avatar(o: ActivityOverview): AvatarStatus = when {
        o.offline -> AvatarStatus.Offline

        o.attention.isNotEmpty() -> AvatarStatus.Attention

        o.paused || o.policy?.effectivePaused == true -> AvatarStatus.Paused

        o.activity.uploads.count > 0 || o.activity.downloads.count > 0 || o.activity.summary in setOf(
            "uploading",
            "downloading",
            "syncing"
        ) ->
            AvatarStatus.Syncing

        else -> AvatarStatus.Idle
    }
}
