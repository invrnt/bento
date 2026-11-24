package dev.bento.benchmark.common

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
 * Drives the app from the test process: shell commands for the lifecycle, the engine's published endpoint for the
 * loopback port and token, and the real API (fake cloud) for sign-in and seeding. Works against the debug build
 * (`run-as`, `noBackupFilesDir`) and the non-debuggable `benchmarkRelease`/`nonMinifiedRelease` builds (endpoint under
 * the app-specific external files dir, `ENGINE_BENCHMARK_TOOLS`).
 */
object BentoDevice {
    const val PACKAGE = "dev.bento.app"
    private const val ENDPOINT_FILE = "dev-endpoint.json"
    private const val EXTERNAL_ENDPOINT = "/sdcard/Android/data/$PACKAGE/files/$ENDPOINT_FILE"

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

    /** Spanish UI (the default locale of the product) so journeys can find labels by text. */
    fun spanish() {
        shell("cmd locale set-app-locales $PACKAGE --locales es-ES")
    }

    private fun readEndpoint(): String {
        val external = shell("cat $EXTERNAL_ENDPOINT").trim()
        if (external.startsWith("{")) return external
        return shell("run-as $PACKAGE cat no_backup/$ENDPOINT_FILE").trim()
    }

    /** The engine's endpoint; pass [previousPid] after a relaunch (each start picks a new loopback port). */
    fun awaitEndpoint(timeoutMs: Long = 180_000, previousPid: Int? = null): Endpoint {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val text = readEndpoint()
            if (text.startsWith("{")) {
                val o = json.parseToJsonElement(text).jsonObject
                val endpoint = Endpoint(o["port"]!!.jsonPrimitive.int, o["token"]!!.jsonPrimitive.content, o["pid"]!!.jsonPrimitive.int)
                // A stale file from a killed process names a dead pid.
                if (endpoint.pid != previousPid && isAlive(endpoint.pid)) return endpoint
            }
            Thread.sleep(200)
        }
        error("engine endpoint not published within $timeoutMs ms")
    }

    private fun isAlive(pid: Int): Boolean = shell("pidof $PACKAGE").trim().split(" ").contains(pid.toString())

    private fun request(endpoint: Endpoint, path: String): Request.Builder =
        Request.Builder().url("http://127.0.0.1:${endpoint.port}$path").header("Authorization", "Bearer ${endpoint.token}")

    fun call(endpoint: Endpoint, method: String, path: String, body: String? = null): JsonObject {
        val requestBody = body?.toRequestBody("application/json".toMediaType()) ?: if (method == "POST") ByteArray(0).toRequestBody(null) else null
        client.newCall(request(endpoint, path).method(method, requestBody).build()).execute().use { response ->
            check(response.isSuccessful) { "$method $path -> ${response.code}" }
            return json.parseToJsonElement(response.body.string()).jsonObject
        }
    }

    fun upload(endpoint: Endpoint, name: String, mime: String, bytes: ByteArray, mode: String = "photos", folderId: String? = null): JsonObject {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", name, bytes.toRequestBody(mime.toMediaType()))
            .addFormDataPart("mode", mode)
            .apply { if (folderId != null) addFormDataPart("folder_id", folderId) }
            .build()
        client.newCall(request(endpoint, "/api/assets/upload").post(body).build()).execute().use { response ->
            check(response.isSuccessful) { "upload $name -> ${response.code}" }
            return json.parseToJsonElement(response.body.string()).jsonObject
        }
    }

    /** Fake cloud: QR login auto-approves; create the vault and confirm the kit. */
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

    /** Total PSS of the app process in KB (`dumpsys meminfo`), or null when it is not running. */
    fun totalPssKb(): Long? {
        val out = shell("dumpsys meminfo $PACKAGE")
        return Regex("TOTAL PSS:\\s+(\\d+)").find(out)?.groupValues?.get(1)?.toLong()
            ?: Regex("(?m)^\\s+TOTAL\\s+(\\d+)").find(out)?.groupValues?.get(1)?.toLong()
    }

    /** Instrumentation argument (`-e name value`) or [default]. */
    fun argument(name: String, default: String): String =
        InstrumentationRegistry.getArguments().getString(name) ?: default
}
