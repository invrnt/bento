package dev.bento.engine.bridge

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class MediaMathTest {
    @Test
    fun `fit keeps aspect ratio and never upscales`() {
        assertEquals(ImageSize(256, 192), MediaMath.fit(4000, 3000, 256))
        assertEquals(ImageSize(192, 256), MediaMath.fit(3000, 4000, 256))
        assertEquals(ImageSize(100, 50), MediaMath.fit(100, 50, 1024))
        assertEquals(ImageSize(1024, 1), MediaMath.fit(100_000, 10, 1024))
    }

    @Test
    fun `formats are jpeg or webp only`() {
        assertEquals("jpeg", MediaMath.outputFormat("JPG"))
        assertEquals("webp", MediaMath.outputFormat("webp"))
        try {
            MediaMath.outputFormat("png")
            fail("expected unsupported")
        } catch (expected: BridgeException) {
            assertEquals(BridgeException.UNSUPPORTED, expected.code)
        }
    }

    @Test
    fun `exif dates become ISO-8601 with optional offset`() {
        assertEquals("2024-03-12T08:30:00", MediaMath.exifDateToIso("2024:03:12 08:30:00", null))
        assertEquals("2024-03-12T08:30:00-05:00", MediaMath.exifDateToIso("2024:03:12 08:30:00", "-05:00"))
        assertNull(MediaMath.exifDateToIso("0000:00:00 00:00:00", null))
        assertNull(MediaMath.exifDateToIso("garbage", null))
    }

    @Test
    fun `rotated orientations swap the display size`() {
        assertEquals(ImageSize(3000, 4000), MediaMath.displaySize(4000, 3000, 6))
        assertEquals(ImageSize(4000, 3000), MediaMath.displaySize(4000, 3000, 1))
    }
}

class BridgeSourceTest {
    @Test
    fun `sources are absolute paths or fd numbers`() {
        assertEquals(BridgeSource.Descriptor(42), BridgeSource.parse("fd:42"))
        assertTrue(BridgeSource.parse("/data/x.jpg") is BridgeSource.Path)
        for (bad in listOf("relative/x.jpg", "fd:abc", "content://x")) {
            try {
                BridgeSource.parse(bad)
                fail("expected unsupported for $bad")
            } catch (expected: BridgeException) {
                assertEquals(BridgeException.UNSUPPORTED, expected.code)
            }
        }
    }
}

class ConditionsMappingTest {
    private fun raw(
        notMetered: Boolean = true,
        validated: Boolean = true,
        plugged: Int = 0,
        status: Int = 3,
        level: Int = 50,
        restrict: Int = 1,
        thermal: Int = 0,
    ) = RawConditions(
        hasInternet = true, validated = validated, notMetered = notMetered, temporarilyNotMetered = false,
        restrictBackgroundStatus = restrict, batteryStatus = status, plugged = plugged, batteryLevel = level,
        batteryScale = 100, powerSave = false, thermalStatus = thermal, storageFreeBytes = 5_000,
    )

    @Test
    fun `wifi vs metered vs offline`() {
        assertTrue(ConditionsMapping.map(raw()).unmetered)
        val metered = ConditionsMapping.map(raw(notMetered = false))
        assertTrue(metered.metered && !metered.unmetered && metered.online)
        val offline = ConditionsMapping.map(raw(validated = false))
        assertTrue(!offline.online && !offline.metered && !offline.unmetered)
    }

    @Test
    fun `charging, battery, data saver and thermal`() {
        assertTrue(ConditionsMapping.map(raw(plugged = 2)).charging)
        assertTrue(ConditionsMapping.map(raw(status = 2)).charging)
        assertEquals(50, ConditionsMapping.map(raw()).batteryPct)
        assertTrue(ConditionsMapping.map(raw(restrict = 3)).dataSaver)
        assertEquals(listOf("none", "light", "moderate", "severe", "severe"), (0..4).map(ConditionsMapping::thermal))
    }

    @Test
    fun `snapshot JSON uses the contract keys`() {
        val json = BridgeJson.encodeToString(DeviceConditionsSnapshot.serializer(), ConditionsMapping.map(raw()))
        val keys = Json.parseToJsonElement(json).jsonObject.keys
        assertEquals(
            setOf("online", "metered", "unmetered", "charging", "battery_pct", "power_save", "data_saver", "storage_free_bytes", "thermal"),
            keys,
        )
    }
}

class MediaStoreMappingTest {
    private fun row(id: Long, type: Int = 1, bucket: String? = "b1", name: String? = "Camera") = MediaRow(
        id = id, mediaType = type, bucketId = bucket, bucketName = name, displayName = "IMG_$id.jpg", mimeType = "image/jpeg",
        size = 10, dateTaken = 0, dateModified = 1_700_000_000, generation = id * 10, width = 0, height = 3000, duration = null,
        relativePath = "DCIM/Camera/",
    )

