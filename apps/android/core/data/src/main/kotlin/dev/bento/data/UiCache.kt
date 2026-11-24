package dev.bento.data

import java.io.File
import kotlinx.serialization.KSerializer
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement

/**
 * Instant-start view cache (architecture/android-runtime.md §8): each top-level destination stores its
 * first screen (≤ [MAX_ITEMS] DTOs) in `filesDir/bento/ui-cache/<key>.json` after a successful load and
 * renders it on cold start, before the engine is ready. It is a view cache, not a catalog: everything is
 * dropped when the vault changes ([bindVault]), on sign-out ([clear]) or when [schemaVersion] (the DTO
 * snapshot) changes.
 */
class UiCache(
    private val directory: File,
    private val schemaVersion: String,
    private val json: Json = Json { ignoreUnknownKeys = true }
) {
    @Serializable
    private data class Envelope(val schema: String, val vault: String?, val savedAtMs: Long, val items: JsonElement)

    private val marker = File(directory, "vault.id")

    /** The vault the cached screens belong to (null before the first successful vault status). */
    @Synchronized
    fun currentVault(): String? = marker.takeIf { it.exists() }?.readText()?.trim()?.ifEmpty { null }

    /** Record the active vault; a different vault than the cached one clears every entry. */
    @Synchronized
    fun bindVault(vaultId: String?) {
        if (vaultId == currentVault()) return
        clear()
        directory.mkdirs()
        marker.writeText(vaultId.orEmpty())
    }

    @Synchronized
    fun <T> write(key: String, items: List<T>, serializer: KSerializer<T>, nowMs: Long = System.currentTimeMillis()) {
        val payload = json.encodeToJsonElement(ListSerializer(serializer), items.take(MAX_ITEMS))
        directory.mkdirs()
        val target = file(key)
        val tmp = File(directory, ".${target.name}.tmp")
        tmp.writeText(json.encodeToString(Envelope.serializer(), Envelope(schemaVersion, currentVault(), nowMs, payload)))
        tmp.renameTo(target)
    }

    /** Cached items, or null when missing, from another vault, or from another schema version. */
    @Synchronized
    fun <T> read(key: String, serializer: KSerializer<T>): List<T>? {
        val target = file(key)
        if (!target.exists()) return null
        val envelope = runCatching { json.decodeFromString(Envelope.serializer(), target.readText()) }.getOrNull()
        if (envelope == null || envelope.schema != schemaVersion || envelope.vault != currentVault()) {
            target.delete()
            return null
        }
        return runCatching { json.decodeFromJsonElement(ListSerializer(serializer), envelope.items) }.getOrElse {
            target.delete()
            null
        }
    }

    /** Sign-out, reset, vault change. */
    @Synchronized
    fun clear() {
        directory.listFiles()?.forEach { it.delete() }
    }

    private fun file(key: String): File {
        require(key.matches(Regex("[a-z0-9_-]{1,64}"))) { "bad cache key" }
        return File(directory, "$key.json")
    }

    companion object {
        const val MAX_ITEMS = 300
    }
}
