package dev.bento.feature.settings

import dev.bento.api.ApiErrorKind
import dev.bento.api.ApiException
import dev.bento.api.generated.SettingsPatchRequest
import dev.bento.data.SettingsRepository
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull

/**
 * The backend settings this phone edits (`domain/settings_registry.py`), read from `GET /api/settings/values`. Backup and
 * OCR policy keys apply live (the job eligibility reads them from the database); `cache_max_gb`, `ocr_provider` and
 * `relay_url` take effect on the next engine start.
 */
data class PhoneSettings(
    val revision: Long,
    val wifiOnly: Boolean = true,
    val videosOnMetered: Boolean = false,
    val onlyCharging: Boolean = false,
    val ocrEnabled: Boolean = true,
    val cacheMaxGb: Int = DEFAULT_CACHE_GB,
    val relayUrl: String = "",
    val storageBackend: String = "telegram"
) {
    companion object {
        const val WIFI_ONLY = "backup_wifi_only"
        const val VIDEOS_ON_METERED = "backup_videos_on_metered"
        const val ONLY_CHARGING = "backup_only_charging"
        const val OCR_PROVIDER = "ocr_provider"
        const val CACHE_MAX_GB = "cache_max_gb"
        const val RELAY_URL = "relay_url"
        const val STORAGE_BACKEND = "storage_backend"
        const val OCR_ON = "mlkit"
        const val OCR_OFF = "disabled"
        const val DEFAULT_CACHE_GB = 2
        val CACHE_CHOICES_GB = listOf(1, 2, 5, 10)

        fun parse(root: JsonObject): PhoneSettings {
            val values = (root["values"] as? JsonObject).orEmpty()
            fun raw(key: String): JsonPrimitive? = (values[key] as? JsonObject)?.get("value") as? JsonPrimitive
            fun bool(key: String, default: Boolean) = raw(key)?.booleanOrNull ?: default
            return PhoneSettings(
                revision = (root["revision"] as? JsonPrimitive)?.longOrNull ?: 0,
                wifiOnly = bool(WIFI_ONLY, true),
                videosOnMetered = bool(VIDEOS_ON_METERED, false),
                onlyCharging = bool(ONLY_CHARGING, false),
                ocrEnabled = raw(OCR_PROVIDER)?.content?.let { it != OCR_OFF } ?: true,
                cacheMaxGb = raw(CACHE_MAX_GB)?.doubleOrNull?.toInt() ?: DEFAULT_CACHE_GB,
                relayUrl = raw(RELAY_URL)?.content.orEmpty(),
                storageBackend = raw(STORAGE_BACKEND)?.content ?: "telegram"
            )
        }
    }
}

/** Reads and patches [PhoneSettings]; a concurrent edit (409) is retried once on the fresh revision. */
@Singleton
class PhoneSettingsRepository @Inject constructor(private val settings: SettingsRepository) {
    suspend fun load(): PhoneSettings = PhoneSettings.parse(settings.values())

    suspend fun set(key: String, value: JsonElement): PhoneSettings {
        var current = load()
        repeat(2) { attempt ->
            try {
                settings.patch(SettingsPatchRequest(revision = current.revision, values = JsonObject(mapOf(key to value))))
                return load()
            } catch (error: ApiException.Http) {
                if (error.kind != ApiErrorKind.CONFLICT || attempt == 1) throw error
                current = load()
            }
        }
        return load()
    }

    suspend fun set(key: String, value: Boolean) = set(key, JsonPrimitive(value))

    suspend fun set(key: String, value: Int) = set(key, JsonPrimitive(value))

    suspend fun set(key: String, value: String) = set(key, JsonPrimitive(value))
}
