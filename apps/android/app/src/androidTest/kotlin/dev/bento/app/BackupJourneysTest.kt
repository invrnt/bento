package dev.bento.app

import android.Manifest
import android.app.NotificationManager
import android.content.ContentUris
import android.content.ContentValues
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import android.util.Log
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import dev.bento.app.navigation.Route
import dev.bento.background.BentoNotifications
import dev.bento.data.Invalidations
import dev.bento.engine.EngineHolder
import dev.bento.engine.di.PlatformEntryPoint
import dev.bento.feature.settings.BackupRepository
import dev.bento.feature.settings.BackupStatus
import dev.bento.feature.settings.PhoneSettings
import java.util.regex.Pattern
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Phone backup, background, free-up-space and app-lock journeys (testing/android-journeys.md 1 (camera-roll part), 10,
 * 11, 12, 16) on the emulator with the real embedded engine and a fresh remote fake cloud per journey
 * (`feature/settings/e2e/run_journeys.sh`). Each journey starts from a cleared app and creates a new cloud.
 */
@RunWith(AndroidJUnit4::class)
class BackupJourneysTest {
    @get:Rule
    val compose = createEmptyComposeRule()

    /** Media access is granted up front: the denial paths are covered by JVM/Compose tests (BackupViewModelTest). */
    @get:Rule
    val permissions: GrantPermissionRule = if (Build.VERSION.SDK_INT >= 33) {
        GrantPermissionRule.grant(
            Manifest.permission.POST_NOTIFICATIONS,
            Manifest.permission.READ_MEDIA_IMAGES,
            Manifest.permission.READ_MEDIA_VIDEO,
            Manifest.permission.ACCESS_MEDIA_LOCATION
        )
    } else {
        GrantPermissionRule.grant(Manifest.permission.READ_EXTERNAL_STORAGE, Manifest.permission.ACCESS_MEDIA_LOCATION)
    }

    private val journey = Journey(compose)
    private val context = journey.context
    private val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
    private val engine = PlatformEntryPoint.get(context).engine()
    private val backup = BackupRepository(journey.phone, Invalidations())
    private val run = java.lang.Long.toString(System.currentTimeMillis() % 1_000_000, 36)
    private val inserted = mutableListOf<Uri>()

    @After
    fun close() {
        shell("svc wifi enable")
        shell("locksettings clear --old $PIN")
        journey.scenario?.close()
        inserted.forEach { runCatching { context.contentResolver.delete(it, null, null) } }
    }

    // Journeys ------------------------------------------------------------------------------------------------

    /** 1 (camera-roll part): backup on with full media access in onboarding; Wi-Fi uploads, metered waits for Wi-Fi. */
    @Test
    fun j01_firstRunBackupOn() {
        insertPhotos(6)
        firstRun(backupOn = true)
        val sources = runBlocking { backup.sources() }
        val buckets = runBlocking { backup.buckets() }
        assertTrue(
            "Camera folder on: sources=$sources buckets=$buckets",
            sources.any {
                it.kind == "media_store" && it.enabled &&
                    it.label?.equals("Camera", true) == true
            }
        )
        assertTrue("Solo con Wi-Fi is on by default", PhoneSettings.parse(runBlocking { journey.phone.settingsValues() }).wifiOnly)
        // The camera roll is in the library (local-first) and uploads on Wi-Fi.
        eventually("6 camera photos in the timeline", 60_000) { timelineCount() >= 6 }
        val done = eventually("uploaded on Wi-Fi", 180_000) { status().takeIf { it.pending == 0 } }
        assertTrue(done.uploadedToday >= 6)
        // Metered network: new photos wait for Wi-Fi and Ajustes › Respaldo says so.
        shell("svc wifi disable")
        Thread.sleep(3_000) // the engine hears the network change through the conditions bridge
        insertPhotos(2)
        eventually("waiting for Wi-Fi", 120_000) { (status().waiting["wifi"] ?: 0) > 0 }
        journey.navigate(Route.Settings("Backup"))
        journey.waitText("esperando Wi-Fi", 60_000, substring = true)
        journey.capture("j01-backup-waiting-wifi")
        shell("svc wifi enable")
        eventually("uploaded once Wi-Fi is back", 180_000) { status().pending == 0 }
        journey.waitText("Todo respaldado ✓", 60_000, substring = true)
        journey.capture("j01-backup-done")
    }

