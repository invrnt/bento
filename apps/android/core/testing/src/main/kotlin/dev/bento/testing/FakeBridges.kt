package dev.bento.testing

import dev.bento.engine.ProcessKeeper
import dev.bento.engine.bridge.BridgeException
import dev.bento.engine.bridge.BridgeSet
import dev.bento.engine.bridge.ContentImports
import dev.bento.engine.bridge.DeviceConditions
import dev.bento.engine.bridge.DeviceKeyLostException
import dev.bento.engine.bridge.KeyWrapping
import dev.bento.engine.bridge.MediaStoreSource
import dev.bento.engine.bridge.MediaTools
import dev.bento.engine.bridge.Notifier
import dev.bento.engine.bridge.Ocr
import java.util.concurrent.CopyOnWriteArrayList

/** JVM fakes for every host bridge (architecture/android-runtime.md §5.1: "every bridge has a fake"). */
class FakeKeyWrapping(private val key: ByteArray = ByteArray(32) { it.toByte() }) : KeyWrapping {
    var calls = 0
        private set
    var resets = 0
        private set

    /** Simulates a lost Keystore key: [deviceWrappingKey] throws [DeviceKeyLostException] until [reset]. */
    var lost = false

    override fun deviceWrappingKey(): ByteArray {
        calls += 1
        if (lost) throw DeviceKeyLostException("fake: key lost")
        return key.copyOf()
    }

    override fun reset() {
        resets += 1
        lost = false
    }
}

class FakeMediaTools : MediaTools {
    val calls = CopyOnWriteArrayList<String>()

    override fun thumbnail(source: String, output: String, maxSide: Int, quality: Int, format: String): String {
        calls += "thumbnail:$maxSide:$format"
        return """{"width":$maxSide,"height":${maxSide * 3 / 4}}"""
    }

    override fun videoFrame(source: String, output: String, maxSide: Int, quality: Int, atMs: Long): String {
        calls += "videoFrame:$maxSide"
        return """{"width":$maxSide,"height":${maxSide * 9 / 16},"duration_ms":1000}"""
    }

    override fun pdfPage(source: String, output: String, page: Int, maxSide: Int): String {
        calls += "pdfPage:$page"
        return """{"width":${maxSide * 7 / 10},"height":$maxSide,"page_count":3}"""
    }

    override fun metadata(source: String, mime: String): String {
        calls += "metadata:$mime"
        return """{"width":4000,"height":3000,"duration_ms":null,"taken_at":null,"orientation":1,"exif":{}}"""
    }
}

class FakeOcr(var text: String = "Factura 123") : Ocr {
    override fun available(): Boolean = true

    override fun recognize(source: String, maxSide: Int): String =
        """{"text":"$text","language":"es","lines":[{"text":"$text","box":[0,0,10,10],"confidence":0.9}]}"""
}

class FakeMediaStoreSource(
    var accessJson: String = """{"full":true,"partial":false,"location":false}""",
    var bucketsJson: String = "[]"
) : MediaStoreSource {
    override fun access(): String = accessJson

    override fun buckets(): String = bucketsJson

    override fun scan(bucketId: String, afterMediaId: Long, limit: Int): String = """{"items":[],"next_after":null}"""

    override fun changes(sinceGeneration: Long, limit: Int): String = """{"items":[],"max_generation":$sinceGeneration}"""

    override fun exists(mediaIds: String): String = mediaIds

    override fun openFd(uri: String, requireOriginal: Boolean): Int = throw BridgeException(BridgeException.UNSUPPORTED, "fake")
}

class FakeDeviceConditions(var json: String = PERMISSIVE) : DeviceConditions {
    override fun snapshot(): String = json

    companion object {
        const val PERMISSIVE = """{"online":true,"metered":false,"unmetered":true,"charging":true,"battery_pct":100,""" +
            """"power_save":false,"data_saver":false,"storage_free_bytes":10000000000,"thermal":"none"}"""
    }
}

class FakeNotifier : Notifier {
    val emitted = CopyOnWriteArrayList<Pair<String, String>>()

    override fun emit(event: String, payloadJson: String) {
        emitted += event to payloadJson
    }
}

class FakeContentImports : ContentImports {
    private val handles = HashMap<Long, Int>()

    fun put(handle: Long, fd: Int) {
        handles[handle] = fd
    }

    override fun describe(handle: Long): String =
        if (handle in handles) {
            """{"display_name":"file.bin","mime_type":"application/octet-stream","size_bytes":1}"""
        } else {
            throw BridgeException(BridgeException.NOT_FOUND, "unknown handle")
        }

    override fun adopt(handle: Long): Int = handles.remove(handle) ?: throw BridgeException(BridgeException.NOT_FOUND, "unknown handle")
}

class FakeProcessKeeper : ProcessKeeper {
    var kept = false
        private set
    var keepCalls = 0
        private set

    override fun keepAlive() {
        kept = true
        keepCalls += 1
    }

    override fun release() {
        kept = false
    }
}

fun fakeBridgeSet(): BridgeSet = BridgeSet(
    mediaTools = FakeMediaTools(),
    ocr = FakeOcr(),
    mediaStore = FakeMediaStoreSource(),
    conditions = FakeDeviceConditions(),
    notifier = FakeNotifier(),
    contentImports = FakeContentImports()
)
