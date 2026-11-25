package dev.bento.engine

/**
 * The non-secret part of `bento.interfaces.android.engine.configure(config)` (api/android-endpoints.md §1).
 * Pure so it is JVM tested; the API token, wrapping key and bridges are added by [ChaquopyEngineRuntime].
 * Debug options become the engine's own keys: `fake_telegram_dir`/`fake_telegram_url` and the debug-only
 * `settings` overrides it accepts.
 */
object EngineConfigWire {
    const val PLATFORM = "android"

    fun values(config: EngineConfig): Map<String, Any?> {
        val debug = config.debugOptions
        return linkedMapOf(
            "data_dir" to config.dataDir,
            "no_backup_dir" to config.noBackupDir,
            "cache_dir" to config.cacheDir,
            "platform" to PLATFORM,
            "environment" to config.environment,
            "storage_backend" to config.storageBackend,
            "telegram_api_id" to config.telegramApiId,
            "telegram_api_hash" to config.telegramApiHash,
            "relay_url" to config.relayUrl,
            "site_url" to config.siteUrl,
            "app_version" to config.appVersion,
            "device_name_default" to config.deviceNameDefault,
            "migrations_dir" to config.migrationsDir,
            "fake_telegram_dir" to debug["fake_cloud_dir"]?.takeIf { it.isNotBlank() },
            "fake_telegram_url" to debug["fake_telegram_url"]?.takeIf { it.isNotBlank() }
        )
    }

    /** `config["settings"]`: only the overrides the engine allows (`_ALLOWED_OVERRIDES`). */
    fun settings(config: EngineConfig): Map<String, String> {
        val debug = config.debugOptions
        return buildMap {
            debug["part_size_mb"]?.takeIf { it.isNotBlank() }?.let { put("BENTO_TELEGRAM_PART_SIZE_MB", it) }
            if (debug["manual_login"] == "true") put("BENTO_FAKE_TELEGRAM_MANUAL_LOGIN", "1")
        }
    }
}
