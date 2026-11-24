package dev.bento.feature.share

import android.content.ClipData
import android.content.Intent
import android.net.Uri
import androidx.core.content.pm.ShortcutManagerCompat
import dev.bento.api.BentoJson
import dev.bento.api.generated.BentoInterfacesHttpRoutesAndroidImportRequest
import dev.bento.data.DriveRepository
import dev.bento.data.Invalidations
import dev.bento.data.UiCache
import dev.bento.feature.files.ContentHandles
import dev.bento.feature.files.Destination
import dev.bento.feature.files.FilesRepository
import dev.bento.feature.files.ImportFailureLog
import dev.bento.feature.files.InMemoryFilesPreferences
import dev.bento.feature.files.TransferControl
import dev.bento.feature.files.UploadCoordinator
import dev.bento.testing.FakeApiTransport
import dev.bento.testing.MainDispatcherRule
import java.nio.file.Files
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class ShareTest {
    @get:Rule
    val main = MainDispatcherRule()

    private val tmp = Files.createTempDirectory("share").toFile()
    private val preferences = InMemoryFilesPreferences(recent = listOf(Destination("f_last", "Recibos")))
    private val failures = ImportFailureLog(tmp)
    private val published = mutableListOf<List<Destination>>()
    private val notes = mutableMapOf<String, String>()

    // Intents ------------------------------------------------------------------------------------------------------

    @Test
    fun singleStream() {
        val intent = Intent(Intent.ACTION_SEND).setType("image/jpeg").putExtra(Intent.EXTRA_STREAM, Uri.parse("content://photos/1"))
        assertEquals(listOf(SharedItem("content://photos/1", "image/jpeg")), ShareIntents.parse(intent).items)
    }

    @Test
    fun multipleStreamsWithMixedMime() {
        val uris =
            arrayListOf(Uri.parse("content://p/1"), Uri.parse("content://p/2"), Uri.parse("content://p/3"), Uri.parse("content://docs/9"))
        val intent = Intent(Intent.ACTION_SEND_MULTIPLE).setType("*/*").putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris)
        val payload = ShareIntents.parse(intent)
        assertEquals(4, payload.items.size)
        // A wildcard type says nothing per item: each item's type comes from its provider.
        assertTrue(payload.items.all { it.declaredMime == null })
    }

    @Test
    fun clipDataFallbackAndFileUrisRefused() {
        val intent = Intent(Intent.ACTION_SEND_MULTIPLE).setType("image/*")
        intent.clipData = ClipData.newRawUri(null, Uri.parse("content://p/1")).apply {
            addItem(ClipData.Item(Uri.parse("file:///data/data/dev.bento.app/databases/bento.db")))
            addItem(ClipData.Item(Uri.parse("content://p/1")))
        }
        assertEquals(listOf("content://p/1"), ShareIntents.parse(intent).items.map { it.uri })
    }

    @Test
    fun textAloneIsANoteAndDirectShareFolder() {
        val intent = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, "https://bento.example/blog\nleer luego")
            .putExtra(ShortcutManagerCompat.EXTRA_SHORTCUT_ID, "folder:f_work")
        val payload = ShareIntents.parse(intent)
        assertTrue(payload.noteOnly)
        assertEquals("f_work", payload.shortcutFolderId)
    }

    @Test
    fun viewIntentImports() {
        val payload = ShareIntents.parse(Intent(Intent.ACTION_VIEW).setDataAndType(Uri.parse("content://dl/7"), "application/pdf"))
        assertEquals(listOf(SharedItem("content://dl/7", "application/pdf")), payload.items)
        assertTrue(ShareIntents.parse(Intent(Intent.ACTION_VIEW).setData(Uri.parse("https://x"))).empty)
        assertTrue(ShareIntents.parse(null).empty)
    }

    // ViewModel ----------------------------------------------------------------------------------------------------

    private val api = FakeApiTransport().apply {
        on("POST /api/android/imports") { """{"import_id":"imp","done":true,"counts":{},"items":[]}""" }
        on("GET /api/android/imports/imp") { """{"import_id":"imp","done":true,"counts":{},"items":[]}""" }
        on("GET /api/photos/albums") {
            """{"items":[{"id":"al1","title":"Cartagena","asset_ids":[],""" +
                """"created_at":"2026-01-01T00:00:00+00:00","updated_at":"2026-01-01T00:00:00+00:00"}],"next_cursor":null}"""
        }
    }

    /** Names as other apps report them; `content://gone/…` behaves like a revoked grant. */
    private val providerNames = mapOf(
        "content://p/1" to ("../../../shared_prefs/bento.xml" to "image/jpeg"),
        "content://p/2" to ("IMG‮gpj.exe" to "image/png"),
        "content://p/3" to ("Foto 3.heic" to "image/heic"),
        "content://docs/9" to ("Contrato\u0000.pdf" to "application/pdf")
    )

    private val describer = ContentDescriber { item ->
        val entry = providerNames[item.uri]
        if (entry == null) {
            SharedDescription(item.uri, "gone", "application/octet-stream", null, readable = false)
        } else {
            SharedDescription(item.uri, dev.bento.feature.files.DisplayNames.file(entry.first), entry.second, 6_000_000, readable = true)
        }
    }

    private val handles = object : ContentHandles {
        var next = 1L

        override fun register(uri: String): ContentHandles.Registered {
            if (uri.startsWith("content://gone")) throw SecurityException("revoked")
            return ContentHandles.Registered(next++, providerNames[uri]?.first ?: "note", "x", 1)
        }
    }

    private fun TestScope.vm(slowImports: Boolean = false): ShareViewModel {
        if (slowImports) {
            api.on("POST /api/android/imports") {
                Thread.sleep(1_000).let { """{"import_id":"imp","done":true,"counts":{},"items":[]}""" }
            }
        }
        val endpoints = api.endpoints()
        val cache = UiCache(tmp, "1")
        val files =
            FilesRepository(endpoints, null, DriveRepository(endpoints, Invalidations(), cache, backgroundScope), Invalidations(), cache)
        val transfers = object : TransferControl {
            override fun start(estimatedBytes: Long) = Unit

            override fun stop() = Unit
        }
        val uploads = UploadCoordinator(endpoints, handles, transfers, failures, Invalidations(), backgroundScope, pollMs = 10)
        return ShareViewModel(
            describer,
            uploads,
            preferences,
            files,
            endpoints,
            { name, text -> "file:///cache/notes/$name".also { notes[name] = text } },
            { published += it }
        )
    }

    private fun TestScope.settle(ms: Long = 2_000) {
        testScheduler.advanceTimeBy(ms)
        testScheduler.runCurrent()
    }

    private fun TestScope.await(condition: () -> Boolean) {
        repeat(100) {
            settle(50)
            if (condition()) return
            Thread.sleep(10)
        }
    }

    private fun payload(vararg uris: String) = SharePayload(uris.map { SharedItem(it) })

    @Test
    fun threeImagesAndAPdfSaveIntoTheLastFolderWithSanitizedNames() = runTest(main.dispatcher) {
        val vm = vm()
        vm.start(payload("content://p/1", "content://p/2", "content://p/3", "content://docs/9"), "Archivos", "Nota")
        await { !vm.state.value.loading }
        assertEquals(Destination("f_last", "Recibos"), vm.state.value.destination)
        assertEquals(4, vm.state.value.count)
        assertFalse(vm.state.value.canAddToAlbum)
        assertTrue(vm.save())
        settle()
        val body = BentoJson.decodeFromString(
            BentoInterfacesHttpRoutesAndroidImportRequest.serializer(),
            api.calls.first {
                it.method ==
                    "POST"
            }.body!!
        )
        assertEquals("f_last", body.folderId)
        assertEquals(listOf("bento.xml", "IMGgpj.exe", "Foto 3.heic", "Contrato.pdf"), body.items.map { it.displayName })
        assertTrue(body.items.none { it.displayName!!.contains('/') || it.displayName!!.contains('‮') })
        assertEquals(listOf(listOf(Destination("f_last", "Recibos"))), published)
        assertFalse(vm.save())
    }

    @Test
    fun saveHandsOverWithinTheDismissBudgetEvenWhenImportsAreSlow() = runTest(main.dispatcher) {
        val vm = vm(slowImports = true)
        vm.start(payload("content://p/1", "content://p/2", "content://p/3", "content://docs/9"), "Archivos", "Nota")
        await { !vm.state.value.loading }
        val started = System.nanoTime()
        assertTrue(vm.save())
        val elapsedMs = (System.nanoTime() - started) / 1_000_000
        assertTrue("save took $elapsedMs ms", elapsedMs < 200)
    }

    @Test
    fun revokedUrisAreShownAndReportedToActivity() = runTest(main.dispatcher) {
        val vm = vm()
        vm.start(payload("content://p/1", "content://gone/5"), "Archivos", "Nota")
        await { !vm.state.value.loading }
        assertEquals(1, vm.state.value.unreadable.size)
        assertEquals(1, vm.state.value.count)
        vm.save()
        settle()
        assertEquals(listOf("gone"), failures.entries.value.map { it.name })
        assertEquals(ImportFailureLog.REASON_UNREADABLE, failures.entries.value.single().reason)
    }

    @Test
    fun mediaCanGoToAnAlbum() = runTest(main.dispatcher) {
        val vm = vm()
        vm.start(payload("content://p/1", "content://p/3"), "Archivos", "Nota")
        await { !vm.state.value.loading }
        assertTrue(vm.state.value.canAddToAlbum)
        vm.showPicker(SharePicker.Album)
        settle()
        vm.setAlbum(vm.state.value.albums.single())
        vm.setDestination(Destination(null, "Archivos"))
        vm.save()
        settle()
        val body = BentoJson.decodeFromString(
            BentoInterfacesHttpRoutesAndroidImportRequest.serializer(),
            api.calls.first {
                it.method ==
                    "POST"
            }.body!!
        )
        assertEquals("al1", body.albumId)
        assertNull(body.folderId)
    }

    @Test
    fun textAloneBecomesANamedNote() = runTest(main.dispatcher) {
        val vm = vm()
        vm.start(SharePayload(text = "Lista de compras\nleche\npan"), "Archivos", "Nota")
        await { !vm.state.value.loading }
        assertEquals("Lista de compras.txt", vm.state.value.noteName)
        vm.save()
        settle()
        assertEquals("Lista de compras\nleche\npan", notes["Lista de compras.txt"])
        val body = BentoJson.decodeFromString(
            BentoInterfacesHttpRoutesAndroidImportRequest.serializer(),
            api.calls.first {
                it.method ==
                    "POST"
            }.body!!
        )
        assertEquals(listOf("Lista de compras.txt"), body.items.map { it.displayName })
        assertEquals(listOf("text/plain"), body.items.map { it.mimeType })
    }

    @Test
    fun directShareTargetPicksItsFolder() = runTest(main.dispatcher) {
        api.on("GET /api/drive/items") { """{"items":[],"breadcrumbs":[{"folder_id":"f_work","name":"Trabajo"}],"next_cursor":null}""" }
        val vm = vm()
        vm.start(SharePayload(listOf(SharedItem("content://p/1")), shortcutFolderId = "f_work"), "Archivos", "Nota")
        await { vm.state.value.destination.name == "Trabajo" }
        assertEquals(Destination("f_work", "Trabajo"), vm.state.value.destination)
    }

    @Test
    fun nothingToSave() = runTest(main.dispatcher) {
        val vm = vm()
        vm.start(SharePayload(), "Archivos", "Nota")
        await { !vm.state.value.loading }
        assertFalse(vm.state.value.canSave)
        assertFalse(vm.save())
    }
}
