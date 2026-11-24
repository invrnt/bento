package dev.bento.engine

import android.content.Context
import dev.bento.engine.bridge.AndroidDeviceConditions
import dev.bento.engine.bridge.AndroidMediaStoreSource
import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put

/** Values the app module supplies (version, Telegram app credentials, relay/site URLs). */
data class EngineBuildInfo(
    val appVersion: String,
    val debugTools: Boolean,
    val telegramApiId: String?,
    val telegramApiHash: String?,
    val relayUrl: String?,
    val siteUrl: String?
)

/** Builds [EngineConfig] from the storage layout of architecture/android-runtime.md §10. */
class EngineConfigFactory(private val context: Context, private val build: EngineBuildInfo) {
    fun create(): EngineConfig {
        val debug = if (build.debugTools) DebugOptions.read(context) else emptyMap()
        return EngineConfig(
            dataDir = File(context.filesDir, "bento").absolutePath,
            noBackupDir = context.noBackupFilesDir.absolutePath,
            cacheDir = context.cacheDir.absolutePath,
            environment = if (build.debugTools) "debug" else "production",
            storageBackend = if (build.debugTools) debug["storage_backend"] ?: "fake" else "telegram",
            telegramApiId = build.telegramApiId?.takeIf { it.isNotBlank() },
            telegramApiHash = build.telegramApiHash?.takeIf { it.isNotBlank() },
            relayUrl = build.relayUrl?.takeIf { it.isNotBlank() },
            siteUrl = build.siteUrl?.takeIf { it.isNotBlank() },
            appVersion = build.appVersion,
            deviceNameDefault = android.os.Build.MODEL ?: "Android",
            debugOptions = debug
        )
    }
}

/**
 * Debug builds only. `filesDir/dev-options.json` (written by tests with `run-as`) tunes the fake backend;
 * `noBackupFilesDir/dev-endpoint.json` exposes port + token to the `:smoke` instrumentation, which runs in
 * another process. Neither file exists in release builds.
 */
object DebugOptions {
    private const val OPTIONS = "dev-options.json"
    private const val ENDPOINT = "dev-endpoint.json"

    fun read(context: Context): Map<String, String> {
        val file = File(context.filesDir, OPTIONS)
        val options = runCatching { Json.parseToJsonElement(file.readText()).jsonObject }.getOrNull()
            ?.mapValues { (it.value as? JsonPrimitive)?.content.orEmpty() }
            .orEmpty()
        return mapOf("fake_cloud_dir" to File(context.filesDir, "fake-cloud").absolutePath) + options
    }

    fun publishEndpoint(context: Context, ready: EngineState.Ready) {
        val payload = buildJsonObject {
            put("port", ready.port)
            put("token", ready.token)
            put("pid", android.os.Process.myPid())
        }
        File(context.noBackupFilesDir, ENDPOINT).writeText(payload.toString())
    }

    fun clearEndpoint(context: Context) {
        File(context.noBackupFilesDir, ENDPOINT).delete()
    }
}

/** Starts/stops the MediaStore and conditions observers with the engine and forwards their events. */
class PlatformObservers(
    private val mediaStore: AndroidMediaStoreSource,
    private val conditions: AndroidDeviceConditions,
    private val engine: () -> BentoEngine
) : EngineLifecycleListener {
    override fun onEngineRunning() {
        mediaStore.observe { uri ->
            engine().onEvent("media_changed", buildJsonObject { put("uri", uri) }.toString())
        }
        conditions.observe { snapshot -> engine().onEvent("conditions", snapshot) }
    }

    override fun onEngineStopping() {
        mediaStore.stopObserving()
        conditions.stopObserving()
    }
}
