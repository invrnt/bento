package dev.bento.background

import dev.bento.engine.bridge.EngineEvent

/** What to do with a backend event (pure; the Android side renders it). product/android.md §8. */
sealed interface NotificationDecision {
    data object Ignore : NotificationDecision

    data class Progress(val event: EngineEvent.TransferProgress) : NotificationDecision

    /** Remove the ongoing notification; [summaryCount] > 0 shows "Listo: N fotos respaldadas". */
    data class Finished(val kind: EngineEvent.TransferKind, val summaryCount: Int) : NotificationDecision

    data class Attention(val code: String) : NotificationDecision

    data class DeviceRequest(val requestId: String, val deviceName: String) : NotificationDecision

    data class DeviceAdded(val deviceId: String, val name: String) : NotificationDecision
}

/**
 * Coalescing rules: one ongoing progress notification, updated at most once per second (and always on the
 * first event and on pause changes); a completion summary only after a backup that transferred files;
 * attention at most once per day per code.
 */
class NotificationPolicy(private val clock: () -> Long = System::currentTimeMillis) {
    private var lastProgressAt = Long.MIN_VALUE
    private var lastPaused: Boolean? = null
    private val attentionShownAt = HashMap<String, Long>()

    @Synchronized
    fun decide(event: EngineEvent): NotificationDecision {
        val now = clock()
        return when (event) {
            is EngineEvent.TransferProgress -> {
                val pauseChanged = lastPaused != event.paused
                if (!pauseChanged && lastProgressAt != Long.MIN_VALUE && now - lastProgressAt < PROGRESS_INTERVAL_MS) {
                    NotificationDecision.Ignore
                } else {
                    lastProgressAt = now
                    lastPaused = event.paused
                    NotificationDecision.Progress(event)
                }
            }
            is EngineEvent.TransferFinished -> {
                lastProgressAt = Long.MIN_VALUE
                lastPaused = null
                val summary = if (event.kind == EngineEvent.TransferKind.BACKUP) event.count - event.failed else 0
                NotificationDecision.Finished(event.kind, summary.coerceAtLeast(0))
            }
            is EngineEvent.Attention -> {
                val last = attentionShownAt[event.code]
                if (last != null && now - last < ATTENTION_INTERVAL_MS) {
                    NotificationDecision.Ignore
                } else {
                    attentionShownAt[event.code] = now
                    NotificationDecision.Attention(event.code)
                }
            }
            is EngineEvent.PairingRequest -> NotificationDecision.DeviceRequest(event.requestId, event.deviceName)
            is EngineEvent.NewDevice -> NotificationDecision.DeviceAdded(event.deviceId, event.name)
            is EngineEvent.Unknown -> NotificationDecision.Ignore
        }
    }

    companion object {
        const val PROGRESS_INTERVAL_MS = 1_000L
        const val ATTENTION_INTERVAL_MS = 24 * 60 * 60_000L
    }
}
