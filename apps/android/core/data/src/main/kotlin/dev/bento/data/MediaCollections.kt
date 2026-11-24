package dev.bento.data

import dev.bento.api.generated.BentoEndpoints
import dev.bento.api.generated.BentoInterfacesHttpRoutesTelegramImportRequest
import dev.bento.api.generated.ImportResponse
import dev.bento.api.generated.ShareRequest
import dev.bento.api.generated.TelegramChatResponse
import dev.bento.api.generated.TelegramMediaResponse
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull

/** Importado de Telegram and Enviar por Telegram: chats, a chat's media, import jobs, sending a copy. */
class TelegramMediaRepository(private val api: BentoEndpoints, private val invalidations: Invalidations) {
    /** Mensajes guardados first (the backend lists them first), then recent chats. */
    suspend fun chats(query: String? = null): List<TelegramChatResponse> = api.listChats(query = query?.ifBlank { null }).items

    suspend fun media(chatId: Long, cursor: String? = null, kind: String = "all"): CursorPage<TelegramMediaResponse> {
        val page = api.listImportMedia(chatId = chatId, cursor = cursor, kind = kind)
        return CursorPage(page.items, page.nextCursor)
    }

    /** Imports in background (a job); [messageIds] null with [all] imports the whole chat's media. */
    suspend fun import(chatId: Long, messageIds: List<Long>?, all: Boolean): ImportResponse =
        api.importMedia(BentoInterfacesHttpRoutesTelegramImportRequest(all = all, chatId = chatId, messageIds = messageIds))
            .also { invalidations.invalidate(Topic.TIMELINE, Topic.DRIVE, Topic.ACTIVITY) }

    /** Enviar por Telegram: sends a plaintext copy to [chatId] (the UI always states it first). */
    suspend fun send(assetId: String, chatId: Long, caption: String? = null): Boolean =
        api.shareAsset(assetId, ShareRequest(caption = caption, chatId = chatId)).sent
}

/** One backed-up phone folder (Del teléfono) from `GET /backup/sources` (untyped in the schema). */
data class PhoneFolder(
    val id: String,
    val label: String,
    val kind: String,
    val enabled: Boolean,
    val state: String,
    val filesTotal: Int,
    val filesDone: Int,
    val filesPending: Int,
    val lastScanAt: String?,
    val error: String?
)

class PhoneFoldersRepository(private val api: BentoEndpoints) {
    suspend fun folders(): List<PhoneFolder> = parsePhoneFolders(api.listBackupSources())

    /** With partial media access (Android 14 "Seleccionar fotos"), how many photos Bento can see; null otherwise. */
    suspend fun partialAccessVisible(): Int? {
        val status = api.backupStatus() as? JsonObject ?: return null
        val partial = (status["partial_access"] as? JsonPrimitive)?.booleanOrNull ?: false
        if (!partial) return null
        return folders().filter { it.kind == "media_store" }.sumOf { it.filesTotal }
    }
}

internal fun parsePhoneFolders(element: JsonElement): List<PhoneFolder> {
    val items = ((element as? JsonObject)?.get("items") as? JsonArray).orEmpty().filterIsInstance<JsonObject>()
    return items.mapNotNull { item ->
        val id = item.string("id") ?: return@mapNotNull null
        PhoneFolder(
            id = id,
            label = item.string("label") ?: item.string("path").orEmpty().substringAfterLast('/'),
            kind = item.string("kind") ?: "folder",
            enabled = (item["enabled"] as? JsonPrimitive)?.booleanOrNull ?: true,
            state = item.string("state") ?: "idle",
            filesTotal = item.int("files_total"),
            filesDone = item.int("files_done"),
            filesPending = item.int("files_pending"),
            lastScanAt = item.string("last_scan_at"),
            error = item.string("error")
        )
    }
}

/** A document (not a photo or video) anywhere in Drive, for Colecciones › Documentos. */
data class DocumentEntry(val id: String, val name: String, val path: String, val mimeType: String, val sizeBytes: Long, val createdAt: String?)

/**
 * Documentos: a thin list from `GET /drive/tree` (the backend has no kind filter yet), capped at [maxNodes]
 * nodes; `truncated` tells the UI to say so. Newest first.
 */
class DocumentsRepository(private val api: BentoEndpoints) {
    data class Result(val items: List<DocumentEntry>, val truncated: Boolean)

    suspend fun documents(maxNodes: Int = 2_000): Result = parseDocuments(api.driveTree(depth = 32, includeAssets = true, maxNodes = maxNodes.toLong()))
}

internal fun parseDocuments(element: JsonElement): DocumentsRepository.Result {
    val root = element as? JsonObject ?: return DocumentsRepository.Result(emptyList(), false)
    val out = ArrayList<DocumentEntry>()
    fun walk(node: JsonObject) {
        if (node.string("kind") == "asset") {
            val mime = node.string("mime_type").orEmpty()
            if (!mime.startsWith("image/") && !mime.startsWith("video/")) {
                out += DocumentEntry(
                    id = node.string("id") ?: return,
                    name = node.string("name").orEmpty(),
                    path = node.string("path").orEmpty(),
                    mimeType = mime,
                    sizeBytes = (node["size_bytes"] as? JsonPrimitive)?.longOrNull ?: 0L,
                    createdAt = node.string("created_at")
                )
            }
        }
        (node["children"] as? JsonArray)?.filterIsInstance<JsonObject>()?.forEach(::walk)
    }
    (root["root"] as? JsonObject)?.let(::walk)
    val truncated = (root["truncated"] as? JsonPrimitive)?.booleanOrNull ?: false
    return DocumentsRepository.Result(out.sortedByDescending { it.createdAt.orEmpty() }, truncated)
}

private fun JsonObject.string(key: String): String? = (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull

private fun JsonObject.int(key: String): Int = (this[key] as? JsonPrimitive)?.intOrNull ?: 0
