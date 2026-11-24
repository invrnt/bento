package dev.bento.engine

import android.content.Context
import androidx.tracing.trace
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import dev.bento.engine.bridge.BridgeSet
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull

/**
 * [EngineRuntime] over Chaquopy. Calls [ENGINE_MODULE], which is TEMPORARILY the shim in
 * `core/engine/src/main/python/bento_engine_shim/engine.py`; it delegates to agent 35's
 * `bento.interfaces.android.engine` when that module exists.
 */
class ChaquopyEngineRuntime(
    private val context: Context,
    private val bridges: BridgeSet,
    private val moduleName: String = ENGINE_MODULE
) : EngineRuntime {
    private val json = Json { ignoreUnknownKeys = true }
    private val module: PyObject by lazy { Python.getInstance().getModule(moduleName) }

    /** Warm-up stage timings reported by Python (`{stages_ms, python, real_engine}`). */
    @Volatile
    var warmUpReport: String? = null
        private set

    override fun warmUp() {
        if (warmUpReport != null) return
        trace("bento.engine.warmUp") {
            if (!Python.isStarted()) Python.start(AndroidPlatform(context))
            warmUpReport = module.callAttr("warm_up").toString()
        }
    }

    override fun configure(config: EngineConfig, wrappingKey: ByteArray, apiToken: String) {
        val py = Python.getInstance()
        val builtins = py.builtins
        val dict = builtins.callAttr("dict")
        fun put(target: PyObject, key: String, value: Any?) {
            target.callAttr("__setitem__", key, value)
        }
        put(dict, "data_dir", config.dataDir)
        put(dict, "no_backup_dir", config.noBackupDir)
        put(dict, "cache_dir", config.cacheDir)
        put(dict, "platform", "android")
        put(dict, "environment", config.environment)
        put(dict, "storage_backend", config.storageBackend)
        put(dict, "wrapping_key", builtins.callAttr("bytes", wrappingKey))
        put(dict, "api_token", apiToken)
        put(dict, "telegram_api_id", config.telegramApiId)
        put(dict, "telegram_api_hash", config.telegramApiHash)
        put(dict, "relay_url", config.relayUrl)
        put(dict, "site_url", config.siteUrl)
        put(dict, "app_version", config.appVersion)
        put(dict, "device_name_default", config.deviceNameDefault)
        val debug = builtins.callAttr("dict")
        config.debugOptions.forEach { (key, value) -> put(debug, key, value) }
        put(dict, "debug_options", debug)
        val bridgeDict = builtins.callAttr("dict")
        bridges.asMap().forEach { (key, bridge) -> put(bridgeDict, key, PyObject.fromJava(bridge)) }
        put(dict, "bridges", bridgeDict)
        trace("bento.engine.configure") { module.callAttr("configure", dict) }
    }

    override fun migrate(): MigrationResult = trace("bento.engine.migrate") {
        val result = toJson(module.callAttr("migrate"))
        MigrationResult(
            from = result["from"]?.jsonPrimitive?.contentOrNullSafe(),
            to = result["to"]?.jsonPrimitive?.contentOrNullSafe(),
            ran = result["ran"]?.jsonPrimitive?.booleanOrNull ?: false,
            ms = result["ms"]?.jsonPrimitive?.longOrNull ?: 0
        )
    }

    override fun startWorker(mode: WorkerMode) {
        trace("bento.engine.startWorker") { module.callAttr("start_worker", mode.wire) }
    }

    override fun startApi(): Int = trace("bento.engine.startApi") { module.callAttr("start_api").toInt() }

    override fun runWorkerUntil(deadlineEpochMs: Long, kinds: List<String>?): WorkerRunResult {
        val pyKinds = kinds?.let { list -> Python.getInstance().builtins.callAttr("list", list.toTypedArray()) }
        val result = toJson(module.callAttr("run_worker_until", deadlineEpochMs, pyKinds))
        return WorkerRunResult(
            ran = result["ran"]?.jsonPrimitive?.intOrNull ?: 0,
            remaining = result["remaining"]?.jsonPrimitive?.intOrNull ?: 0,
            nextEligibleAtEpochMs = result["next_eligible_at"]?.jsonPrimitive?.longOrNull,
            stoppedReason = runCatching {
                WorkerRunResult.StopReason.valueOf(result["stopped_reason"]?.jsonPrimitive?.content.orEmpty().uppercase())
            }.getOrDefault(WorkerRunResult.StopReason.ERROR)
        )
    }

    override fun stop(timeoutMs: Long) {
        if (!Python.isStarted()) return
        module.callAttr("stop", timeoutMs)
    }

    override fun onEvent(kind: String, payloadJson: String) {
        module.callAttr("on_event", kind, payloadJson)
    }

    override fun status(): EngineStatus {
        val result = toJson(module.callAttr("status"))
        return EngineStatus(
            apiPort = result["api_port"]?.jsonPrimitive?.intOrNull,
            worker = result["worker"]?.jsonPrimitive?.contentOrNullSafe() ?: "stopped",
            telegram = result["telegram"]?.jsonPrimitive?.contentOrNullSafe() ?: "disconnected",
            lastError = result["last_error"]?.jsonPrimitive?.contentOrNullSafe()
        )
    }

    private fun toJson(value: PyObject?): JsonObject {
        if (value == null) return JsonObject(emptyMap())
        val text = Python.getInstance().getModule("json").callAttr("dumps", value).toString()
        return json.parseToJsonElement(text).jsonObject
    }

    private fun kotlinx.serialization.json.JsonPrimitive.contentOrNullSafe(): String? = if (isString) {
        content
    } else {
        content.takeIf {
            it !=
                "null"
        }
    }

    companion object {
        /** TEMPORARY: switch to "bento.interfaces.android.engine" once agent 35 merges (and move `warm_up` there). */
        const val ENGINE_MODULE = "bento_engine_shim.engine"
    }
}
