package dev.bento.feature.settings

import android.net.Uri
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.emptyPreferences
import dev.bento.data.Invalidations
import dev.bento.data.SettingsRepository
import dev.bento.testing.FakeApiTransport
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow

/** In-memory DataStore (synchronous, so virtual-time tests stay deterministic). */
class FakePrefsStore : DataStore<Preferences> {
    private val state = MutableStateFlow(emptyPreferences())
    override val data: Flow<Preferences> = state

    override suspend fun updateData(transform: suspend (t: Preferences) -> Preferences): Preferences =
        transform(state.value).also { state.value = it }
}

/** Permissions and MediaStore of a fake phone; [access] can change between calls ("revoked later"). */
class FakePhoneMedia(var access: MediaAccess = MediaAccess.Denied, var location: Boolean = true, var visible: Int = 12) : PhoneMedia {
    val present = mutableSetOf("101", "102", "103")
    var transfers = 0
    var accessEvents = 0

    override fun access() = access

    override fun location() = location

    override fun visibleCount() = visible

    override fun newestIn(bucketId: String): Uri? = null

    override fun urisFor(mediaIds: List<String>): Map<String, Uri> =
        mediaIds.filter { it in present }.associateWith { Uri.parse("content://media/external/images/media/$it") }

    override fun deleted(mediaIds: List<String>): List<String> = mediaIds.filter { it !in present }

    override fun startTransfer() {
        transfers++
    }

    override fun accessChanged() {
        accessEvents++
    }
}

object SettingsFixtures {
    const val NOW = 1_795_000_000_000L

    const val BUCKETS = """{"items":[
        {"id":"b_cam","kind":"media_store","name":"Cámara","label":"Cámara","count":120,"suggested":true},
        {"id":"b_shots","kind":"media_store","name":"Capturas de pantalla","label":"Capturas de pantalla","count":40,"suggested":true},
        {"id":"b_wa","kind":"media_store","name":"WhatsApp Images","label":"WhatsApp Images","count":300,"suggested":false},
        {"path":"/home/x","label":"Desktop","kind":"folder"}]}"""

    fun source(id: String, bucket: String, enabled: Boolean = true, pending: Int = 0) =
        """{"id":"$id","kind":"media_store","bucket_id":"$bucket","label":"$bucket","enabled":$enabled,"files_pending":$pending}"""

    fun status(pending: Int = 0, waiting: String = "{}", last: String? = "2026-11-24T09:57:00+00:00") =
        """{"pending":$pending,"waiting":$waiting,"uploaded_today":0,"last_backup_at":${last?.let { "\"$it\"" } ?: "null"},
        "partial_access":false,"location_access":true}"""

    fun policy(paused: Boolean = false, effective: Boolean = paused) =
        """{"paused":$paused,"pause_on_battery":true,"on_battery":false,"effective_paused":$effective}"""

    fun values(revision: Int = 3, wifiOnly: Boolean = true, videosOnMetered: Boolean = false, charging: Boolean = false) = """{"revision":$revision,
        "values":{"backup_wifi_only":{"value":$wifiOnly,"source":"default","locked":false,"apply_mode":"live"},
        "backup_videos_on_metered":{"value":$videosOnMetered,"source":"default","locked":false,"apply_mode":"live"},
        "backup_only_charging":{"value":$charging,"source":"default","locked":false,"apply_mode":"live"},
        "ocr_provider":{"value":"mlkit","source":"default","locked":false,"apply_mode":"restart_worker"},
        "cache_max_gb":{"value":2,"source":"default","locked":false,"apply_mode":"restart_services"},
        "relay_url":{"value":"","source":"default","locked":false,"apply_mode":"restart_services"},
        "telegram_api_hash":{"configured":true,"source":"environment","locked":true,"apply_mode":"restart_services"},
        "storage_backend":{"value":"telegram","source":"default","locked":false,"apply_mode":"restart_services"}}}"""

    /** A phone with Cámara on (3 pending, waiting for Wi-Fi) unless the test reroutes. */
    fun api(): FakeApiTransport = FakeApiTransport().apply {
        on("GET /api/backup/suggestions") { BUCKETS }
        on("GET /api/backup/sources") { """{"items":[${source("s_cam", "b_cam", pending = 3)}]}""" }
        on("GET /api/backup/status") { status(pending = 3, waiting = """{"wifi":3,"charging":0}""") }
        on("GET /api/backup/policy") { policy() }
        on("GET /api/settings/values") { values() }
        on("PATCH /api/settings/values") { values() }
    }

    fun backup(api: FakeApiTransport) = BackupRepository(api.endpoints(), Invalidations())

    fun phoneSettings(api: FakeApiTransport) = PhoneSettingsRepository(SettingsRepository(api.endpoints(), Invalidations()))
}
