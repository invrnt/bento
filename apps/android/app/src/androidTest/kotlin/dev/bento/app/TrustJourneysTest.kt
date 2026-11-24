package dev.bento.app

import android.Manifest
import android.os.Build
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.rule.GrantPermissionRule
import dev.bento.app.navigation.Route
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Trust journeys of testing/android-journeys.md on the emulator with the real embedded engine and the fake cloud.
 * Each test expects a freshly cleared app (`feature/pairing/e2e/run_journeys.sh` runs one per `am instrument`).
 * The multi-device ones need `trust_host.py` (remote fake cloud, relay double, two headless desktops) behind
 * `adb reverse`; without it they are skipped.
 */
@RunWith(AndroidJUnit4::class)
class TrustJourneysTest {
    @get:Rule
    val compose = createEmptyComposeRule()

    @get:Rule
    val permissions: GrantPermissionRule = if (Build.VERSION.SDK_INT >= 33) {
        GrantPermissionRule.grant(Manifest.permission.POST_NOTIFICATIONS, Manifest.permission.CAMERA)
    } else {
        GrantPermissionRule.grant(Manifest.permission.CAMERA)
    }

    private val journey = Journey(compose)

    @After
    fun close() {
        journey.scenario?.close()
    }

    /** English copy (run with APP_LOCALE=en-US): welcome, sign-in options and the join scanner rationale. */
    @Test
    fun j90_englishCopy() {
        journey.launch()
        journey.waitText("Get started", 90_000)
        journey.capture("en-1-welcome")
        journey.tap("Get started")
        journey.waitText("Use my phone number")
        journey.capture("en-2-signin")
        journey.relaunch()
        journey.tap("I already use Bento on another device", 90_000)
        journey.waitText("Add this phone to your cloud")
        journey.capture("en-3-join")
    }

    private fun requireHost() = assumeTrue("trust_host.py is not running", HostDevice.desktop.reachable())

    /** 1. First run, new vault (sign-in, cloud creation, backup hand-off, kit confirmed by its last group). */
    @Test
    fun j01_firstRunNewVault() {
        journey.launch()
        journey.waitText("Empezar", 90_000)
        journey.capture("j01-1-welcome")
        journey.tap("Empezar")
        journey.waitText("Usar mi número de teléfono")
        journey.capture("j01-2-signin")
        journey.signInWithPhone()
        journey.waitText("Creando tu nube", 30_000)
        journey.capture("j01-3-creating")
        // Respalda este teléfono (agent 41): left off here; BackupJourneysTest turns it on with full media access.
        journey.tap("Ahora no", 90_000)
        val spoken = journey.description("Código de recuperación: ")
        assertTrue("FLAG_SECURE on the kit", journey.secure())
        journey.capture("j01-4-kit-flag-secure")
        val lastGroup = spoken.substringAfter(": ").split(", ").last().replace(" ", "")
        journey.type("Último grupo del código", lastGroup)
        journey.waitText("Ir a mis fotos", 30_000)
        journey.capture("j01-5-done")
        journey.tap("Ir a mis fotos")
        journey.inLibrary()
        assertFalse(journey.secure())
        val vault = runBlocking { journey.phone.vaultStatus() }
        assertEquals("ready", vault.state)
        assertTrue("kit confirmed", vault.recoveryKitSaved)
        journey.relaunch()
        journey.inLibrary(10_000) // next start goes straight to the library
    }

    /** 3. Join by App Link: the code arrives filled in; joining still takes a tap. */
    @Test
    fun j03_joinByAppLink() {
        journey.launch(journey.appLink("https://bento.example/join#v=1&c=K7Q2-MXR9-T4WA"))
        journey.waitText("Unirme", 90_000)
        compose.onNodeWithText("Unirme").assertIsEnabled()
        journey.capture("j03-app-link-prefilled")
        compose.onNodeWithText("K7Q2MXR9T4WA", substring = true, useUnmergedTree = true).assertExists()
    }

