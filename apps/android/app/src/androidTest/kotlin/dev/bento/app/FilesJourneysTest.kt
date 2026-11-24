package dev.bento.app

import android.Manifest
import android.content.ClipData
import android.content.ContentValues
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.pdf.PdfDocument
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.longClick
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.test.performTouchInput
import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import dev.bento.api.generated.FolderCreateRequest
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.regex.Pattern
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Archivos, Buscar and Compartir journeys (testing/android-journeys.md 6, 8, 9) on the emulator with the real
 * embedded engine and the remote fake cloud shared with `feature/files/e2e/files_host.py` (one headless desktop).
 * Each journey expects a freshly cleared app (`feature/files/e2e/run_journeys.sh` runs one per `am instrument`).
 */
@RunWith(AndroidJUnit4::class)
class FilesJourneysTest {
    @get:Rule
    val compose = createEmptyComposeRule()

    @get:Rule
    val permissions: GrantPermissionRule = if (Build.VERSION.SDK_INT >= 33) {
        GrantPermissionRule.grant(Manifest.permission.POST_NOTIFICATIONS)
    } else {
        GrantPermissionRule.grant(Manifest.permission.READ_EXTERNAL_STORAGE)
    }

    private val journey = Journey(compose)
    private val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
    private val resolver = journey.context.contentResolver
    private var shareScenario: ActivityScenario<ShareActivity>? = null

    @After
    fun close() {
        airplane(false)
        shareScenario?.close()
        journey.scenario?.close()
    }

    /** 6. Share to Bento: 3 images + 1 PDF → sheet → saved in the chosen folder; the sheet is gone ≤ 200 ms. */
    @Test
    fun j06_shareToBento() {
        joinHostCloud()
        val folder = runBlocking { journey.phone.createFolder(FolderCreateRequest(name = "Compartidos")) }
        val uris =
            (1..3).map { insertImage("Playa $it.jpg", Color.rgb(40 * it, 120, 200)) } +
                insertDownload("BentoShare", "Contrato.pdf", "application/pdf", pdf("Contrato"))
        journey.scenario?.close()
        val intent = Intent(Intent.ACTION_SEND_MULTIPLE)
            .setClass(journey.context, ShareActivity::class.java)
            .setType("*/*")
            .putParcelableArrayListExtra(Intent.EXTRA_STREAM, ArrayList(uris))
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        intent.clipData = ClipData.newRawUri(null, uris.first()).apply { uris.drop(1).forEach { addItem(ClipData.Item(it)) } }
        shareScenario = ActivityScenario.launch(intent)
        journey.waitText("4 archivos", 60_000, substring = true)
        journey.capture("j06-1-sheet")
        journey.tap("Carpeta")
        journey.tap("Compartidos", 30_000)
        journey.tap("Guardar aquí")
        journey.waitText("Compartidos")
        journey.capture("j06-2-destination")
        val save = compose.onNode(hasText("Guardar en Bento") and hasClickAction())
        val started = System.nanoTime()
        save.performClick()
        var gone = 0L
        while (System.nanoTime() - started < 5_000_000_000L) {
            val state = shareScenario!!.state
            if (state == Lifecycle.State.DESTROYED || state == Lifecycle.State.CREATED) {
                gone = (System.nanoTime() - started) / 1_000_000
                break
            }
            Thread.sleep(2)
        }
        android.util.Log.i("BentoJourney", "j06 share sheet gone after $gone ms")
        assertTrue("sheet gone after $gone ms", gone in 1..SHEET_BUDGET_MS)
        val names = waitFor("4 shared items in Compartidos", 120_000) {
            runBlocking { journey.phone.driveItems(folderId = folder.id).items }.map { it.name }.toSet().takeIf { it.size == 4 }
        }
        assertEquals(setOf("Playa 1.jpg", "Playa 2.jpg", "Playa 3.jpg", "Contrato.pdf"), names)
    }

