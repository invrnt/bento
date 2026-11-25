package dev.bento.background

import android.app.Notification
import android.content.Context
import android.content.Intent
import android.service.quicksettings.Tile
import androidx.core.app.NotificationCompat
import androidx.test.core.app.ApplicationProvider
import dev.bento.engine.bridge.EngineEvent
import java.io.File
import javax.xml.parsers.DocumentBuilderFactory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

/** Notification content and actions for every Notifier event (product/android.md §8; agent 41). */
@RunWith(RobolectricTestRunner::class)
@Config(qualifiers = "es")
class NotificationsTest {
    private val context: Context = ApplicationProvider.getApplicationContext()

    @Before
    fun setUp() {
        BentoNotifications.launchIntent = { Intent(Intent.ACTION_MAIN).setPackage(it.packageName) }
    }

    private fun Notification.title() = extras.getCharSequence(NotificationCompat.EXTRA_TITLE)?.toString()

    private fun Notification.text() = extras.getCharSequence(NotificationCompat.EXTRA_TEXT)?.toString()

    private fun Notification.target(): OpenTarget? =
        OpenTargets.decode(shadowOf(contentIntent).savedIntent.getStringExtra(OpenTargets.EXTRA))

    private fun Notification.actionTitles() = actions.orEmpty().map { it.title.toString() }

    @Test
    fun transferProgressIsOneOngoingSilentNotificationWithPause() {
        val n = BentoNotifications.transfer(
            context,
            EngineEvent.TransferProgress(EngineEvent.TransferKind.BACKUP, 1240, 18000, 12_000_000, 40_000_000, false)
        )
        assertEquals("Respaldando fotos", n.title())
        assertEquals("1.240 de 18.000 archivos", n.text())
        assertEquals(NotificationCompat.CATEGORY_PROGRESS, n.category)
        assertTrue(n.flags and Notification.FLAG_ONGOING_EVENT != 0)
        assertEquals(BentoNotifications.CHANNEL_TRANSFERS, n.channelId)
        assertEquals(listOf("Pausar"), n.actionTitles())
        assertEquals(OpenTarget.Activity, n.target())
        assertEquals(300, n.extras.getInt(NotificationCompat.EXTRA_PROGRESS))
    }

    @Test
    fun pausedTransferOffersResume() {
        val n = BentoNotifications.transfer(context, EngineEvent.TransferProgress(EngineEvent.TransferKind.IMPORT, 1, 3, 0, 0, true))
        assertEquals("Importando archivos", n.title())
        assertEquals("En pausa", n.text())
        assertEquals(listOf("Reanudar"), n.actionTitles())
        assertEquals(TransferActionReceiver.ACTION_RESUME, shadowOf(n.actions.single().actionIntent).savedIntent.action)
    }

    @Test
    fun preparingWhenNothingIsKnownYet() {
        val n = BentoNotifications.transfer(context, null)
        assertEquals("Preparando…", n.text())
        assertTrue(n.extras.getBoolean(NotificationCompat.EXTRA_PROGRESS_INDETERMINATE))
    }

    @Test
    fun transferFinishedSummaryOpensBackup() {
        val n = BentoNotifications.backupSummary(context, 18000)
        assertEquals("Listo: 18.000 fotos respaldadas", n.title())
        assertEquals(OpenTarget.Backup, n.target())
        assertTrue(n.flags and Notification.FLAG_AUTO_CANCEL != 0)
    }

    @Test
    fun attentionHasOneActionAndTheRightDestinationPerCode() {
        val cases = mapOf(
            "session_revoked" to Triple("Bento se desconectó de Telegram", "Volver a conectar", OpenTarget.Reconnect),
            "recovery_kit" to Triple("Guarda tu kit de recuperación", "Guardar kit", OpenTarget.Recovery),
            "device_removed" to Triple("Este teléfono se quitó de tu nube", "Revisar", OpenTarget.DeviceRemoved),
            "storage_full" to Triple("El teléfono no tiene espacio", "Liberar espacio", OpenTarget.Storage),
            "new_device" to Triple("Se añadió un dispositivo a tu nube", "Revisar", OpenTarget.Devices),
            "something_new" to Triple("Bento necesita tu atención", "Revisar", OpenTarget.Activity)
        )
        cases.forEach { (code, expected) ->
            val n = BentoNotifications.attention(context, code, 1)
            assertEquals(code, expected.first, n.title())
            assertEquals(code, listOf(expected.second), n.actionTitles())
            assertEquals(code, expected.third, n.target())
            assertEquals(BentoNotifications.CHANNEL_ATTENTION, n.channelId)
        }
        assertEquals("3 archivos no se pudieron subir", BentoNotifications.attention(context, "upload_failed", 3).title())
    }