    /** 2. Join from a desktop by code: SAS on both, host approves, login token forwarded, library visible. */
    @Test
    fun j02_joinFromDesktopByCode() {
        requireHost()
        val desktop = HostDevice.desktop
        desktop.ensureVault()
        val pairing = desktop.call("POST", "/pairing/host")
        journey.launch()
        journey.tap("Ya uso Bento en otro dispositivo", 90_000)
        journey.tap("Escribir el código")
        journey.type("Código de emparejamiento", pairing.getString("code"))
        journey.tap("Unirme")
        journey.waitText("Confirma en tu computador", 60_000)
        journey.capture("j02-sas")
        val phoneSas = journey.description("Emojis de verificación")
        val hostSas = desktop.waitPairing(pairing.getString("id"), "awaiting_approval").getJSONArray("sas")
        for (i in 0 until hostSas.length()) assertTrue(phoneSas.contains(hostSas.getString(i)))
        desktop.call("POST", "/pairing/${pairing.getString("id")}/approve")
        journey.inLibrary(120_000)
        val account = runBlocking { journey.phone.accountStatus() }
        assertEquals("signed in through the forwarded login token", "authorized", account.step)
        // A file added on the desktop reaches the phone while it is in the foreground.
        val before = runBlocking { journey.phone.driveItems().items.size }
        desktop.call("POST", "/drive/folders", """{"name":"Desde el portátil ${System.currentTimeMillis()}"}""")
        val deadline = System.currentTimeMillis() + 20_000
        var after = before
        while (after <= before && System.currentTimeMillis() < deadline) {
            Thread.sleep(500)
            runBlocking { journey.phone.syncNow() }
            after = runBlocking { journey.phone.driveItems().items.size }
        }
        assertTrue("desktop change synced to the phone", after > before)
    }

    /** 4. Recovery without the other device: sign in, paste the kit's code, bootstrap. */
    @Test
    fun j04_recoveryWithoutOtherDevice() {
        requireHost()
        val desktop = HostDevice.desktop
        desktop.ensureVault()
        val code = desktop.call("POST", "/vault/recovery-code").getString("recovery_code")
        journey.clipboard(code)
        journey.launch()
        journey.tap("Ya uso Bento en otro dispositivo", 90_000)
        journey.tap("No tengo el otro dispositivo")
        journey.signInWithPhone()
        journey.tap("Usar mi kit de recuperación", 60_000)
        journey.waitText("Escribe tu código de recuperación")
        compose.waitForIdle()
        assertTrue("FLAG_SECURE on recovery entry", journey.secure())
        journey.tap("Pegar el código copiado")
        journey.inLibrary(120_000)
        assertEquals("bootstrapping or ready", true, runBlocking { journey.phone.vaultStatus().state } in setOf("ready", "bootstrapping"))
    }

    /** 13. Phone as host: Dispositivos › Añadir dispositivo, a second desktop joins with the code shown. */
    @Test
    fun j13_phoneAsHost() {
        requireHost()
        joinPhoneByRecovery()
        journey.navigate(Route.Devices)
        journey.tap("Añadir dispositivo", 30_000)
        val spoken = journey.description("Código: ")
        assertTrue("FLAG_SECURE on the pairing code", journey.secure())
        val code = spoken.substringAfter("Código: ").replace(" ", "").chunked(4).joinToString("-")
        val guest = HostDevice.desktop2
        if (guest.call("GET", "/account").getString("step") == "authorized") guest.call("POST", "/account/logout")
        val joined = guest.call("POST", "/pairing/join", """{"code":"$code"}""")
        journey.waitText("Añadir", 60_000)
        journey.capture("j13-approve")
        journey.tap("Añadir")
        journey.waitText("Dispositivo añadido", 60_000)
        journey.capture("j13-added")
        guest.waitPairing(joined.getString("id"), "completed", 60_000)
    }

