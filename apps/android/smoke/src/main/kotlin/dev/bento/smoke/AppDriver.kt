package dev.bento.smoke

import android.os.ParcelFileDescriptor
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** Drives the debug app from another process through shell commands (`am`, `run-as`). */
object AppDriver {
    const val PACKAGE = "dev.bento.app"

    data class Endpoint(val port: Int, val token: String, val pid: Int)

    fun shell(command: String): String {
        val pfd = InstrumentationRegistry.getInstrumentation().uiAutomation.executeShellCommand(command)
        return ParcelFileDescriptor.AutoCloseInputStream(pfd).bufferedReader().use { it.readText() }
    }

    fun forceStop() {
        shell("am force-stop $PACKAGE")
    }

    fun writeDevOptions(json: String) {
        // run-as needs a single argument; the JSON has no spaces or quotes problems once base64-free.
        shell("run-as $PACKAGE sh -c 'echo $json > files/dev-options.json'")
    }

    fun launch() {
        shell("am start -W -n $PACKAGE/.MainActivity")
    }

    /** Waits for the debug-only `no_backup/dev-endpoint.json` written when the engine is Ready. */
    fun awaitEndpoint(previousPid: Int? = null, timeoutMs: Long = 180_000): Endpoint {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val text = shell("run-as $PACKAGE cat no_backup/dev-endpoint.json").trim()
            if (text.startsWith("{")) {
                val json = Json.parseToJsonElement(text).jsonObject
                val endpoint = Endpoint(json["port"]!!.jsonPrimitive.int, json["token"]!!.jsonPrimitive.content, json["pid"]!!.jsonPrimitive.int)
                if (endpoint.pid != previousPid) return endpoint
            }
            Thread.sleep(200)
        }
        error("engine endpoint not published within $timeoutMs ms")
    }

    fun kill(pid: Int) {
        shell("run-as $PACKAGE kill -9 $pid")
    }
}
