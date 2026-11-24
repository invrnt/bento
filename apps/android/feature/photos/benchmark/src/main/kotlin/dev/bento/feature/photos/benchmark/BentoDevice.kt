package dev.bento.feature.photos.benchmark

import android.os.ParcelFileDescriptor
import androidx.test.platform.app.InstrumentationRegistry
import java.util.concurrent.TimeUnit
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

/**
 * Drives the debug app from this separate test process (same approach as smoke/AppDriver): shell commands for the
 * lifecycle, the debug-only `no_backup/dev-endpoint.json` for the loopback port and token, and the real API for
 * seeding and assertions. The fake Telegram cloud signs in automatically (debug builds).
 */
object BentoDevice {
    const val PACKAGE = "dev.bento.app"

    data class Endpoint(val port: Int, val token: String, val pid: Int)

    private val json = Json { ignoreUnknownKeys = true }
    val client: OkHttpClient = OkHttpClient.Builder().readTimeout(2, TimeUnit.MINUTES).writeTimeout(2, TimeUnit.MINUTES).build()

    fun shell(command: String): String {
        val pfd = InstrumentationRegistry.getInstrumentation().uiAutomation.executeShellCommand(command)
        return ParcelFileDescriptor.AutoCloseInputStream(pfd).bufferedReader().use { it.readText() }
    }

    fun launch() {
        shell("am start -W -n $PACKAGE/.MainActivity")
    }

    fun forceStop() {
        shell("am force-stop $PACKAGE")
    }

    /** The engine's endpoint; pass [previousPid] after a relaunch (each start picks a new loopback port). */
    fun awaitEndpoint(timeoutMs: Long = 180_000, previousPid: Int? = null): Endpoint {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val text = shell("run-as $PACKAGE cat no_backup/dev-endpoint.json").trim()
            if (text.startsWith("{")) {
                val o = json.parseToJsonElement(text).jsonObject
                val endpoint = Endpoint(o["port"]!!.jsonPrimitive.int, o["token"]!!.jsonPrimitive.content, o["pid"]!!.jsonPrimitive.int)
                if (endpoint.pid != previousPid) return endpoint
            }
            Thread.sleep(200)
        }
        error("engine endpoint not published within $timeoutMs ms")
    }

    private fun request(endpoint: Endpoint, path: String): Request.Builder =
        Request.Builder().url("http://127.0.0.1:${endpoint.port}$path").header("Authorization", "Bearer ${endpoint.token}")

    fun call(endpoint: Endpoint, method: String, path: String, body: String? = null): JsonObject {
        val requestBody = body?.toRequestBody("application/json".toMediaType()) ?: if (method == "POST") ByteArray(0).toRequestBody(null) else null
        client.newCall(request(endpoint, path).method(method, requestBody).build()).execute().use { response ->
            check(response.isSuccessful) { "$method $path -> ${response.code}" }
            return json.parseToJsonElement(response.body.string()).jsonObject
        }
    }

    fun upload(endpoint: Endpoint, name: String, mime: String, bytes: ByteArray): JsonObject {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", name, bytes.toRequestBody(mime.toMediaType()))
            .addFormDataPart("mode", "photos")
            .build()
        client.newCall(request(endpoint, "/api/assets/upload").post(body).build()).execute().use { response ->
            check(response.isSuccessful) { "upload $name -> ${response.code}" }
            return json.parseToJsonElement(response.body.string()).jsonObject
        }
    }

    /** Fake cloud (debug): QR login auto-approves; create the vault and confirm the kit. */
    fun signInWithFakeCloud(endpoint: Endpoint) {
        fun state() = call(endpoint, "GET", "/api/vault")["state"]!!.jsonPrimitive.content
        if (state() == "ready") return
        if (call(endpoint, "GET", "/api/account")["step"]!!.jsonPrimitive.content != "authorized") {
            call(endpoint, "POST", "/api/account/login/qr")
            val deadline = System.currentTimeMillis() + 30_000
            while (call(endpoint, "GET", "/api/account")["step"]!!.jsonPrimitive.content != "authorized") {
                check(System.currentTimeMillis() < deadline) { "fake login did not authorize" }
                Thread.sleep(200)
            }
        }
        if (state() == "no_vault") {
            val code = call(endpoint, "POST", "/api/vault")["recovery_code"]!!.jsonPrimitive.content
            call(endpoint, "POST", "/api/vault/recovery-code/confirm", "{\"last_group\":\"${code.substringAfterLast('-')}\"}")
        }
    }

    /** Launches the app and returns a signed-in endpoint. */
    fun ready(): Endpoint {
        launch()
        val endpoint = awaitEndpoint()
        signInWithFakeCloud(endpoint)
        return endpoint
    }
}