    /** 14. Removed from the desktop: the phone says so, keeps its library, and joins again as a new device. */
    @Test
    fun j14_removedFromDesktop() {
        requireHost()
        joinPhoneByRecovery()
        val before =
            eventually("this phone's device record") { runBlocking { journey.phone.listDevices().items.firstOrNull { it.current }?.id } }
        val desktop = HostDevice.desktop
        // The desktop learns about the phone through the Sync channel.
        val phoneId = eventually("the desktop sees the phone") {
            runBlocking { journey.phone.syncNow() }
            desktop.call("POST", "/sync/now")
            val devices = desktop.call("GET", "/devices").getJSONArray("items")
            (0 until devices.length()).map { devices.getJSONObject(it).getString("id") }.firstOrNull { it == before }
        }
        desktop.call("DELETE", "/devices/$phoneId", "{}")
        // Removal closes the phone's Telegram session (ResetAuthorization) before the phone can read the keys message,
        // so the phone first reports a closed session: it shows the reconnect screen over its library.
        eventually("the phone notices") {
            runBlocking { journey.phone.syncNow() }
            runBlocking { journey.phone.vaultStatus() }.takeIf { it.state != "ready" }
        }
        journey.relaunch()
        if (runBlocking { journey.phone.vaultStatus().reason } == "session_closed") {
            journey.tap("Volver a conectar", 60_000)
            journey.signInWithPhone()
            // Signed in again, sync reads the keys message that left this phone out.
            eventually("the phone learns it was removed", 90_000) {
                runBlocking { journey.phone.syncNow() }
                runBlocking { journey.phone.vaultStatus() }.takeIf { it.reason == "device_removed" }
            }
            journey.relaunch()
        }
        // "Este teléfono se quitó de tu nube", over the library that stays readable.
        journey.waitText("Volver a unirme", 120_000)
        journey.capture("j14-removed")
        journey.tap("Volver a unirme")
        val pairing = desktop.call("POST", "/pairing/host")
        journey.tap("Escribir el código")
        journey.type("Código de emparejamiento", pairing.getString("code"))
        journey.tap("Unirme")
        desktop.waitPairing(pairing.getString("id"), "awaiting_approval")
        desktop.call("POST", "/pairing/${pairing.getString("id")}/approve")
        journey.inLibrary(120_000)
        val after = eventually("the new identity") { runBlocking { journey.phone.listDevices().items.firstOrNull { it.current }?.id } }
        assertNotEquals("joined again with a new identity", before, after)
    }

    /** 15. Session closed: reconnect screen over the library; signing in again resumes. Single device. */
    @Test
    fun j15_sessionRevoked() {
        journey.launch()
        journey.tap("Empezar", 90_000)
        journey.signInWithPhone()
        journey.tap("Ahora no", 90_000) // Respalda este teléfono: backup stays off
        journey.tap("Más tarde", 30_000)
        journey.tap("Ir a mis fotos", 30_000)
        journey.inLibrary()
        // The fake cloud cannot revoke from "another app"; logging out keeps the cloud layout, which the engine
        // reports exactly like a session closed elsewhere (`signed_out` + `session_closed`).
        runBlocking { journey.phone.logOut() }
        assertEquals("session_closed", runBlocking { journey.phone.vaultStatus().reason })
        journey.relaunch()
        journey.waitText("Bento se desconectó de Telegram", 60_000)
        journey.capture("j15-reconnect")
        journey.tap("Volver a conectar")
        journey.signInWithPhone()
        journey.inLibrary(60_000)
        assertEquals("ready", runBlocking { journey.phone.vaultStatus().state })
    }

    private fun <T : Any> eventually(what: String, timeoutMs: Long = 60_000, probe: () -> T?): T {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            runCatching(probe).getOrNull()?.let { return it }
            Thread.sleep(500)
        }
        throw AssertionError("Timed out waiting for $what")
    }

    private fun joinPhoneByRecovery() {
        val desktop = HostDevice.desktop
        desktop.ensureVault()
        val code = desktop.call("POST", "/vault/recovery-code").getString("recovery_code")
        journey.clipboard(code)
        journey.launch()
        journey.tap("Ya uso Bento en otro dispositivo", 90_000)
        journey.tap("No tengo el otro dispositivo")
        journey.signInWithPhone()
        journey.tap("Usar mi kit de recuperación", 60_000)
        journey.tap("Pegar el código copiado")
        journey.inLibrary(120_000)
    }
}
