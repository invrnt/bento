package dev.bento.feature.photos.benchmark

import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import dev.bento.benchmark.common.BentoDevice
import dev.bento.benchmark.common.LibrarySeeder
import java.io.File
import java.util.regex.Pattern
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Instrumented journeys on the real app (embedded engine, fake Telegram cloud), in Spanish:
 * journey 7 (viewer) end to end, and the Fotos parts of journeys 1, 2 and 5 (testing/android-journeys.md).
 */
@RunWith(AndroidJUnit4::class)
class PhotosJourneysTest {
    private val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
    private val tile = Pattern.compile("photos:tile:.*")

    @Before
    fun spanish() {
        BentoDevice.shell("cmd locale set-app-locales ${BentoDevice.PACKAGE} --locales es-ES")
    }

    private fun waitRes(res: String, timeoutMs: Long = 20_000): UiObject2 {
        dismissSystemDialogs()
        return device.wait(Until.findObject(By.res(res)), timeoutMs)
            ?: dismissSystemDialogs().let { device.wait(Until.findObject(By.res(res)), 5_000) }
            ?: failWithScreen("no $res on screen")
    }

    /** A loaded emulator shows "X isn't responding" for other apps; keep waiting so our UI is reachable. */
    private fun dismissSystemDialogs() {
        repeat(3) { device.findObject(By.text("Wait"))?.click() ?: return }
    }

    /** Saves a screenshot and the UI tree next to the test results, then fails. */
    private fun failWithScreen(message: String): Nothing {
        val dir = "/sdcard/Android/media/dev.bento.feature.photos.benchmark"
        val name = message.replace(Regex("[^A-Za-z0-9]+"), "-")
        BentoDevice.shell("mkdir -p $dir")
        BentoDevice.shell("screencap -p $dir/$name.png")
        BentoDevice.shell("uiautomator dump $dir/$name.xml")
        error(message)
    }

    private fun waitDesc(desc: String, timeoutMs: Long = 10_000): UiObject2 =
        device.wait(Until.findObject(By.desc(desc)), timeoutMs) ?: error("no '$desc' on screen")

    private fun asset(endpoint: BentoDevice.Endpoint, id: String) = BentoDevice.call(endpoint, "GET", "/api/assets/$id")

    private fun trashIds(endpoint: BentoDevice.Endpoint) =
        BentoDevice.call(endpoint, "GET", "/api/trash?limit=200")["items"]!!.jsonArray.map { it.jsonObject["id"]!!.jsonPrimitive.content }.toSet()