    @Test
    fun `rows map to MediaItem with the contract keys`() {
        val item = MediaStoreMapping.item(row(7, type = 3))
        assertEquals("content://media/external/video/media/7", item.uri)
        assertNull("non-positive values become null", item.dateTakenMs)
        assertNull(item.width)
        val keys = Json.parseToJsonElement(BridgeJson.encodeToString(MediaItem.serializer(), item)).jsonObject.keys
        assertEquals(
            setOf(
                "media_id", "uri", "bucket_id", "display_name", "mime_type", "size_bytes", "date_taken_ms", "date_modified_s",
                "generation", "width", "height", "duration_ms", "relative_path",
            ),
            keys,
        )
    }

    @Test
    fun `buckets group counts and videos and sort by name`() {
        val buckets = MediaStoreMapping.buckets(
            sequenceOf(row(1), row(2, type = 3), row(3, bucket = "b2", name = "Alpha"), row(4, bucket = null)),
        )
        assertEquals(listOf("Alpha", "Camera"), buckets.map { it.name })
        assertEquals(2, buckets[1].count)
        assertEquals(1, buckets[1].videoCount)
    }

    @Test
    fun `exists ids parse from a JSON list`() {
        assertEquals(listOf(1L, 2L, 30L), MediaStoreMapping.parseIds("[1, 2, 30]"))
    }
}

class OcrMappingTest {
    @Test
    fun `lines become boxes with width and height and the majority language`() {
        val result = OcrMapping.map(
            "Hola\nmundo",
            listOf(
                OcrMapping.RawLine("Hola", 10, 20, 50, 40, 0.9f, "es"),
                OcrMapping.RawLine("mundo", 10, 45, 60, 65, null, "es"),
                OcrMapping.RawLine("x", 0, 0, 1, 1, 2f, "und"),
            ),
        )
        assertEquals("es", result.language)
        assertEquals(listOf(10, 20, 40, 20), result.lines[0].box)
        assertNull(result.lines[1].confidence)
        assertNull("out-of-range confidence dropped", result.lines[2].confidence)
    }
}

class EngineEventTest {
    @Test
    fun `notifier payloads parse into typed events`() {
        val progress = EngineEvent.parse(
            "transfer_progress",
            """{"kind":"backup","done":3,"total":10,"bytes_done":30,"bytes_total":100,"paused":false}""",
        )
        assertEquals(EngineEvent.TransferProgress(EngineEvent.TransferKind.BACKUP, 3, 10, 30, 100, false), progress)
        assertEquals(EngineEvent.Attention("kit_pending", 1), EngineEvent.parse("attention", """{"code":"kit_pending","count":1}"""))
        assertEquals(
            EngineEvent.PairingRequest("r1", "Portátil", "desktop"),
            EngineEvent.parse("pairing_request", """{"request_id":"r1","device_name":"Portátil","platform":"desktop"}"""),
        )
        assertEquals(EngineEvent.Unknown("attention"), EngineEvent.parse("attention", "not json"))
        assertEquals(EngineEvent.Unknown("new_device"), EngineEvent.parse("new_device", "{}"))
        assertEquals(EngineEvent.Unknown("future"), EngineEvent.parse("future", "{}"))
    }

    @Test
    fun `hub republishes without blocking`() {
        val hub = NotifierHub()
        repeat(200) { hub.emit("transfer_finished", """{"kind":"upload","count":$it,"failed":0}""") }
        assertTrue(hub.events.replayCache.isEmpty())
    }
}

class ContentImportRegistryTest {
    private class FakeOpener : DescriptorOpener {
        var next = 100
        val closed = mutableListOf<Int>()

        override fun open(uri: String): Int = next++

        override fun describe(uri: String) = ContentDescription("a.pdf", "application/pdf", 12)

        override fun close(fd: Int) {
            closed += fd
        }
    }

    @Test
    fun `handles are adopted exactly once`() {
        val registry = ContentImportRegistry(FakeOpener())
        val handle = registry.register("content://x/1")
        val described = Json.parseToJsonElement(registry.describe(handle)).jsonObject
        assertEquals("a.pdf", described["display_name"]!!.jsonPrimitive.content)
        assertEquals(100, registry.adopt(handle))
        try {
            registry.adopt(handle)
            fail("second adopt must fail")
        } catch (expected: BridgeException) {
            assertEquals(BridgeException.NOT_FOUND, expected.code)
        }
    }

    @Test
    fun `unclaimed handles expire and are closed`() {
        var now = 0L
        val opener = FakeOpener()
        val registry = ContentImportRegistry(opener, clock = { now }, ttlMs = 1_000)
        val stale = registry.register("content://x/1")
        now = 2_000
        registry.register("content://x/2")
        assertEquals(listOf(100), opener.closed)
        assertEquals(1, registry.pendingCount())
        try {
            registry.adopt(stale)
            fail("expired handle must fail")
        } catch (expected: BridgeException) {
            assertEquals(BridgeException.NOT_FOUND, expected.code)
        }
        registry.clear()
        assertEquals(listOf(100, 101), opener.closed)
    }
}