    /** 10. App closed, 30 new photos → backed up by the next background run on Wi-Fi; metered → waits for Wi-Fi. */
    @Test
    fun j10_backgroundBackup() {
        firstRun(backupOn = true) { insertPhotos(1) }
        eventually("backup idle", 120_000) { status().pending == 0 }
        journey.scenario?.close()
        journey.scenario = null
        val sawBackgroundRun = java.util.concurrent.atomic.AtomicBoolean(false)
        val watcher = Thread {
            while (!Thread.currentThread().isInterrupted) {
                if (engine.activeHolders().any { it is EngineHolder.Work && it.name == "backup" }) sawBackgroundRun.set(true)
                runCatching { Thread.sleep(100) }.onFailure { return@Thread }
            }
        }.apply { start() }
        insertPhotos(30)
        try {
            eventually("a background backup run (content trigger)", 180_000) { sawBackgroundRun.get() }
            eventually("the background run finished", 300_000) {
                engine.activeHolders().none {
                    it is EngineHolder.Work &&
                        it.name == "backup"
                }
            }
        } finally {
            watcher.interrupt()
        }
        engine.acquire(EngineHolder.Work("journey-check")).use {
            val after = status()
            Log.i(TAG, "j10 after background run: pending=${after.pending} today=${after.uploadedToday}")
            assertEquals("30 photos uploaded by the background run", 0, after.pending)
        }
        // Metered: the next background run defers uploads and reports "esperando Wi-Fi".
        shell("svc wifi disable")
        Thread.sleep(3_000)
        sawBackgroundRun.set(false)
        insertPhotos(3)
        engine.acquire(EngineHolder.Work("journey-check")).use {
            eventually("waiting for Wi-Fi", 300_000) { (status().waiting["wifi"] ?: 0) > 0 }
        }
    }

    /** 11. Initial backup of an existing roll as a user-initiated transfer with its notification; stopped mid-way, resumes. */
    @Test
    fun j11_initialBackup() {
        // The roll exists before backup is turned on (inserted on the backup step: 120 inserts during sign-in made the
        // emulator miss the sign-in field).
        firstRun(backupOn = true) { insertPhotos(INITIAL) }
        val notifications = context.getSystemService(NotificationManager::class.java)
        eventually("the transfer notification", 120_000) {
            notifications.activeNotifications.any { it.id == BentoNotifications.ID_TRANSFER }
        }
        val progress = eventually("progress mid-way", 300_000) { status().takeIf { it.uploadedToday in 1 until INITIAL } }
        journey.captureNotifications("j11-transfer-notification")
        // A reboot cannot run inside instrumentation: the system stopping the job mid-way is the closest (uploads
        // resume at part granularity from the upload sessions either way).
        dev.bento.background.TransferScheduler.stop(context)
        Log.i(TAG, "j11 stopped at ${progress.uploadedToday}/$INITIAL")
        journey.navigate(Route.Settings("Backup"))
        journey.waitText("Respaldar ahora", 60_000)
        compose.onNode(hasText("Respaldar ahora") and hasClickAction()).performScrollTo().performClick()
        eventually("resumed to the end", 600_000) { status().pending == 0 }
        assertTrue(status().uploadedToday >= INITIAL)
        eventually("completion summary", 120_000) {
            notifications.activeNotifications.any { it.id == BentoNotifications.ID_TRANSFER_SUMMARY }
        }
        journey.captureNotifications("j11-summary")
    }

