package dev.bento.feature.settings

import java.time.Instant

/** Ajustes › Respaldo header (product/android.md §5 "Status"); rendered to copy by [backupHeaderText]. */
sealed interface BackupHeader {
    data object Off : BackupHeader

    data object NoAccess : BackupHeader

    /** "Todo respaldado ✓ · hace 3 min" ([lastBackupAt] null = nothing to back up yet). */
    data class Done(val lastBackupAt: Long?) : BackupHeader

    data class Waiting(val pending: Int, val reason: WaitReason) : BackupHeader

    data class Paused(val lowBattery: Boolean) : BackupHeader

    data class Running(val pending: Int) : BackupHeader

    companion object {
        fun of(backupOn: Boolean, access: MediaAccess, status: BackupStatus?, policy: BackupPolicy?): BackupHeader = when {
            !backupOn -> Off
            access == MediaAccess.Denied -> NoAccess
            policy?.paused == true -> Paused(lowBattery = false)
            policy?.effectivePaused == true -> Paused(lowBattery = true)
            status == null || status.pending <= 0 -> Done(status?.lastBackupAt?.let(::epochMs))
            status.waitReason == WaitReason.Battery -> Paused(lowBattery = true)
            status.waitReason != null -> Waiting(status.pending, status.waitReason!!)
            else -> Running(status.pending)
        }
    }
}

internal fun epochMs(iso: String): Long? = runCatching { Instant.parse(iso).toEpochMilli() }
    .recoverCatching { java.time.OffsetDateTime.parse(iso).toInstant().toEpochMilli() }.getOrNull()

/**
 * OEM background killers (product/android.md §11): when the backup has had pending items for over 24 h with nothing
 * holding it back (no Wi-Fi/charging/battery wait, not paused) and nothing was backed up meanwhile, the next open shows
 * a card linking to vendor-specific help. Never asks for a battery-optimization exemption.
 */
object StallDetector {
    const val STALL_MS = 24 * 60 * 60_000L

    fun stalled(status: BackupStatus?, policy: BackupPolicy?, backupOn: Boolean, prefs: LocalPrefs, now: Long): Boolean {
        val since = prefs.pendingSinceAt
        if (!unexplainedBacklog(status, policy, backupOn) || since == null) return false
        val last = status?.lastBackupAt?.let(::epochMs)
        val dismissed = prefs.stallDismissedAt
        return now - maxOf(since, last ?: Long.MIN_VALUE) >= STALL_MS && (dismissed == null || dismissed < since)
    }

    /** Pending work with nothing holding it back (no wait reason, not paused). */
    private fun unexplainedBacklog(status: BackupStatus?, policy: BackupPolicy?, backupOn: Boolean): Boolean {
        val waiting = status == null || status.pending <= 0 || status.waitReason != null
        val paused = policy?.paused == true || policy?.effectivePaused == true
        return backupOn && !waiting && !paused
    }

    /** Keeps [LocalPrefs.pendingSinceAt] in step with the backlog; returns the updated prefs (or the same). */
    fun track(prefs: LocalPrefs, pending: Int, now: Long): LocalPrefs = when {
        pending <= 0 && prefs.pendingSinceAt != null -> prefs.copy(pendingSinceAt = null, stallDismissedAt = null)
        pending > 0 && prefs.pendingSinceAt == null -> prefs.copy(pendingSinceAt = now)
        else -> prefs
    }

    /** dontkillmyapp.com keeps per-vendor steps for background restrictions; unknown vendors get the general page. */
    fun helpUrl(manufacturer: String): String {
        val vendor = manufacturer.lowercase().trim()
        val known = mapOf(
            "xiaomi" to "xiaomi", "redmi" to "xiaomi", "poco" to "xiaomi", "samsung" to "samsung", "huawei" to "huawei",
            "honor" to "honor", "oneplus" to "oneplus", "oppo" to "oppo", "realme" to "realme", "vivo" to "vivo",
            "asus" to "asus", "sony" to "sony", "nokia" to "nokia", "hmd global" to "nokia", "motorola" to "motorola",
            "lenovo" to "lenovo", "meizu" to "meizu", "google" to "google", "tecno" to "tecno", "infinix" to "infinix"
        )
        return known[vendor]?.let { "https://dontkillmyapp.com/$it" } ?: "https://dontkillmyapp.com/"
    }
}
