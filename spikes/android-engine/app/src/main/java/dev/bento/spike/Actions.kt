package dev.bento.spike

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Shader
import android.os.SystemClock
import android.util.Log
import com.chaquo.python.Python
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File

/** Spike actions; each returns a JSON result that is logged as `RESULT <action> <json>` and appended to results.jsonl. */
object Actions {
    val names = listOf("ready", "health", "thumbnail", "fts5", "memory", "fake_login_vault",
        "upload_big", "upload_then_kill", "resume_check", "download_big", "aes_bench", "start_host", "host_seed", "pair_guest")

    fun run(action: String, args: JSONObject): JSONObject {
        val started = SystemClock.uptimeMillis()
        val result = try {
            when (action) {
                "ready" -> Engine.ensureStarted(args)
                "health" -> health()
                "thumbnail" -> thumbnail()
                "start_host" -> startHost(args)
                else -> python(action, args)
            }.put("ok", true)
        } catch (t: Throwable) {
            Log.e(Engine.TAG, "action $action failed", t)
            JSONObject().put("ok", false).put("error", t.toString().take(4000))
        }
        result.put("action_ms", SystemClock.uptimeMillis() - started)
        val line = "RESULT $action $result"
        Log.i(Engine.TAG, line)
        File(Engine.appContext.filesDir, "results.jsonl").appendText(JSONObject().put("action", action).put("result", result).toString() + "\n")
        return result
    }

    private fun python(action: String, args: JSONObject): JSONObject {
        if (action != "aes_bench" && action != "fts5") Engine.ensureStarted()
        val payload = JSONObject(args.toString()).put("port", Engine.port).put("token", Engine.apiToken)
        val out = Python.getInstance().getModule("bento_spike.scenarios").callAttr("run", action, payload.toString())
        return JSONObject(out.toString())
    }

    private val hostConnection = object : android.content.ServiceConnection {
        override fun onServiceConnected(name: android.content.ComponentName?, service: android.os.IBinder?) {}
        override fun onServiceDisconnected(name: android.content.ComponentName?) {}
    }

    private fun startHost(args: JSONObject): JSONObject {
        val file = File(Engine.appContext.filesDir, "host.json")
        file.delete()
        val intent = android.content.Intent(Engine.appContext, HostService::class.java).putExtra("options", args.toString())
        Engine.appContext.startService(intent)
        Engine.appContext.bindService(intent, hostConnection,
            android.content.Context.BIND_AUTO_CREATE or android.content.Context.BIND_IMPORTANT)
        val t0 = SystemClock.uptimeMillis()
        while (!file.exists() && SystemClock.uptimeMillis() - t0 < 180_000) Thread.sleep(200)
        val state = JSONObject(file.readText())
        state.remove("token")
        return state.put("wait_ms", SystemClock.uptimeMillis() - t0)
    }

    private fun health(): JSONObject {
        Engine.ensureStarted()
        return JSONObject()
            .put("with_token", Engine.get("/api/health"))
            .put("without_token", Engine.get("/api/health", auth = false))
    }

    /** Kotlin uploads a generated JPEG through OkHttp; the worker's thumbnail job must go through the MediaTools bridge. */
    private fun thumbnail(): JSONObject {
        Engine.ensureStarted()
        val bitmap = Bitmap.createBitmap(4000, 3000, Bitmap.Config.ARGB_8888)
        Canvas(bitmap).drawPaint(Paint().apply {
            shader = LinearGradient(0f, 0f, 4000f, 3000f, Color.MAGENTA, Color.CYAN, Shader.TileMode.CLAMP)
        })
        val jpeg = ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.JPEG, 90, it) }.toByteArray()
        bitmap.recycle()
        val callsBefore = MediaTools.calls
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("mode", "drive")
            .addFormDataPart("file", "spike-${System.currentTimeMillis()}.jpg", jpeg.toRequestBody("image/jpeg".toMediaType()))
            .build()
        val request = Request.Builder().url("http://127.0.0.1:${Engine.port}/api/assets/upload")
            .header("Authorization", "Bearer ${Engine.apiToken}").post(body).build()
        val asset = Engine.http.newCall(request).execute().use { JSONObject(it.body!!.string()) }
        val assetId = asset.getString("id")
        val t0 = SystemClock.uptimeMillis()
        var job: JSONObject? = null
        while (SystemClock.uptimeMillis() - t0 < 60_000) {
            val jobs = JSONObject(Engine.get("/api/jobs?limit=50").getString("body")).getJSONArray("items")
            for (i in 0 until jobs.length()) {
                val j = jobs.getJSONObject(i)
                if (j.optString("asset_id") == assetId && j.optString("type") == "thumbnail" &&
                    j.optString("status") in setOf("succeeded", "failed")) job = j
            }
            if (job != null) break
            Thread.sleep(200)
        }
        val thumb = Engine.http.newCall(
            Request.Builder().url("http://127.0.0.1:${Engine.port}/api/assets/$assetId/thumbnail")
                .header("Authorization", "Bearer ${Engine.apiToken}").build()
        ).execute().use { JSONObject().put("status", it.code).put("bytes", it.body?.bytes()?.size ?: 0).put("type", it.header("content-type")) }
        return JSONObject()
            .put("asset_id", assetId)
            .put("upload_bytes", jpeg.size)
            .put("job", job)
            .put("job_wait_ms", SystemClock.uptimeMillis() - t0)
            .put("media_tools_calls", MediaTools.calls - callsBefore)
            .put("thumbnail", thumb)
    }
}
