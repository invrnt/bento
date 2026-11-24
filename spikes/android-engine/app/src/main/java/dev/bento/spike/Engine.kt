package dev.bento.spike

import android.content.Context
import android.os.Process
import android.os.SystemClock
import android.util.Base64
import android.util.Log
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.security.SecureRandom
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Throwaway engine holder: interpreter warm-up, `bento_spike.engine.start`, and a token-bound OkHttp client. */
object Engine {
    const val TAG = "BentoSpike"

    private val interpreterReady = CountDownLatch(1)
    private val timings = JSONObject()
    @Volatile private var warmUpError: Throwable? = null
    @Volatile var port: Int = 0
        private set
    @Volatile private var started = false
    lateinit var appContext: Context
        private set

    /** 32 random bytes per process start, kept only in memory and passed to Python in-process. */
    val apiToken: String by lazy { randomUrlToken(32) }

    val http: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .readTimeout(10, TimeUnit.MINUTES)
            .writeTimeout(10, TimeUnit.MINUTES)
            .build()
    }

    fun baselineMode(context: Context): Boolean = File(context.filesDir, "no-python").exists()

    fun warmUp(context: Context) {
        appContext = context.applicationContext
        val processStart = Process.getStartUptimeMillis()
        timings.put("app_on_create_ms", SystemClock.uptimeMillis() - processStart)
        if (baselineMode(context)) {
            Log.i(TAG, "baseline mode: Python not started")
            interpreterReady.countDown()
            return
        }
        Thread({
            try {
                val t0 = SystemClock.uptimeMillis()
                if (!Python.isStarted()) Python.start(AndroidPlatform(appContext))
                val t1 = SystemClock.uptimeMillis()
                val warm = Python.getInstance().getModule("bento_spike.engine").callAttr("warm_up").toString()
                val t2 = SystemClock.uptimeMillis()
                timings.put("python_start_ms", t1 - t0)
                timings.put("warm_up_imports_ms", t2 - t1)
                timings.put("interpreter_ready_since_process_start_ms", t2 - processStart)
                timings.put("warm_up", JSONObject(warm))
            } catch (t: Throwable) {
                warmUpError = t
                Log.e(TAG, "warm-up failed", t)
            } finally {
                interpreterReady.countDown()
            }
        }, "bento-warm-up").start()
    }

    /** Blocking: interpreter → configure → migrations → worker → API → `/api/health` 200 via OkHttp. */
    @Synchronized
    fun ensureStarted(options: JSONObject = JSONObject()): JSONObject {
        if (started) return JSONObject().put("port", port).put("already_started", true)
        val processStart = Process.getStartUptimeMillis()
        interpreterReady.await()
        warmUpError?.let { throw it }
        val dataRoot = File(appContext.noBackupFilesDir, "bento")
        val config = JSONObject()
            .put("data_dir", File(dataRoot, "data").absolutePath)
            .put("fake_cloud_dir", options.optString("fake_cloud_dir", File(appContext.filesDir, "fake-cloud").absolutePath))
            .put("api_token", apiToken)
            .put("wrapping_key", wrappingKey())
            .put("options", options)
        val t0 = SystemClock.uptimeMillis()
        val result = JSONObject(
            Python.getInstance().getModule("bento_spike.engine").callAttr("start", config.toString()).toString()
        )
        val t1 = SystemClock.uptimeMillis()
        port = result.getInt("port")
        val health = get("/api/health")
        val t2 = SystemClock.uptimeMillis()
        started = true
        return JSONObject()
            .put("port", port)
            .put("kotlin_timings", JSONObject(timings.toString()))
            .put("engine_start_call_ms", t1 - t0)
            .put("first_health_ms", t2 - t1)
            .put("engine_ready_since_process_start_ms", t2 - processStart)
            .put("python", result)
            .put("health", health)
    }

    fun get(path: String, auth: Boolean = true): JSONObject {
        val builder = Request.Builder().url("http://127.0.0.1:$port$path")
        if (auth) builder.header("Authorization", "Bearer $apiToken")
        http.newCall(builder.build()).execute().use { response ->
            val body = response.body?.string().orEmpty()
            return JSONObject().put("status", response.code).put("body", body.take(2000))
        }
    }

    /**
     * Spike stand-in for the Keystore-wrapped `wrapping.bin` (Stage 20 owns the real KeyWrapping bridge):
     * a random 32-byte key kept in app-private noBackup storage, passed to Python in memory only.
     */
    private fun wrappingKey(): String {
        val file = File(appContext.noBackupFilesDir, "spike-wrapping.key")
        if (!file.exists()) file.writeText(randomUrlToken(32))
        return file.readText().trim()
    }

    private fun randomUrlToken(bytes: Int): String {
        val raw = ByteArray(bytes).also { SecureRandom().nextBytes(it) }
        return Base64.encodeToString(raw, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
    }
}
