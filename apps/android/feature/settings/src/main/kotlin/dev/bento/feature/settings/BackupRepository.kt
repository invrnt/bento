package dev.bento.feature.settings

import dev.bento.api.BentoJson
import dev.bento.api.generated.BackupPolicyPatchRequest
import dev.bento.api.generated.BackupSourceCreateRequest
import dev.bento.api.generated.BackupSourcePatchRequest
import dev.bento.api.generated.BentoEndpoints
import dev.bento.api.generated.FreeUpSpaceConfirmRequest
import dev.bento.data.Invalidations
import dev.bento.data.Topic
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

/*
 * The backup routes (`/api/backup/…`) declare no response models in the OpenAPI schema (`response_model=None`), so no DTOs are
 * generated for them. These are the shapes `routes_backup.py` returns, read leniently (unknown keys ignored); they move
 * to generated DTOs automatically once the routes declare models (listed in the handoff).
 */

/** `GET /api/backup/status` (api/android-endpoints.md §3). */
@Serializable
data class BackupStatus(
    val pending: Int = 0,
    val waiting: Map<String, Int> = emptyMap(),
    @SerialName("uploaded_today") val uploadedToday: Int = 0,
    @SerialName("last_backup_at") val lastBackupAt: String? = null,
    @SerialName("partial_access") val partialAccess: Boolean = false,
    @SerialName("location_access") val locationAccess: Boolean = true
) {
    /** The first reason the backlog waits for, in the order the person can act on it. */
    val waitReason: WaitReason? get() = WaitReason.entries.firstOrNull { (waiting[it.key] ?: 0) > 0 }
}

/** Deferral reasons (`domain/device.py` `WaitReason`), most actionable first. */
enum class WaitReason(val key: String) { Offline("offline"), Wifi("wifi"), Charging("charging"), Battery("battery"), Thermal("thermal") }

/** One backup source (`GET /api/backup/sources`). */
@Serializable
data class BackupSourceDto(
    val id: String,
    val kind: String = "folder",
    @SerialName("bucket_id") val bucketId: String? = null,
    val label: String? = null,
    val enabled: Boolean = true,
    val state: String? = null,
    @SerialName("files_total") val filesTotal: Int = 0,
    @SerialName("files_done") val filesDone: Int = 0,
    @SerialName("files_pending") val filesPending: Int = 0,
    @SerialName("bytes_pending") val bytesPending: Long = 0,
    val error: String? = null
)

/** A MediaStore bucket suggestion (`GET /api/backup/suggestions` on Android). */
@Serializable
data class BucketSuggestion(
    val id: String? = null,
    val kind: String = "folder",
    val name: String? = null,
    val label: String? = null,
    val count: Int = 0,
    val suggested: Boolean = false
) {
    val title: String get() = name ?: label.orEmpty()
}

@Serializable
data class BackupPolicy(
    val paused: Boolean = false,
    @SerialName("pause_on_battery") val pauseOnBattery: Boolean = true,
    @SerialName("on_battery") val onBattery: Boolean = false,
    @SerialName("effective_paused") val effectivePaused: Boolean = false
)

@Serializable
data class FreeUpItem(
    @SerialName("asset_id") val assetId: String,
    @SerialName("media_id") val mediaId: String,
    @SerialName("size_bytes") val sizeBytes: Long = 0
)

@Serializable
data class FreeUpPreview(val items: List<FreeUpItem> = emptyList(), @SerialName("total_bytes") val totalBytes: Long = 0, val count: Int = 0)

@Serializable
private data class Items<T>(val items: List<T> = emptyList())

@Serializable
private data class Freed(val freed: Int = 0)

@Serializable
private data class RunNow(val accepted: Boolean = false, val pending: Int = 0)

/** Phone backup: sources (MediaStore buckets), policy, status, `Respaldar ahora` and `Liberar espacio`. */
@Singleton
class BackupRepository @Inject constructor(private val api: BentoEndpoints, private val invalidations: Invalidations) {
    suspend fun status(): BackupStatus = api.backupStatus().decode(BackupStatus.serializer())

    suspend fun sources(): List<BackupSourceDto> = api.listBackupSources().decode(Items.serializer(BackupSourceDto.serializer())).items

    /** MediaStore buckets with counts; folder suggestions (desktop) are filtered out. */
    suspend fun buckets(): List<BucketSuggestion> = api.backupSuggestions().decode(Items.serializer(BucketSuggestion.serializer())).items
        .filter { it.kind == MEDIA_STORE && it.id != null }

    suspend fun addBucket(bucketId: String, label: String): BackupSourceDto = api.addBackupSource(
        BackupSourceCreateRequest(kind = MEDIA_STORE, bucketId = bucketId, label = label)
    ).decode(BackupSourceDto.serializer()).also { changed() }

    suspend fun setEnabled(sourceId: String, enabled: Boolean): BackupSourceDto =
        api.updateBackupSource(sourceId, BackupSourcePatchRequest(enabled = enabled)).decode(BackupSourceDto.serializer()).also {
            changed()
        }

    suspend fun policy(): BackupPolicy = api.getBackupPolicy().decode(BackupPolicy.serializer())

    suspend fun setPaused(paused: Boolean): BackupPolicy =
        api.updateBackupPolicy(BackupPolicyPatchRequest(paused = paused)).decode(BackupPolicy.serializer()).also { changed() }

    /** `Respaldar ahora`: lifts the Wi-Fi rule once for the current backlog; returns what is pending. */
    suspend fun runNow(): Int = api.backupRunNow().decode(RunNow.serializer()).pending.also { changed() }

    suspend fun freeUpPreview(): FreeUpPreview = api.freeUpSpacePreview().decode(FreeUpPreview.serializer())

    /** Reports the MediaStore ids the system actually deleted; assets and thumbnails stay. */
    suspend fun freeUpConfirm(mediaIds: List<String>): Int =
        api.freeUpSpaceConfirm(FreeUpSpaceConfirmRequest(mediaIds)).decode(Freed.serializer()).freed.also { changed() }

    private fun changed() = invalidations.invalidate(Topic.ACTIVITY, Topic.SETTINGS)

    private fun <T> JsonElement.decode(serializer: KSerializer<T>): T = BentoJson.decodeFromJsonElement(serializer, this)

    companion object {
        const val MEDIA_STORE = "media_store"
    }
}
