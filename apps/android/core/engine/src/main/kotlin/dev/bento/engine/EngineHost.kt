package dev.bento.engine

import android.content.Context
import android.content.res.AssetManager
import dev.bento.engine.bridge.AndroidDeviceConditions
import dev.bento.engine.bridge.AndroidMediaStoreSource
import dev.bento.engine.bridge.MediaStoreMapping
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
        val tools = build.debugTools || BuildConfig.ENGINE_BENCHMARK_TOOLS
        val debug = if (tools) DebugOptions.read(context) else emptyMap()
        return EngineConfig(
            // Catalog, key store and logs are excluded from backup (architecture/android-runtime.md §10).
            dataDir = File(context.noBackupFilesDir, "bento").absolutePath,
            noBackupDir = context.noBackupFilesDir.absolutePath,
            cacheDir = context.cacheDir.absolutePath,
            environment = if (tools) "debug" else "production",
            storageBackend = if (tools) debug["storage_backend"] ?: "fake" else "telegram",
            telegramApiId = build.telegramApiId?.takeIf { it.isNotBlank() },
            telegramApiHash = build.telegramApiHash?.takeIf { it.isNotBlank() },
            relayUrl = DebugOptions.relayUrl(debug, build.relayUrl),
            siteUrl = build.siteUrl?.takeIf { it.isNotBlank() },
            appVersion = build.appVersion,
            deviceNameDefault = android.os.Build.MODEL ?: "Android",
            migrationsDir = MigrationAssets.extract(context).absolutePath,
            debugOptions = debug
        )
    }
}

/**
 * `apps/api/migrations` ships as APK assets under [ASSET_ROOT] (core/engine build); alembic reads real files, so they
 * are copied to `noBackupFilesDir/migrations/<install stamp>` once per installed APK and older copies are removed.
 */
object MigrationAssets {
    const val ASSET_ROOT = "bento-migrations"
    private const val COMPLETE = ".complete"

    fun extract(context: Context): File {
        val root = File(context.noBackupFilesDir, "migrations")
        val target = File(root, installStamp(context))
        if (File(target, COMPLETE).isFile) return target
        root.listFiles()?.forEach { it.deleteRecursively() }
        copy(context.assets, ASSET_ROOT, target)
        File(target, COMPLETE).writeText("")
        return target
    }

    private fun installStamp(context: Context): String {
        val manager = context.packageManager
        val info = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
            manager.getPackageInfo(context.packageName, android.content.pm.PackageManager.PackageInfoFlags.of(0))
        } else {
            @Suppress("DEPRECATION")
            manager.getPackageInfo(context.packageName, 0)
        }
        return info.lastUpdateTime.toString()
    }

    private fun copy(assets: AssetManager, path: String, destination: File) {
        val children = assets.list(path).orEmpty()
        if (children.isEmpty()) {
            destination.parentFile?.mkdirs()
            assets.open(path).use { input -> destination.outputStream().use(input::copyTo) }
        } else {
            destination.mkdirs()
            children.forEach { copy(assets, "$path/$it", File(destination, it)) }
        }
    }
}

/**
 * Debug builds only. `filesDir/dev-options.json` (written by tests with `run-as`) tunes the fake backend and can
 * point pairing at the e2e harness's relay double (`relay_url`), so any debug APK runs the multi-device journeys;
 * `noBackupFilesDir/dev-endpoint.json` exposes port + token to the `:smoke` instrumentation, which runs in
 * another process. Neither file exists in release builds.
 *
 * The non-debuggable benchmark variants (`ENGINE_BENCHMARK_TOOLS`, never shipped) have no `run-as`: they publish the
 * endpoint under the app-specific external files dir, which the shell (Macrobenchmark) can read.
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

    /** `relay_url` from the debug options wins over the build's `-PbentoRelayUrl`; blank means none. */
    fun relayUrl(debug: Map<String, String>, built: String?): String? =
        debug["relay_url"]?.takeIf { it.isNotBlank() } ?: built?.takeIf { it.isNotBlank() }

    fun publishEndpoint(context: Context, ready: EngineState.Ready) {
        val payload = buildJsonObject {
            put("port", ready.port)
            put("token", ready.token)
            put("pid", android.os.Process.myPid())
        }
        File(endpointDir(context), ENDPOINT).writeText(payload.toString())
    }

    fun clearEndpoint(context: Context) {
        File(endpointDir(context), ENDPOINT).delete()
    }

    private fun endpointDir(context: Context): File =
        if (BuildConfig.ENGINE_BENCHMARK_TOOLS) context.getExternalFilesDir(null) ?: context.noBackupFilesDir else context.noBackupFilesDir
}

/** Starts/stops the MediaStore and conditions observers with the engine and forwards their events. */
class PlatformObservers(
    private val mediaStore: AndroidMediaStoreSource,
    private val conditions: AndroidDeviceConditions,
    private val engine: () -> BentoEngine
) : EngineLifecycleListener {
    override fun onEngineRunning() {
        mediaStore.observe { uri ->
            // The engine rescans only the sources of the changed bucket; an unknown bucket rescans every source.
            val bucket = uri?.let(mediaStore::bucketIdFor)
            engine().onEvent("media_changed", MediaStoreMapping.changedPayload(bucket))
        }
        conditions.observe { snapshot -> engine().onEvent("conditions", snapshot) }
    }

    override fun onEngineStopping() {
        mediaStore.stopObserving()
        conditions.stopObserving()
    }
}