    /** 8. Files: create a folder, upload a folder tree via SAF, move, rename, pin offline; airplane mode. */
    @Test
    fun j08_files() {
        insertDownload("BentoTree", "Guia.pdf", "application/pdf", pdf("Guía de viaje"))
        insertDownload("BentoTree", "notas.txt", "text/plain", "Llevar pasaporte\nReservar hotel".toByteArray())
        insertDownload("BentoTree/Fotos", "mapa.txt", "text/plain", "Mapa".toByteArray())
        joinHostCloud()
        journey.tap("Archivos")
        journey.waitText("Nuevo")
        // New folder.
        journey.tap("Nuevo")
        journey.tap("Nueva carpeta", 10_000)
        compose.onNode(hasContentDescription("Nombre de la carpeta", substring = true)).performTextReplacement("Viajes")
        journey.tap("Crear")
        journey.waitText("Viajes")
        journey.capture("j08-1-folder")
        // Folder tree through the system picker.
        journey.tap("Nuevo")
        journey.tap("Subir una carpeta", 10_000)
        pickTreeInDocumentsUi("BentoTree")
        journey.waitText("BentoTree", 120_000)
        journey.tap("BentoTree")
        journey.waitText("notas.txt", 120_000)
        journey.waitText("Fotos")
        journey.capture("j08-2-tree")
        // Move notas.txt to Viajes.
        compose.onNode(hasText("notas.txt")).performTouchInput { longClick() }
        compose.onNode(hasContentDescription("Mover")).performClick()
        journey.waitText("Mover a…")
        compose.onNode(hasContentDescription("Subir un nivel") and hasClickAction(), useUnmergedTree = true).performClick()
        journey.tap("Viajes")
        journey.tap("Mover aquí")
        journey.waitText("Se movió a «Viajes»")
        // Rename and pin the PDF.
        compose.onNode(hasContentDescription("Opciones de «Guia.pdf»")).performClick()
        journey.tap("Renombrar")
        compose.onNode(hasContentDescription("Nuevo nombre", substring = true)).performTextReplacement("Guía de viaje.pdf")
        journey.tap("Guardar")
        journey.waitText("Guía de viaje.pdf")
        compose.onNode(hasContentDescription("Opciones de «Guía de viaje.pdf»")).performClick()
        journey.tap("Disponible sin conexión")
        journey.waitText("estará disponible sin conexión", substring = true)
        journey.capture("j08-3-pinned")
        // Airplane mode: the pinned PDF opens, the unpinned note explains how to keep it offline.
        airplane(true)
        journey.tap("Guía de viaje.pdf")
        journey.waitText("Página 1 de 1", 60_000)
        journey.capture("j08-4-offline-pinned-opens")
        device.pressBack()
        compose.onNode(hasContentDescription("Subir un nivel") and hasClickAction()).performClick()
        journey.tap("Viajes")
        journey.tap("notas.txt", 30_000)
        journey.waitText("No disponible sin conexión")
        journey.capture("j08-5-offline-unpinned")
    }

    /** 9. Search: OCR text of an image the desktop indexed is found on the phone; filters; no results. */
    @Test
    fun j09_searchDesktopOcr() {
        joinHostCloud()
        uploadToDesktop("recibo-luz.png", png())
        waitFor("the desktop's OCR synced to the phone", 180_000) {
            runBlocking { journey.phone.search(q = "luz").items }.firstOrNull { it.title == "recibo-luz.png" }
        }
        journey.tap("Archivos")
        journey.tap(SEARCH_PILL)
        compose.onNode(hasContentDescription(SEARCH_PILL, substring = true) and hasClickAction().not()).performTextReplacement("luz")
        journey.waitText("Texto en la imagen: «luz»", 30_000)
        journey.waitText("recibo-luz.png")
        journey.capture("j09-1-ocr-result")
        journey.tap("Fecha")
        journey.tap("Este mes", 10_000)
        journey.waitText("recibo-luz.png", 30_000)
        journey.capture("j09-2-filtered")
        compose.onNode(hasContentDescription(SEARCH_PILL, substring = true) and hasClickAction().not()).performTextReplacement("zzqxwv")
        journey.waitText("No encontramos «zzqxwv»", 30_000)
        journey.capture("j09-3-no-results")
        compose.onAllNodes(hasText("Quitar filtros") and hasClickAction())[0].performClick()
        journey.waitText("No encontramos «zzqxwv»", 30_000)
    }

    /** English copy of Archivos and Buscar (run with APP_LOCALE=en-US). */
    @Test
    fun j90_englishFiles() {
        joinHostCloud(english = true)
        journey.tap("Files")
        journey.waitText("Your cloud is ready", 30_000)
        journey.capture("en-1-files-empty")
        journey.tap("New")
        journey.waitText("Upload photos or videos", 10_000)
        journey.capture("en-2-new-sheet")
        device.pressBack()
        journey.tap("Search Bento")
        journey.waitText("Spreadsheets", 10_000)
        journey.capture("en-3-search")
    }

    // Steps --------------------------------------------------------------------------------------------------------

    private fun joinHostCloud(english: Boolean = false) {
        val desktop = HostDevice.desktop
        assumeTrue("files_host.py is not running", desktop.reachable())
        desktop.ensureVault()
        val code = desktop.call("POST", "/vault/recovery-code").getString("recovery_code")
        journey.clipboard(code)
        journey.launch()
        if (english) {
            journey.tap("I already use Bento on another device", 90_000)
            journey.tap("I don’t have the other device")
            journey.tap("Use my phone number")
        } else {
            journey.tap("Ya uso Bento en otro dispositivo", 90_000)
            journey.tap("No tengo el otro dispositivo")
        }
        if (english) {
            journey.type("Phone number", "3001234567")
            journey.tap("Send code")
            if (runCatching { journey.waitText("Enter the code", 20_000) }.isSuccess) journey.type("Telegram code", Journey.FAKE_CODE)
            journey.tap("Use my recovery kit", 60_000)
            journey.tap("Paste the copied code")
            journey.waitText("Files", 120_000)
        } else {
            journey.signInWithPhone()
            journey.tap("Usar mi kit de recuperación", 60_000)
            journey.tap("Pegar el código copiado")
            journey.inLibrary(120_000)
        }
    }

