package dev.bento.app

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.view.WindowManager
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.ComposeTimeoutException
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.ComposeTestRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import dev.bento.api.BentoHttp
import dev.bento.api.EngineEndpointProvider
import dev.bento.api.generated.BentoEndpoints
import dev.bento.api.loopbackOkHttp
import dev.bento.app.navigation.Navigator
import dev.bento.app.navigation.Route
import dev.bento.engine.di.PlatformEntryPoint
import java.net.HttpURLConnection
import java.net.URL
import org.json.JSONObject

/** Shared steps of the trust journeys (testing/android-journeys.md 1-4, 13-15). */
internal class Journey(val compose: ComposeTestRule) {
    val context: Context = ApplicationProvider.getApplicationContext()
    private val engine = PlatformEntryPoint.get(context).engine()
    val phone = BentoEndpoints(BentoHttp(loopbackOkHttp(engine), EngineEndpointProvider(engine, timeoutMs = 180_000)))
    var scenario: ActivityScenario<MainActivity>? = null

    fun launch(intent: Intent? = null) {
        scenario = if (intent == null) ActivityScenario.launch(MainActivity::class.java) else ActivityScenario.launch(intent)
    }

    fun relaunch() {
        scenario?.close()
        launch()
    }

    fun appLink(link: String): Intent = Intent(Intent.ACTION_VIEW, Uri.parse(link)).setClass(context, MainActivity::class.java)

    fun waitText(text: String, timeoutMs: Long = 60_000, substring: Boolean = false) = waitFor(
        hasText(text, substring = substring),
        timeoutMs
    )

    fun waitFor(matcher: SemanticsMatcher, timeoutMs: Long = 60_000) {
        try {
            compose.waitUntil(timeoutMs) { compose.onAllNodes(matcher, useUnmergedTree = true).fetchSemanticsNodes().isNotEmpty() }
        } catch (timeout: ComposeTimeoutException) {
            throw AssertionError("Timed out waiting for $matcher", timeout)
        }
    }

    fun tap(text: String, timeoutMs: Long = 60_000) {
        waitText(text, timeoutMs)
        compose.onNodeWithText(text).performClick()
    }

    fun type(fieldDescription: String, value: String) {
        waitFor(hasContentDescription(fieldDescription, substring = true))
        compose.onNode(hasContentDescription(fieldDescription, substring = true)).performTextInput(value)
    }

    fun description(prefix: String): String {
        waitFor(hasContentDescription(prefix, substring = true))
        return compose.onNode(hasContentDescription(prefix, substring = true), useUnmergedTree = true)
            .fetchSemanticsNode().config.getOrNull(SemanticsProperties.ContentDescription)!!.joinToString(" ")
    }

    fun secure(): Boolean {
        var flags = 0
        scenario!!.onActivity { flags = it.window.attributes.flags }
        return flags and WindowManager.LayoutParams.FLAG_SECURE != 0
    }

    /** Ajustes is another agent's screen; journeys open Dispositivos the way its row will. */
    fun navigate(route: Route) {
        scenario!!.onActivity { activity ->
            val field = MainActivity::class.java.getDeclaredField("navigator").apply { isAccessible = true }
            (field.get(activity) as Navigator).navigate(route)
        }
    }

    /** Real device screenshot (FLAG_SECURE screens come out black, which is the point) for the visual record. */
    fun capture(name: String) {
        compose.waitForIdle()
        Thread.sleep(400)
        val bitmap = InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot() ?: return
        val dir = java.io.File(context.getExternalFilesDir(null), "journeys").apply { mkdirs() }
        java.io.File(dir, "$name.png").outputStream().use { bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it) }
    }

    fun clipboard(text: String) = InstrumentationRegistry.getInstrumentation().runOnMainSync {
        context.getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("test", text))
    }

    /** First-run sign-in on this phone with the fake cloud's code. */
    fun signInWithPhone() {
        tap("Usar mi número de teléfono")
        type("Número de teléfono", "3001234567")
        tap("Enviar código")
        // An account that is still (or again) authorized skips the code: the flow simply moves on.
        val codeShown = runCatching { waitText("Escribe el código", 20_000) }.isSuccess
        if (codeShown) type("Código de Telegram", FAKE_CODE)
    }

    fun inLibrary(timeoutMs: Long = 60_000) = waitText("Archivos", timeoutMs)

    companion object {
        const val FAKE_CODE = "12345"
    }
}

/** A headless desktop device run by `feature/pairing/e2e/trust_host.py`, reached through `adb reverse`. */
internal class HostDevice(port: Int) {
    private val base = "http://127.0.0.1:$port/api"

    fun reachable(): Boolean = runCatching { call("GET", "/health") }.isSuccess

    fun call(method: String, path: String, body: String? = null): JSONObject {
        val connection = URL(base + path).openConnection() as HttpURLConnection
        connection.requestMethod = method
        connection.connectTimeout = 3_000
        connection.readTimeout = 60_000
        connection.setRequestProperty("X-Bento-Client", "web")
        if (body != null) {
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json")
            connection.outputStream.use { it.write(body.toByteArray()) }
        }
        val code = connection.responseCode
        val text = (if (code < 400) connection.inputStream else connection.errorStream)?.bufferedReader()?.readText().orEmpty()
        check(code < 400) { "$method $path → $code $text" }
        return if (text.isBlank()) JSONObject() else JSONObject(text)
    }

    /** Signs this desktop in (fake cloud code) and makes sure the account has a cloud; returns its recovery code if created. */
    fun ensureVault(): String? {
        if (call("GET", "/account").getString("step") != "authorized") {
            call("POST", "/account/login/phone", """{"phone":"+573001234567"}""")
            check(call("POST", "/account/login/code", """{"code":"${Journey.FAKE_CODE}"}""").getString("step") == "authorized")
        }
        return when (call("GET", "/vault").getString("state")) {
            "no_vault" -> call("POST", "/vault").getString("recovery_code")
            else -> null
        }
    }

    fun waitPairing(id: String, state: String, timeoutMs: Long = 60_000): JSONObject {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val pairing = call("GET", "/pairing/$id")
            if (pairing.getString("state") == state) return pairing
            check(pairing.getString("state") !in setOf("failed", "expired", "cancelled", "rejected")) { "pairing ended: $pairing" }
            Thread.sleep(250)
        }
        error("pairing $id never reached $state")
    }

    companion object {
        val desktop = HostDevice(8791)
        val desktop2 = HostDevice(8792)
    }
}