    @Test
    fun journey7_viewer() {
        BentoDevice.forceStop()
        val seeding = BentoDevice.ready()
        LibrarySeeder.ensurePhotos(seeding, 120)
        val clip = InstrumentationRegistry.getInstrumentation().context.assets.open("sample-video.mp4").use { it.readBytes() }
        val videoId = LibrarySeeder.ensureVideo(seeding, clip)
        BentoDevice.forceStop()
        BentoDevice.launch()
        val endpoint = BentoDevice.awaitEndpoint(previousPid = seeding.pid)
        val grid = waitRes("photos:grid", 60_000)
        val photoTile = Pattern.compile("photos:tile:(?!$videoId).*")
        device.wait(Until.hasObject(By.res(photoTile)), 30_000) ?: failWithScreen("no photo tiles")
        device.waitForIdle()

        // Open from the grid (shared element) on a photo, not the video at the top.
        val first = grid.findObject(By.res(photoTile)) ?: failWithScreen("no photo tile")
        val openedId = first.resourceName.removePrefix("photos:tile:")
        val tapAt = System.nanoTime()
        first.click()
        val pager = waitRes("viewer:pager", 5_000)
        Log.i("BentoJourney", "viewer visible after ${(System.nanoTime() - tapAt) / 1_000_000} ms (UiAutomator round trip)")

        // Swipe through 50 items.
        repeat(50) {
            pager.swipe(Direction.LEFT, 0.9f, 4_000)
            device.waitForIdle(200)
        }
        // Zoom in and out (pinch), then the info sheet with a swipe up.
        pager.pinchOpen(0.6f, 1_500)
        device.waitForIdle()
        pager.pinchClose(0.6f, 1_500)
        device.waitForIdle()
        // Info: swipe up at fit zoom; Detalles in the overflow is the non-gesture path.
        device.swipe(device.displayWidth / 2, device.displayHeight * 3 / 4, device.displayWidth / 2, device.displayHeight / 4, 20)
        if (device.wait(Until.findObject(By.res("viewer:info")), 3_000) == null) {
            Log.i("BentoJourney", "swipe up did not open the info; using Detalles")
            if (device.findObject(By.desc("Más opciones")) == null) device.click(device.displayWidth / 2, device.displayHeight / 2)
            waitDesc("Más opciones").click()
            device.wait(Until.findObject(By.text("Detalles")), 5_000)!!.click()
        }
        waitRes("viewer:info", 5_000)
        device.pressBack()
        device.waitForIdle()

        // Favorite (heart toggles; the backend has it) and delete with undo.
        val page = device.wait(Until.findObject(By.res(Pattern.compile("viewer:page:.*"))), 5_000) ?: failWithScreen("no viewer page")
        val current = page.resourceName.removePrefix("viewer:page:")
        if (device.findObject(By.desc("Añadir a favoritos")) == null) device.click(device.displayWidth / 2, device.displayHeight / 2)
        waitDesc("Añadir a favoritos").click()
        waitDesc("Quitar de favoritos")
        assertTrue(asset(endpoint, current)["favorite"]!!.jsonPrimitive.boolean)
        waitDesc("Eliminar").click()
        device.wait(Until.findObject(By.text("Deshacer")), 5_000)!!.click()
        device.waitForIdle()
        Thread.sleep(1_000)
        assertFalse("undo restored it from the trash", current in trashIds(endpoint))

        // Back to the grid; open the video and seek while it streams through Range requests.
        device.pressBack()
        waitRes("photos:grid")
        // The grid came back on the last viewed photo (deep in the timeline): fling to the top, where the video is.
        val gridAgain = waitRes("photos:grid")
        repeat(12) { if (device.findObject(By.res("photos:tile:$videoId")) == null) gridAgain.fling(Direction.UP, 8_000) }
        val video = device.wait(Until.findObject(By.res("photos:tile:$videoId")), 10_000) ?: error("video tile missing")
        video.click()
        waitRes("viewer:video-controls", 10_000)
        val scrubber = waitRes("viewer:scrubber")
        Thread.sleep(1_500)
        val bounds = scrubber.visibleBounds
        device.click(bounds.left + bounds.width() * 7 / 10, bounds.centerY())
        Thread.sleep(800)
        assertNotNull("controls stay after seeking", device.findObject(By.res("viewer:video-controls")))
        Log.i("BentoJourney", "journey 7 passed; opened $openedId, video $videoId")
    }

    /** Journey 2 (Fotos part): something uploaded elsewhere shows up in the open grid in <= 10 s. */
    @Test
    fun journey2_newPhotoAppearsInGrid() {
        BentoDevice.forceStop()
        val endpoint = BentoDevice.ready()
        waitRes("photos:grid", 60_000)
        val dir = File(InstrumentationRegistry.getInstrumentation().context.cacheDir, "j2").apply { mkdirs() }
        val bytes = LibrarySeeder.jpeg(900_000 + (System.currentTimeMillis() % 100_000).toInt(), dir, java.time.LocalDateTime.now())
        val id = BentoDevice.upload(endpoint, "Desde el computador.jpg", "image/jpeg", bytes)["id"]!!.jsonPrimitive.content
        // The file is in the vault now (another device would have uploaded and synced it): the clock starts here.
        val started = System.currentTimeMillis()
        waitRes("photos:grid").scroll(Direction.UP, 50f)
        val shown = device.wait(Until.findObject(By.res("photos:tile:$id")), 10_000)
        Log.i("BentoJourney", "journey 2: new photo visible after ${System.currentTimeMillis() - started} ms")
        if (shown == null) runCatching { failWithScreen("journey 2 new photo missing") }
        assertNotNull("the new photo appears within 10 s", shown)
    }

