package dev.bento.feature.files

import dev.bento.api.BentoJson
import dev.bento.api.generated.BentoInterfacesHttpRoutesAndroidImportRequest
import dev.bento.data.Invalidations
import dev.bento.testing.FakeApiTransport
import java.nio.file.Files
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UploadsTest {
    private val dir = Files.createTempDirectory("imports").toFile()

    /** Registers content URIs like the engine's registry; `revoked` ones throw like a dead grant. */
    private class FakeHandles(private val names: Map<String, String>, private val revoked: Set<String> = emptySet()) : ContentHandles {
        val registered = mutableListOf<String>()

        override fun register(uri: String): ContentHandles.Registered {
            if (uri in revoked) throw SecurityException("Permission Denial: grant revoked")
            registered += uri
            return ContentHandles.Registered(registered.size.toLong(), names[uri] ?: "x", "application/octet-stream", 1_000)
        }
    }

    private class FakeTransfers : TransferControl {
        var started = 0
        var stopped = 0

        override fun start(estimatedBytes: Long) {
            started++
        }

        override fun stop() {
            stopped++
        }
    }

    private fun TestScope.coordinator(
        api: FakeApiTransport,
        handles: ContentHandles,
        log: ImportFailureLog,
        transfers: FakeTransfers = FakeTransfers()
    ) =
        UploadCoordinator(api.endpoints(), handles, transfers, log, Invalidations(), backgroundScope, pollMs = 10)

    private fun importApi(statuses: List<String>): FakeApiTransport = FakeApiTransport().apply {
        on("POST /api/android/imports") { """{"import_id":"imp_1","done":false,"counts":{},"items":[]}""" }
        on("GET /api/android/imports/imp_1") {
            val items = statuses.mapIndexed { index, status ->
                """{"client_index":$index,"asset_id":${if (status == "failed") "null" else "\"as_$index\""},""" +
                    """"status":"$status","error":${if (status == "failed") "\"content_unreadable\"" else "null"}}"""
            }
            """{"import_id":"imp_1","done":true,"counts":{},"items":[${items.joinToString(",")}]}"""
        }
    }

    @Test
    fun weirdAndTraversalNamesReachTheBackendSanitized() = runTest {
        val api = importApi(listOf("done", "done", "duplicate"))
        val handles = FakeHandles(
            mapOf(
                "content://a/1" to "../../../data/data/dev.bento.app/files/x.db",
                "content://a/2" to "Fac‮tura\u0000.pdf",
                "content://a/3" to "CON"
            )
        )
        val uploads = coordinator(api, handles, ImportFailureLog(dir))
        uploads.submit(
            listOf(
                PickedContent("content://a/1"),
                PickedContent("content://a/2"),
                PickedContent("content://a/3", displayName = "..\\..\\boot.ini")
            ),
            UploadTarget("f_1")
        )
        settle(1_000)
        val body = BentoJson.decodeFromString(
            BentoInterfacesHttpRoutesAndroidImportRequest.serializer(),
            api.calls.first {
                it.method ==
                    "POST"
            }.body!!
        )
        assertEquals(listOf("x.db", "Factura.pdf", "boot.ini"), body.items.map { it.displayName })
        assertEquals("f_1", body.folderId)
        assertEquals(listOf(1L, 2L, 3L), body.items.map { it.fdHandle })
        assertEquals(listOf(UploadStatus.Done, UploadStatus.Done, UploadStatus.Duplicate), uploads.state.value.rows.map { it.status })
    }

    @Test
    fun revokedUrisAreReportedWithTheirNamesNeverDropped() = runTest {
        val api = importApi(listOf("done", "failed"))
        val log = ImportFailureLog(dir)
        val transfers = FakeTransfers()
        val handles =
            FakeHandles(mapOf("content://a/ok" to "ok.jpg", "content://a/late" to "tarde.jpg"), revoked = setOf("content://a/gone"))
        val uploads = coordinator(api, handles, log, transfers)
        val rows = uploads.submit(
            listOf(
                PickedContent("content://a/ok"),
                PickedContent("content://a/gone", displayName = "Recibo.pdf"),
                PickedContent("content://a/late")
            ),
            UploadTarget(null)
        )
        assertEquals(UploadStatus.Failed, rows[1].status)
        settle(1_000)
        val body = BentoJson.decodeFromString(
            BentoInterfacesHttpRoutesAndroidImportRequest.serializer(),
            api.calls.first {
                it.method ==
                    "POST"
            }.body!!
        )
        assertEquals(2, body.items.size)
        assertEquals(listOf("Recibo.pdf", "tarde.jpg"), log.entries.value.map { it.name })
        assertEquals(listOf(ImportFailureLog.REASON_UNREADABLE, "content_unreadable"), log.entries.value.map { it.reason })
        assertEquals(1, transfers.started)
        assertEquals(2, uploads.state.value.failedCount)
    }

    @Test
    fun interruptedBatchesAreReportedAfterAProcessDeath() {
        val first = ImportFailureLog(dir)
        first.journalStart(listOf("a.jpg", "b.pdf"))
        // The process dies here; next start:
        val second = ImportFailureLog(dir)
        second.recoverInterrupted()
        assertEquals(listOf("a.jpg", "b.pdf"), second.entries.value.map { it.name })
        assertTrue(second.entries.value.all { it.reason == ImportFailureLog.REASON_INTERRUPTED })
        val third = ImportFailureLog(dir)
        third.recoverInterrupted()
        assertEquals(2, third.entries.value.size)
    }

    @Test
    fun cardStateAndPause() = runTest {
        val api = importApi(listOf("done"))
        val transfers = FakeTransfers()
        val uploads = coordinator(api, FakeHandles(mapOf("content://a/1" to "a.pdf")), ImportFailureLog(dir), transfers)
        uploads.submit(listOf(PickedContent("content://a/1", sizeBytes = 4_000)), UploadTarget(null))
        assertTrue(uploads.state.value.active)
        uploads.pause()
        assertTrue(uploads.state.value.paused)
        assertEquals(1, transfers.stopped)
        uploads.resume()
        assertFalse(uploads.state.value.paused)
        settle()
        assertFalse(uploads.state.value.visible)
    }

    @Test
    fun importErrorsFailTheBatch() = runTest {
        val api = FakeApiTransport().apply { fail("POST /api/android/imports", 422, "validation_failed") }
        val log = ImportFailureLog(dir)
        val uploads = coordinator(api, FakeHandles(mapOf("content://a/1" to "a.pdf")), log)
        uploads.submit(listOf(PickedContent("content://a/1")), UploadTarget(null))
        settle()
        assertEquals(listOf("a.pdf"), log.entries.value.map { it.name })
    }
}