    @Test
    fun pairingRequestAndNewDeviceOpenTheirReview() {
        val request = BentoNotifications.pairingRequest(context, "req_1", "Pixel 9")
        assertEquals("Un dispositivo nuevo quiere unirse", request.title())
        assertEquals("«Pixel 9» pide unirse a tu nube. Toca para revisarlo.", request.text())
        assertEquals(OpenTarget.PairingRequest("req_1"), request.target())
        assertEquals(BentoNotifications.CHANNEL_DEVICES, request.channelId)
        val added = BentoNotifications.deviceAdded(context, "d_9", "Portátil de Ana")
        assertEquals("Se añadió «Portátil de Ana»", added.title())
        assertEquals(OpenTarget.DeviceReview("d_9"), added.target())
        assertEquals(listOf("Revisar"), added.actionTitles())
    }

    @Test
    fun englishCopy() {
        val en = context.createConfigurationContext(
            android.content.res.Configuration(context.resources.configuration).apply {
                setLocale(java.util.Locale.ENGLISH)
            }
        )
        assertEquals("Save your recovery kit", BentoNotifications.attention(en, "recovery_kit", 1).title())
        assertEquals(
            "1 of 3 files",
            NotificationContent.transfer(en, EngineEvent.TransferProgress(EngineEvent.TransferKind.UPLOAD, 1, 3, 0, 0, false)).text
        )
    }
}

class OpenTargetsTest {
    @Test
    fun encodeDecodeRoundTrip() {
        val all = listOf(
            OpenTarget.Activity, OpenTarget.Backup, OpenTarget.Storage, OpenTarget.Recovery, OpenTarget.Reconnect, OpenTarget.Devices,
            OpenTarget.DeviceRemoved, OpenTarget.Search, OpenTarget.AddDevice,
            OpenTarget.PairingRequest(
                "req_1"
            ),
            OpenTarget.DeviceReview("d-9")
        )
        all.forEach { assertEquals(it, OpenTargets.decode(OpenTargets.encode(it))) }
    }

    @Test
    fun malformedValuesOpenNothing() {
        assertNull(OpenTargets.decode(null))
        assertNull(OpenTargets.decode("pairing_request:"))
        assertNull(OpenTargets.decode("device_review:../../x"))
        assertNull(OpenTargets.decode("settings"))
    }

    @Test
    fun shortcutsAndTilePreferences() {
        assertEquals(OpenTarget.Search, OpenTargets.from(OpenTargets.ACTION_SEARCH, null))
        assertEquals(OpenTarget.AddDevice, OpenTargets.from(OpenTargets.ACTION_ADD_DEVICE, null))
        assertEquals(OpenTarget.Backup, OpenTargets.from(OpenTargets.ACTION_QS_TILE_PREFERENCES, null))
        assertEquals(OpenTarget.Recovery, OpenTargets.from("android.intent.action.MAIN", "recovery"))
    }

    @Test
    fun attentionTopics() {
        assertEquals(AttentionTopic.SignIn, AttentionTopic.of("session_revoked"))
        assertEquals(AttentionTopic.UploadFailed, AttentionTopic.of("upload_failed"))
        assertEquals(AttentionTopic.Generic, AttentionTopic.of("clock_skew"))
    }

    @Test
    fun tileStates() {
        assertEquals(Tile.STATE_UNAVAILABLE, TileLook.state(null))
        assertEquals(Tile.STATE_UNAVAILABLE, TileLook.state(BackupTileState(enabled = false, paused = false, subtitle = null)))
        assertEquals(Tile.STATE_INACTIVE, TileLook.state(BackupTileState(enabled = true, paused = true, subtitle = "x")))
        assertEquals(Tile.STATE_ACTIVE, TileLook.state(BackupTileState(enabled = true, paused = false, subtitle = "x")))
    }
}

/** Debug builds must keep the kitchen sink and every real shortcut; release builds must not have the kitchen sink. */
class ShortcutsTest {
    private fun ids(path: String): List<String> {
        val doc = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(File(path))
        val nodes = doc.getElementsByTagName("shortcut")
        return (0 until nodes.length).map { (nodes.item(it) as org.w3c.dom.Element).getAttribute("android:shortcutId") }
    }

    @Test
    fun releaseHasTheFourProductShortcutsAndDebugAddsTheKitchenSink() {
        val release = ids("src/main/res/xml/bento_shortcuts.xml")
        assertEquals(listOf("search", "upload_photos", "scan_document", "add_device"), release)
        assertEquals(release + "kitchen_sink", ids("../../app/src/debug/res/xml/bento_shortcuts.xml"))
    }

    @Test
    fun debugEntriesAreIdenticalToRelease() {
        val main = File("src/main/res/xml/bento_shortcuts.xml").readText()
        val debug = File("../../app/src/debug/res/xml/bento_shortcuts.xml").readText()
        val body = Regex("<shortcut\\b[\\s\\S]*?</shortcut>")
        assertEquals(body.findAll(main).map { it.value }.toList(), body.findAll(debug).map { it.value }.toList().dropLast(1))
    }
}
