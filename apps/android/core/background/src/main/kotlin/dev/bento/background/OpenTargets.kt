package dev.bento.background

import android.content.Intent

/**
 * Where a notification, the Quick Settings tile or a launcher shortcut opens the app (agent 41). Encoded as one intent
 * extra so MainActivity maps it to a navigation route; pure and JVM tested.
 */
sealed interface OpenTarget {
    data object Activity : OpenTarget

    data object Backup : OpenTarget

    data object Storage : OpenTarget

    data object Recovery : OpenTarget

    data object Reconnect : OpenTarget

    data object Devices : OpenTarget

    data object DeviceRemoved : OpenTarget

    data object Search : OpenTarget

    data object AddDevice : OpenTarget

    data class PairingRequest(val requestId: String) : OpenTarget

    data class DeviceReview(val deviceId: String) : OpenTarget
}

object OpenTargets {
    const val EXTRA = "dev.bento.open"

    /** Launcher shortcut actions (res/xml/bento_shortcuts.xml) handled by MainActivity. */
    const val ACTION_SEARCH = "dev.bento.action.SEARCH"
    const val ACTION_ADD_DEVICE = "dev.bento.action.ADD_DEVICE"

    /** Quick Settings tile long-press (Ajustes › Respaldo). */
    const val ACTION_QS_TILE_PREFERENCES = "android.service.quicksettings.action.QS_TILE_PREFERENCES"

    private val ID = Regex("^[A-Za-z0-9_.:-]{1,128}$")

    fun encode(target: OpenTarget): String = when (target) {
        OpenTarget.Activity -> "activity"
        OpenTarget.Backup -> "backup"
        OpenTarget.Storage -> "storage"
        OpenTarget.Recovery -> "recovery"
        OpenTarget.Reconnect -> "reconnect"
        OpenTarget.Devices -> "devices"
        OpenTarget.DeviceRemoved -> "device_removed"
        OpenTarget.Search -> "search"
        OpenTarget.AddDevice -> "add_device"
        is OpenTarget.PairingRequest -> "pairing_request:${target.requestId}"
        is OpenTarget.DeviceReview -> "device_review:${target.deviceId}"
    }

    /** Unknown or malformed values open nothing special (the app simply comes to the front). */
    fun decode(value: String?): OpenTarget? {
        if (value.isNullOrBlank()) return null
        val kind = value.substringBefore(':')
        val id = value.substringAfter(':', "").takeIf { ID.matches(it) }
        return when (kind) {
            "activity" -> OpenTarget.Activity
            "backup" -> OpenTarget.Backup
            "storage" -> OpenTarget.Storage
            "recovery" -> OpenTarget.Recovery
            "reconnect" -> OpenTarget.Reconnect
            "devices" -> OpenTarget.Devices
            "device_removed" -> OpenTarget.DeviceRemoved
            "search" -> OpenTarget.Search
            "add_device" -> OpenTarget.AddDevice
            "pairing_request" -> id?.let(OpenTarget::PairingRequest)
            "device_review" -> id?.let(OpenTarget::DeviceReview)
            else -> null
        }
    }

    /** What an incoming MainActivity intent asks to open: notification extra, shortcut action or tile long-press. */
    fun from(action: String?, extra: String?): OpenTarget? = when (action) {
        ACTION_SEARCH -> OpenTarget.Search
        ACTION_ADD_DEVICE -> OpenTarget.AddDevice
        ACTION_QS_TILE_PREFERENCES -> OpenTarget.Backup
        else -> decode(extra)
    }

    fun from(intent: Intent?): OpenTarget? = intent?.let { from(it.action, it.getStringExtra(EXTRA)) }
}
