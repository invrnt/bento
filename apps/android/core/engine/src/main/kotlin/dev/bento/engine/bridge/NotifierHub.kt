package dev.bento.engine.bridge

import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull

/** Semantic backend events (api/android-endpoints.md §7). `core/background` turns them into notifications. */
sealed interface EngineEvent {
    enum class TransferKind { BACKUP, UPLOAD, DOWNLOAD, IMPORT, UNKNOWN }

    data class TransferProgress(
        val kind: TransferKind,
        val done: Int,
        val total: Int,
        val bytesDone: Long,
        val bytesTotal: Long,
        val paused: Boolean,
    ) : EngineEvent

    data class TransferFinished(val kind: TransferKind, val count: Int, val failed: Int) : EngineEvent

    data class Attention(val code: String, val count: Int) : EngineEvent

    data class PairingRequest(val requestId: String, val deviceName: String, val platform: String) : EngineEvent

    data class NewDevice(val deviceId: String, val name: String) : EngineEvent

    data class Unknown(val event: String) : EngineEvent

    companion object {
        /** Parses a bridge call; malformed payloads map to [Unknown] (never throw back into Python). */
        fun parse(event: String, payloadJson: String): EngineEvent {
            val payload = runCatching { BridgeJson.parseToJsonElement(payloadJson).jsonObject }.getOrNull() ?: return Unknown(event)
            return runCatching {
                when (event) {
                    "transfer_progress" -> TransferProgress(
                        kind = payload.kind(),
                        done = payload.int("done"),
                        total = payload.int("total"),
                        bytesDone = payload.long("bytes_done"),
                        bytesTotal = payload.long("bytes_total"),
                        paused = payload["paused"]?.jsonPrimitive?.booleanOrNull ?: false,
                    )
                    "transfer_finished" -> TransferFinished(payload.kind(), payload.int("count"), payload.int("failed"))
                    "attention" -> Attention(payload.string("code"), payload.int("count"))
                    "pairing_request" -> PairingRequest(payload.string("request_id"), payload.string("device_name"), payload.string("platform"))
                    "new_device" -> NewDevice(payload.string("device_id"), payload.string("name"))
                    else -> Unknown(event)
                }
            }.getOrDefault(Unknown(event))
        }

        private fun JsonObject.kind(): TransferKind =
            runCatching { TransferKind.valueOf(string("kind").uppercase()) }.getOrDefault(TransferKind.UNKNOWN)

        private fun JsonObject.int(key: String): Int = this[key]?.jsonPrimitive?.intOrNull ?: 0

        private fun JsonObject.long(key: String): Long = this[key]?.jsonPrimitive?.longOrNull ?: 0L

        private fun JsonObject.string(key: String): String = this[key]?.jsonPrimitive?.content ?: error("missing $key")
    }
}

/** [Notifier] that republishes events as a hot flow; non-blocking for the Python caller. */
class NotifierHub : Notifier {
    private val _events = MutableSharedFlow<EngineEvent>(extraBufferCapacity = 64, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val events: SharedFlow<EngineEvent> = _events.asSharedFlow()

    override fun emit(event: String, payloadJson: String) {
        _events.tryEmit(EngineEvent.parse(event, payloadJson))
    }
}
