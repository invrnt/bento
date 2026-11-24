package dev.bento.smoke

import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okio.BufferedSink
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/**
 * Journey "process killed mid-upload resumes" (product/android.md §11): upload 160 MB (3 parts of 64 MB on
 * the fake cloud), SIGKILL the app while `remote_upload` runs, relaunch, and expect the job to finish with
 * the original bytes intact. The worker requeues the abandoned job and upload_sessions skips committed parts.
 */
@RunWith(AndroidJUnit4::class)
class ProcessDeathUploadTest {
    private val client = OkHttpClient.Builder().readTimeout(10, TimeUnit.MINUTES).writeTimeout(10, TimeUnit.MINUTES).build()
    private val size = 160L * 1024 * 1024

    private fun byteAt(i: Long): Int = ((i * 31 + i / 4096) % 251).toInt()

    private fun request(endpoint: AppDriver.Endpoint, path: String): Request.Builder =
        Request.Builder().url("http://127.0.0.1:${endpoint.port}$path").header("Authorization", "Bearer ${endpoint.token}")

    private fun jobsFor(endpoint: AppDriver.Endpoint, assetId: String): List<JsonObject> {
        client.newCall(request(endpoint, "/api/jobs?limit=200").build()).execute().use { response ->
            val root = Json.parseToJsonElement(response.body.string()).jsonObject
            return root["items"]!!.jsonArray.map { it.jsonObject }
                .filter { it["asset_id"]?.jsonPrimitive?.contentOrNull == assetId && it["type"]!!.jsonPrimitive.content == "remote_upload" }
        }
    }

    @Test
    fun uploadResumesAfterSigkill() {
        AppDriver.forceStop()
        AppDriver.launch() // creates the app data dirs before writing options
        AppDriver.awaitEndpoint()
        AppDriver.writeDevOptions("{\"part_size_mb\":\"64\"}")
        AppDriver.forceStop()
        AppDriver.launch()
        val first = AppDriver.awaitEndpoint()

        val expected = MessageDigest.getInstance("SHA-256")
        val body = object : RequestBody() {
            override fun contentType() = "application/octet-stream".toMediaType()

            override fun contentLength() = size

            override fun writeTo(sink: BufferedSink) {
                val chunk = ByteArray(1 shl 20)
                var offset = 0L
                while (offset < size) {
                    for (j in chunk.indices) chunk[j] = byteAt(offset + j).toByte()
                    sink.write(chunk)
                    expected.update(chunk)
                    offset += chunk.size
                }
            }
        }
        val multipart = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", "kill-${System.nanoTime()}.bin", body).build()
        val assetId = client.newCall(request(first, "/api/assets/upload").post(multipart).build()).execute().use { response ->
            assertEquals(200, response.code)
            Json.parseToJsonElement(response.body.string()).jsonObject["id"]!!.jsonPrimitive.content
        }
        val digest = expected.digest().joinToString("") { "%02x".format(it) }

        // Kill while the upload job runs.
        val runningDeadline = System.currentTimeMillis() + 120_000
        while (jobsFor(first, assetId).none { it["status"]!!.jsonPrimitive.content == "running" }) {
            check(System.currentTimeMillis() < runningDeadline) { "remote_upload never started" }
            Thread.sleep(100)
        }
        Thread.sleep(1_500)
        val statusAtKill = jobsFor(first, assetId).single()["status"]!!.jsonPrimitive.content
        AppDriver.kill(first.pid)

        AppDriver.launch()
        val second = AppDriver.awaitEndpoint(previousPid = first.pid)
        assertTrue("killed while uploading", statusAtKill == "running")
        val doneDeadline = System.currentTimeMillis() + 300_000
        var job: JsonObject
        do {
            job = jobsFor(second, assetId).single()
            if (job["status"]!!.jsonPrimitive.content == "succeeded") break
            check(job["status"]!!.jsonPrimitive.content != "failed") { "upload failed after restart: $job" }
            Thread.sleep(500)
        } while (System.currentTimeMillis() < doneDeadline)
        assertEquals("succeeded", job["status"]!!.jsonPrimitive.content)

        val actual = MessageDigest.getInstance("SHA-256")
        client.newCall(request(second, "/api/assets/$assetId/download").build()).execute().use { response ->
            assertEquals(200, response.code)
            val source = response.body.source()
            val buffer = ByteArray(1 shl 20)
            while (true) {
                val read = source.read(buffer)
                if (read < 0) break
                actual.update(buffer, 0, read)
            }
        }
        assertEquals(digest, actual.digest().joinToString("") { "%02x".format(it) })
    }
}
