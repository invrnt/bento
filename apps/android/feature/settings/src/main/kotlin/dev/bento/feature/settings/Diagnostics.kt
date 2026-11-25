package dev.bento.feature.settings

import android.app.ActivityManager
import android.content.Context
import android.net.Uri
import android.os.Build
import java.io.File
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** What goes into the diagnostic report; collected by [SettingsViewModel], written by [Diagnostics.write]. */
data class DiagnosticFacts(
    val appVersion: String,
    val engine: String,
    val storageBackend: String?,
    val sync: String?,
    val backup: String?,
    val activity: String?,
    val settings: JsonObject?
)

/**
 * Ajustes › Avanzado › Exportar diagnóstico (product/android.md §9): a plain-text report written through the Storage
 * Access Framework. It holds versions, states and the engine's redacted log tail; never tokens, sessions, codes, keys,
 * phone numbers or file names (secrets are skipped by key, and every line passes [Diagnostics.scrub] as well).
 */
object Diagnostics {
    private const val LOG_LINES = 400
    private val longSecret = Regex("[A-Za-z0-9_\\-+/=]{32,}")
    private val phone = Regex("\\+?\\d[\\d ()-]{7,}\\d")
    private val email = Regex("[\\w.+-]+@[\\w-]+\\.[\\w.]+")

    fun scrub(line: String): String = line
        .replace(longSecret, "[redacted]")
        .replace(email, "[redacted]")
        .replace(phone, "[redacted]")

    fun report(facts: DiagnosticFacts, device: String, logs: List<String>): String = buildString {
        appendLine("Bento diagnostic report")
        appendLine("app_version: ${facts.appVersion}")
        appendLine("device: $device")
        appendLine("engine: ${facts.engine}")
        appendLine("storage_backend: ${facts.storageBackend ?: "unknown"}")
        appendLine("sync: ${facts.sync ?: "unavailable"}")
        appendLine("backup: ${facts.backup ?: "unavailable"}")
        appendLine("activity: ${facts.activity ?: "unavailable"}")
        appendLine()
        appendLine("[settings]")
        facts.settings?.let(::settingsLines)?.forEach(::appendLine)
        appendLine()
        appendLine("[engine log, redacted, last ${logs.size} lines]")
        logs.forEach { appendLine(scrub(it)) }
    }

    /** Non-secret setting values only (secret entries carry `configured`, never a value). */
    internal fun settingsLines(root: JsonObject): List<String> {
        val values = root["values"] as? JsonObject ?: return emptyList()
        return values.entries.sortedBy { it.key }.mapNotNull { (key, entry) ->
            val obj = entry as? JsonObject ?: return@mapNotNull null
            if (key in SKIPPED || "configured" in obj) return@mapNotNull "$key: (hidden)"
            val value = (obj["value"] as? JsonPrimitive)?.content ?: "null"
            "$key: $value (${(obj["source"] as? JsonPrimitive)?.content})"
        }
    }

    /** Paths and device names can identify a person; they are summarized, not copied. */
    private val SKIPPED = setOf("data_dir", "device_name", "fake_telegram_dir", "fake_telegram_url", "jina_model_path")

    fun deviceLine(): String = "${Build.MANUFACTURER} ${Build.MODEL}, Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT}), " +
        Build.SUPPORTED_ABIS.firstOrNull().orEmpty()

    /** The tail of the backend's redacted rotating log (`noBackupFilesDir/logs`). */
    fun logTail(context: Context): List<String> {
        val dir = File(context.noBackupFilesDir, "logs")
        val files = dir.listFiles { f -> f.isFile }.orEmpty().sortedBy { it.lastModified() }
        val lines = ArrayDeque<String>()
        files.forEach { file ->
            runCatching {
                file.useLines { seq ->
                    seq.forEach {
                        lines.addLast(it)
                        if (lines.size > LOG_LINES) lines.removeFirst()
                    }
                }
            }
        }
        return lines.toList()
    }

    fun write(context: Context, uri: Uri, text: String): Boolean = runCatching {
        context.contentResolver.openOutputStream(uri, "wt")?.use { it.write(text.toByteArray()) } != null
    }.getOrDefault(false)
}

/**
 * `Restablecer Bento en este teléfono` (product/android.md §9-§10): wipes this phone's local data and keys (database,
 * key store, caches, sessions); the vault and the other devices are untouched. `clearApplicationUserData` also removes
 * the app's Keystore entries and ends the process, so the next launch is a first run.
 */
object PhoneReset {
    const val CONFIRM_ES = "RESTABLECER"
    const val CONFIRM_EN = "RESET"

    /** Typed confirmation: the localized word, case-insensitive, surrounding spaces ignored. */
    fun confirmed(typed: String, expected: String): Boolean = typed.trim().equals(expected, ignoreCase = true)

    fun wipe(context: Context): Boolean = context.getSystemService(ActivityManager::class.java)?.clearApplicationUserData() == true
}