    /** 12. Free up space: only verified items are listed, the system delete request removes them, the timeline stays. */
    @Test
    fun j12_freeUpSpace() {
        val uris = insertPhotos(5)
        firstRun(backupOn = true)
        eventually("all uploaded", 240_000) { status().pending == 0 }
        val before = timelineCount()
        val preview = eventually("verified items", 120_000) { runBlocking { backup.freeUpPreview() }.takeIf { it.count >= 5 } }
        journey.navigate(Route.Settings("Backup"))
        journey.waitText("Liberar espacio", 60_000)
        compose.onNode(hasText("Liberar espacio") and hasClickAction()).performScrollTo().performClick()
        journey.waitText("ya están en tu nube", 60_000, substring = true)
        journey.capture("j12-preview")
        compose.onNode(
            hasText("en este teléfono", substring = true) and hasText("Liberar", substring = true) and hasClickAction()
        ).performClick()
        // The system's own confirmation (MediaStore.createDeleteRequest).
        val allow = device.wait(Until.findObject(By.text(Pattern.compile("(?i)^(permitir|allow)$"))), 30_000)
        device.takeScreenshot(
            java.io.File(context.getExternalFilesDir(null), "journeys/j12-system-request.png").apply {
                parentFile?.mkdirs()
            }
        )
        allow.click()
        journey.waitText("Listo: se liberaron", 60_000, substring = true)
        journey.capture("j12-done")
        uris.forEach { uri ->
            val gone =
                context.contentResolver.query(uri, arrayOf(MediaStore.MediaColumns._ID), null, null, null)?.use { it.count == 0 } ?: true
            assertTrue("$uri removed from the phone", gone)
        }
        assertEquals("timeline unchanged", before, timelineCount())
        assertTrue(preview.count >= uris.size)
    }