    /**
     * Journey 1 (Fotos part): with phone backup on for the camera folder, photos taken on the phone show in Fotos.
     * Pushes 3 JPEGs into DCIM/Camera, enables the MediaStore source through the API and waits for the tiles.
     */
    @Test
    fun journey1_cameraRollShowsInFotos() {
        BentoDevice.forceStop()
        BentoDevice.shell("pm grant ${BentoDevice.PACKAGE} android.permission.READ_MEDIA_IMAGES")
        BentoDevice.shell("pm grant ${BentoDevice.PACKAGE} android.permission.READ_MEDIA_VIDEO")
        // The shell can read the test's media dir (not its private cache) to copy into DCIM.
        val dir = InstrumentationRegistry.getInstrumentation().context.externalMediaDirs.first().apply { mkdirs() }
        val stamp = System.currentTimeMillis() % 1_000_000
        val names = (0 until 3).map { "IMG_J1_${stamp}_$it.jpg" }
        names.forEachIndexed { i, name ->
            val local = File(dir, name).apply { writeBytes(LibrarySeeder.jpeg(800_000 + stamp.toInt() + i, dir, java.time.LocalDateTime.now())) }
            BentoDevice.shell("mkdir -p /sdcard/DCIM/Camera")
            BentoDevice.shell("cp ${local.absolutePath} /sdcard/DCIM/Camera/$name")
        }
        // API 29+: the scan broadcast is gone; ask MediaProvider to scan the volume.
        BentoDevice.shell("content call --uri content://media --method scan_volume --arg external_primary")
        Thread.sleep(2_000)
        val endpoint = BentoDevice.ready()
        val suggestions = BentoDevice.call(endpoint, "GET", "/api/backup/suggestions")["items"]?.jsonArray.orEmpty()
        val camera = suggestions.map { it.jsonObject }.firstOrNull { it["name"]?.jsonPrimitive?.content?.contains("Camera", ignoreCase = true) == true }
        assertNotNull("MediaStore lists the Camera bucket: $suggestions", camera)
        val bucket = camera!!["id"]!!.jsonPrimitive.content
        val source = runCatching { BentoDevice.call(endpoint, "POST", "/api/backup/sources", "{\"kind\":\"media_store\",\"bucket_id\":\"$bucket\"}") }.getOrNull()
        val sourceId = source?.get("id")?.jsonPrimitive?.content
            ?: BentoDevice.call(endpoint, "GET", "/api/backup/sources")["items"]!!.jsonArray.map { it.jsonObject }
                .first { it["bucket_id"]?.jsonPrimitive?.content == bucket }["id"]!!.jsonPrimitive.content
        val started = System.currentTimeMillis()
        BentoDevice.call(endpoint, "POST", "/api/backup/sources/$sourceId/scan")
        waitRes("photos:grid", 60_000)
        var found = false
        while (System.currentTimeMillis() - started < 30_000 && !found) {
            found = device.findObjects(By.res(tile)).any { true } &&
                BentoDevice.call(endpoint, "GET", "/api/photos/timeline?limit=50")["groups"]!!.jsonArray
                    .flatMap { it.jsonObject["assets"]!!.jsonArray }.any { it.jsonObject["filename"]!!.jsonPrimitive.content in names }
            if (!found) Thread.sleep(250)
        }
        Log.i("BentoJourney", "journey 1: camera photos in the timeline after ${System.currentTimeMillis() - started} ms")
        assertTrue("camera roll photos reach Fotos", found)
    }

    /** Journey 5 (Fotos part): with partial media access, Fotos explains it with a calm card. */
    @Test
    fun journey5_partialAccessCard() {
        BentoDevice.forceStop()
        BentoDevice.shell("pm revoke ${BentoDevice.PACKAGE} android.permission.READ_MEDIA_IMAGES")
        BentoDevice.shell("pm revoke ${BentoDevice.PACKAGE} android.permission.READ_MEDIA_VIDEO")
        BentoDevice.shell("pm grant ${BentoDevice.PACKAGE} android.permission.READ_MEDIA_VISUAL_USER_SELECTED")
        val endpoint = BentoDevice.ready()
        val status = BentoDevice.call(endpoint, "GET", "/api/backup/status")
        Log.i("BentoJourney", "journey 5: backup status $status")
        waitRes("photos:grid", 60_000)
        val card = device.wait(Until.findObject(By.textStartsWith("Bento solo ve")), 15_000)
        BentoDevice.shell("pm grant ${BentoDevice.PACKAGE} android.permission.READ_MEDIA_IMAGES")
        if (card == null) runCatching { failWithScreen("no partial access card") }
        assertNotNull("partial access card (backend partial_access=${status["partial_access"]})", card)
    }

    /** The same screens in English (per-app language), then back to Spanish. */
    @Test
    fun englishLocale() {
        BentoDevice.forceStop()
        BentoDevice.shell("cmd locale set-app-locales ${BentoDevice.PACKAGE} --locales en-US")
        try {
            BentoDevice.ready()
            waitRes("photos:grid", 60_000)
            assertNotNull(device.wait(Until.findObject(By.text("Photos")), 5_000))
            assertNotNull(device.wait(Until.findObject(By.text("Collections")), 5_000))
            device.findObject(By.text("Collections")).click()
            assertNotNull(device.wait(Until.findObject(By.text("Favorites")), 5_000))
            assertNotNull(device.findObject(By.text("Trash")))
        } finally {
            BentoDevice.shell("cmd locale set-app-locales ${BentoDevice.PACKAGE} --locales es-ES")
        }
    }
}
