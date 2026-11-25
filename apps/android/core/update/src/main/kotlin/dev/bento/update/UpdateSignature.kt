package dev.bento.update

import java.security.MessageDigest
import java.util.Base64
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import org.bouncycastle.math.ec.rfc8032.Ed25519

/**
 * Ed25519 signatures over the exact bytes of a per-target update manifest, the same format as the desktop updater
 * (`apps/desktop/src/main/update-signature.ts`) and signed by the same key:
 *
 *   message   = "bento-update-manifest:v1" || 0x00 || manifest bytes
 *   .sig file = {"schemaVersion":1,"algorithm":"ed25519","signatures":[{"keyId","signature"}]}
 *   keyId     = first 16 hex characters of SHA-256(raw 32-byte public key)
 *
 * Several signatures allow key rotation; one valid signature by any embedded key is enough.
 */
object UpdateSignature {
    const val SUFFIX: String = ".sig"
    const val MAX_SIGNATURE_BYTES: Int = 4096
    const val MAX_SIGNATURES: Int = 4

    private val CONTEXT = "bento-update-manifest:v1\u0000".toByteArray(Charsets.UTF_8)
    private val RAW_PUBLIC_KEY = Regex("^[A-Za-z0-9+/]{43}=$")
    private val SIGNATURE = Regex("^[A-Za-z0-9+/]{86}==$")
    private val KEY_ID = Regex("^[a-f0-9]{16}$")
    private val strict = Json { isLenient = false }

    /** Raw 32-byte Ed25519 public key from its canonical base64 (`BENTO_UPDATE_PUBLIC_KEY`), or `null`. */
    fun parsePublicKey(value: String): ByteArray? {
        if (!RAW_PUBLIC_KEY.matches(value)) return null
        val raw = runCatching { Base64.getDecoder().decode(value) }.getOrNull() ?: return null
        if (raw.size != Ed25519.PUBLIC_KEY_SIZE || Base64.getEncoder().encodeToString(raw) != value) return null
        return if (Ed25519.validatePublicKeyFull(raw, 0)) raw else null
    }

    /** Comma-separated embedded keys; malformed entries are dropped (and leave the updater unavailable if none remain). */
    fun parsePublicKeys(value: String): List<ByteArray> =
        value.split(',').map { it.trim() }.filter { it.isNotEmpty() }.mapNotNull(::parsePublicKey)

    fun keyId(publicKey: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(publicKey).toHex().take(16)

    /** True only for a well-formed signature document with a valid signature by one of [publicKeys]. */
    fun verify(manifest: ByteArray, signatureFile: ByteArray, publicKeys: List<ByteArray>): Boolean {
        val entries = parseDocument(signatureFile) ?: return false
        val message = CONTEXT + manifest
        return publicKeys.any { key ->
            val id = keyId(key)
            entries.any { (entryKeyId, signature) ->
                entryKeyId == id && runCatching {
                    Ed25519.verify(Base64.getDecoder().decode(signature), 0, key, 0, message, 0, message.size)
                }.getOrDefault(false)
            }
        }
    }

    /** The (keyId, signature) entries of a well-formed document, or `null`; any deviation from the format rejects it. */
    private fun parseDocument(bytes: ByteArray): List<Pair<String, String>>? {
        if (bytes.isEmpty() || bytes.size > MAX_SIGNATURE_BYTES) return null
        return runCatching { strictEntries(requireNotNull(decodeUtf8(bytes))) }.getOrNull()
    }

    private fun strictEntries(text: String): List<Pair<String, String>> {
        val root = strict.parseToJsonElement(text) as JsonObject
        require(root.keys == setOf("schemaVersion", "algorithm", "signatures"))
        val schema = root.getValue("schemaVersion") as JsonPrimitive
        require(!schema.isString && schema.content == "1" && schema.intOrNull == 1)
        require(root.getValue("algorithm").stringValue() == "ed25519")
        val signatures = root.getValue("signatures") as JsonArray
        require(signatures.size in 1..MAX_SIGNATURES)
        return signatures.map { element ->
            val entry = element as JsonObject
            require(entry.keys == setOf("keyId", "signature"))
            val keyId = entry.getValue("keyId").stringValue()
            val signature = entry.getValue("signature").stringValue()
            require(KEY_ID.matches(keyId) && SIGNATURE.matches(signature))
            keyId to signature
        }
    }

    private fun JsonElement.stringValue(): String {
        val primitive = this as JsonPrimitive
        require(primitive.isString)
        return primitive.content
    }
}

internal fun decodeUtf8(bytes: ByteArray): String? = runCatching {
    Charsets.UTF_8.newDecoder()
        .onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
        .onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT)
        .decode(java.nio.ByteBuffer.wrap(bytes))
        .toString()
}.getOrNull()

internal fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it) }