    /** Drives DocumentsUI (system folder picker) to grant [folder] under Downloads. */
    private fun pickTreeInDocumentsUi(folder: String) {
        val timeout = 20_000L
        device.wait(Until.hasObject(By.pkg(Pattern.compile(".*documentsui.*"))), timeout)
        device.findObject(By.desc(Pattern.compile("Show roots|Mostrar raíces", Pattern.CASE_INSENSITIVE)))?.click()
        device.wait(Until.findObject(By.text(Pattern.compile("Downloads|Descargas"))), timeout)?.click()
        device.wait(Until.findObject(By.text(folder)), timeout)!!.click()
        device.wait(
            Until.findObject(By.text(Pattern.compile("Use this folder|Usar esta carpeta", Pattern.CASE_INSENSITIVE))),
            timeout
        )!!.click()
        device.wait(Until.findObject(By.text(Pattern.compile("Allow|Permitir", Pattern.CASE_INSENSITIVE))), timeout)!!.click()
    }

    private fun airplane(on: Boolean) {
        val state = if (on) "enable" else "disable"
        InstrumentationRegistry.getInstrumentation().uiAutomation.executeShellCommand("cmd connectivity airplane-mode $state").close()
        val connectivity = journey.context.getSystemService(ConnectivityManager::class.java)
        waitFor("airplane mode $state", 20_000) {
            val online =
                connectivity.getNetworkCapabilities(
                    connectivity.activeNetwork
                )?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) ==
                    true
            (online != on).takeIf { it }
        }
    }

    private fun insertImage(name: String, color: Int): Uri {
        val bitmap = Bitmap.createBitmap(640, 480, Bitmap.Config.ARGB_8888).apply { eraseColor(color) }
        val bytes = ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.JPEG, 90, it) }.toByteArray()
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, name)
            put(MediaStore.MediaColumns.MIME_TYPE, "image/jpeg")
            put(MediaStore.MediaColumns.RELATIVE_PATH, "Pictures/BentoShare")
        }
        val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)!!
        resolver.openOutputStream(uri)!!.use { it.write(bytes) }
        return uri
    }

    private fun insertDownload(folder: String, name: String, mime: String, bytes: ByteArray): Uri {
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, name)
            put(MediaStore.MediaColumns.MIME_TYPE, mime)
            put(MediaStore.MediaColumns.RELATIVE_PATH, "Download/$folder")
        }
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)!!
        resolver.openOutputStream(uri)!!.use { it.write(bytes) }
        return uri
    }

    private fun pdf(title: String): ByteArray {
        val document = PdfDocument()
        val page = document.startPage(PdfDocument.PageInfo.Builder(595, 842, 1).create())
        page.canvas.drawText(title, 72f, 96f, Paint().apply { textSize = 24f })
        document.finishPage(page)
        return ByteArrayOutputStream().also { document.writeTo(it) }.toByteArray().also { document.close() }
    }

    private fun png(): ByteArray {
        val bitmap = Bitmap.createBitmap(800, 400, Bitmap.Config.ARGB_8888).apply { eraseColor(Color.WHITE) }
        Canvas(bitmap).drawText("FACTURA DE LUZ", 40f, 200f, Paint().apply { textSize = 64f })
        return ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
    }

    /** `POST /api/assets/upload` on the host desktop (multipart), as its own UI would. */
    private fun uploadToDesktop(name: String, bytes: ByteArray) {
        val boundary = "bento${System.nanoTime()}"
        val connection = URL("http://127.0.0.1:8791/api/assets/upload").openConnection() as HttpURLConnection
        connection.requestMethod = "POST"
        connection.doOutput = true
        connection.setRequestProperty("X-Bento-Client", "web")
        connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
        DataOutputStream(connection.outputStream).use { out ->
            out.writeBytes(
                "--$boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"$name\"\r\nContent-Type: image/png\r\n\r\n"
            )
            out.write(bytes)
            out.writeBytes("\r\n--$boundary--\r\n")
        }
        check(connection.responseCode < 400) { "desktop upload → ${connection.responseCode}" }
    }

    private fun <T : Any> waitFor(what: String, timeoutMs: Long, probe: () -> T?): T {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            runCatching(probe).getOrNull()?.let { return it }
            Thread.sleep(500)
        }
        throw AssertionError("Timed out waiting for $what")
    }

    private companion object {
        const val SHEET_BUDGET_MS = 200L
        const val SEARCH_PILL = "Buscar en Bento"
    }
}
