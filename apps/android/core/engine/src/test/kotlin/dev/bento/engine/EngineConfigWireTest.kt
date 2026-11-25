package dev.bento.engine

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class EngineConfigWireTest {
    private fun config(debug: Map<String, String> = emptyMap()) = EngineConfig(
        dataDir = "/data/nb/bento",
        noBackupDir = "/data/nb",
        cacheDir = "/data/cache",
        environment = "debug",
        storageBackend = "fake",
        telegramApiId = null,
        telegramApiHash = null,
        relayUrl = null,
        siteUrl = null,
        appVersion = "0.1.0",
        deviceNameDefault = "Pixel",
        migrationsDir = "/data/nb/migrations/1",
        debugOptions = debug
    )

    @Test
    fun `values use only keys the backend engine accepts`() {
        val known = setOf(
            "data_dir", "no_backup_dir", "cache_dir", "platform", "environment", "storage_backend", "telegram_api_id",
            "telegram_api_hash", "relay_url", "site_url", "app_version", "device_name_default", "migrations_dir",
            "fake_telegram_dir", "fake_telegram_url"
        )
        val values = EngineConfigWire.values(config())
        assertTrue(known.containsAll(values.keys))
        assertEquals("android", values["platform"])
        assertEquals("/data/nb/migrations/1", values["migrations_dir"])
        assertNull(values["fake_telegram_dir"])
    }

    @Test
    fun `debug options become engine keys and allowed setting overrides`() {
        val wire = config(
            mapOf("fake_cloud_dir" to "/data/files/fake-cloud", "part_size_mb" to "64", "manual_login" to "true", "other" to "x")
        )
        assertEquals("/data/files/fake-cloud", EngineConfigWire.values(wire)["fake_telegram_dir"])
        assertEquals(
            mapOf("BENTO_TELEGRAM_PART_SIZE_MB" to "64", "BENTO_FAKE_TELEGRAM_MANUAL_LOGIN" to "1"),
            EngineConfigWire.settings(wire)
        )
        assertEquals(emptyMap<String, String>(), EngineConfigWire.settings(config()))
    }

    @Test
    fun `a debug relay_url option overrides the built relay`() {
        assertEquals("ws://127.0.0.1:8788", DebugOptions.relayUrl(mapOf("relay_url" to "ws://127.0.0.1:8788"), "wss://relay.example"))
        assertEquals("wss://relay.example", DebugOptions.relayUrl(mapOf("relay_url" to " "), "wss://relay.example"))
        assertNull(DebugOptions.relayUrl(emptyMap(), ""))
    }
}