    /** 16. App lock: device-credential gate, locked on return, background sync continues while locked. */
    @Test
    fun j16_appLock() {
        shell("locksettings set-pin $PIN")
        // An empty roll has no Camera bucket to enable yet (see the handoff): the phone has one photo already.
        firstRun(backupOn = true) { insertPhotos(1) }
        journey.navigate(Route.Settings("General"))
        journey.tap("Huella, rostro o el PIN del teléfono.")
        enterPin()
        journey.waitText("Al salir", 30_000) // timeouts appear once the lock is on
        journey.capture("j16-lock-on")
        device.pressHome()
        Thread.sleep(1_500)
        journey.scenario!!.onActivity {
            it.startActivity(
                android.content.Intent(it, MainActivity::class.java).addFlags(android.content.Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
            )
        }
        journey.waitText("Bento está bloqueado", 30_000)
        assertFalse("the library is not composed while locked", compose.onAllNodes(hasText("Archivos")).fetchSemanticsNodes().isNotEmpty())
        device.wait(Until.hasObject(By.pkg("com.android.systemui")), 5_000)
        device.takeScreenshot(java.io.File(context.getExternalFilesDir(null), "journeys/j16-locked.png").apply { parentFile?.mkdirs() })
        // Background sync keeps working while locked.
        insertPhotos(2)
        eventually("uploads continue while locked", 360_000) { status().let { it.pending == 0 && it.uploadedToday >= 3 } }
        enterPin()
        journey.waitText("Bloqueo de la app", 30_000)
    }

    /** English copy of Ajustes, Respaldo and the account sheet (run with APP_LOCALE=en-US). */
    @Test
    fun j91_englishSettings() {
        firstRun(backupOn = false, notNow = "Not now", later = "Later", goToPhotos = "Go to my photos", library = "Files")
        journey.navigate(Route.Settings())
        journey.waitText("Phone backup", 60_000)
        journey.capture("en-settings-home")
        journey.tap("Phone backup")
        journey.waitText("Backup is off", 60_000)
        journey.capture("en-settings-backup")
        journey.navigate(Route.Files())
        journey.waitFor(hasContentDescription("Your account", substring = true).or(hasContentDescription("Ana", substring = true)), 30_000)
        journey.capture("en-files-avatar")
    }

    // Steps ---------------------------------------------------------------------------------------------------

    private fun firstRun(
        backupOn: Boolean,
        notNow: String = "Ahora no",
        later: String = "Más tarde",
        goToPhotos: String = "Ir a mis fotos",
        library: String = "Archivos",
        beforeBackup: () -> Unit = {}
    ) {
        journey.launch()
        journey.waitText(if (notNow == "Ahora no") "Empezar" else "Get started", 90_000)
        journey.tap(if (notNow == "Ahora no") "Empezar" else "Get started")
        try {
            if (notNow == "Ahora no") journey.signInWithPhone() else signInEnglish()
        } catch (failure: AssertionError) {
            journey.capture("failure-sign-in")
            throw failure
        }
        if (backupOn) {
            journey.waitText("Respalda este teléfono", 180_000)
            journey.capture("backup-setup")
            beforeBackup()
            journey.tap("Respaldar fotos")
        } else {
            journey.tap(notNow, 90_000)
        }
        journey.tap(later, 60_000)
        journey.tap(goToPhotos, 30_000)
        journey.waitText(library, 60_000)
    }

    private fun signInEnglish() {
        journey.tap("Use my phone number")
        journey.type("Phone number", "3001234567")
        journey.tap("Send code")
        if (runCatching { journey.waitText("Enter the code", 20_000) }.isSuccess) journey.type("Telegram code", Journey.FAKE_CODE)
    }

    private fun enterPin() {
        device.wait(Until.hasObject(By.pkg("com.android.systemui")), 15_000)
        Thread.sleep(800)
        shell("input text $PIN")
        shell("input keyevent 66")
        Thread.sleep(1_500)
    }

    // Helpers -------------------------------------------------------------------------------------------------

    private fun status(): BackupStatus = runBlocking { backup.status() }

    private fun timelineCount(): Int = runBlocking { journey.phone.photosTimeline(limit = 500).groups.sumOf { it.assets.size } }

    private fun shell(command: String): String = InstrumentationRegistry.getInstrumentation().uiAutomation.executeShellCommand(
        command
    ).use { fd ->
        android.os.ParcelFileDescriptor.AutoCloseInputStream(fd).bufferedReader().readText()
    }

    /** Unique JPEGs (distinct bytes, so no dedup) in `DCIM/Camera`, the default "Camera" bucket. */
    private fun insertPhotos(count: Int): List<Uri> = (1..count).map { index ->
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, "IMG_${run}_${inserted.size + 1}.jpg")
            put(MediaStore.MediaColumns.MIME_TYPE, "image/jpeg")
            put(MediaStore.MediaColumns.RELATIVE_PATH, "DCIM/Camera/")
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val uri = context.contentResolver.insert(MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY), values)!!
        val bitmap = Bitmap.createBitmap(320, 240, Bitmap.Config.ARGB_8888)
        Canvas(bitmap).apply {
            drawColor(Color.rgb((index * 37) % 255, (index * 91) % 255, (inserted.size * 53) % 255))
            drawText("$run #${inserted.size + 1}", 20f, 120f, Paint().apply { textSize = 32f })
        }
        context.contentResolver.openOutputStream(uri)!!.use { bitmap.compress(Bitmap.CompressFormat.JPEG, 90, it) }
        context.contentResolver.update(uri, ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }, null, null)
        inserted += uri
        ContentUris.withAppendedId(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, ContentUris.parseId(uri))
    }

    private fun <T : Any> eventually(what: String, timeoutMs: Long = 60_000, probe: () -> T?): T {
        val deadline = System.currentTimeMillis() + timeoutMs
        var last: Throwable? = null
        while (System.currentTimeMillis() < deadline) {
            val value = runCatching(probe).onFailure { last = it }.getOrNull()
            if (value != null && value != false) return value
            Thread.sleep(500)
        }
        throw AssertionError("Timed out waiting for $what", last)
    }

    private companion object {
        const val TAG = "BentoJourney"
        const val PIN = "1234"
        const val INITIAL = 120
    }
}

/** Notification shade screenshot for the visual record (UIDT progress, completion summary). */
internal fun Journey.captureNotifications(name: String) {
    val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
    device.openNotification()
    Thread.sleep(1_200)
    val dir = java.io.File(context.getExternalFilesDir(null), "journeys").apply { mkdirs() }
    device.takeScreenshot(java.io.File(dir, "$name.png"))
    device.pressBack()
}
