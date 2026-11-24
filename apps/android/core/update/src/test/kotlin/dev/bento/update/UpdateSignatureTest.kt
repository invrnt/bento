package dev.bento.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdateSignatureTest {
    private val key = TestKey()
    private val manifest = manifestJson()

    @Test
    fun validSignatureVerifies() {
        assertTrue(UpdateSignature.verify(manifest, key.document(manifest), listOf(key.raw)))
    }

    @Test
    fun desktopSignedFixtureVerifies() {
        // Produced by apps/desktop/src/main/update-signature.ts (Node crypto): same format, same key handling.
        val publicKey = UpdateSignature.parsePublicKey(resource("fixture/public-key.txt").readText().trim())
        assertNotNull(publicKey)
        val bytes = resource("fixture/manifest.json").readBytes()
        val sig = resource("fixture/manifest.json.sig").readBytes()
        assertTrue(UpdateSignature.verify(bytes, sig, listOf(publicKey!!)))
        assertEquals("0c68d1de27cfcee8", UpdateSignature.keyId(publicKey))
        assertFalse(UpdateSignature.verify(bytes + ' '.code.toByte(), sig, listOf(publicKey)))
    }

    @Test
    fun tamperedManifestFails() {
        val sig = key.document(manifest)
        val tampered = manifest.decodeToString().replace("1234", "1235").toByteArray()
        assertFalse(UpdateSignature.verify(tampered, sig, listOf(key.raw)))
    }

    @Test
    fun tamperedSignatureFails() {
        val sig = key.document(manifest).decodeToString()
        val value = Regex("\"signature\":\"([^\"]+)\"").find(sig)!!.groupValues[1]
        val flipped = (if (value[0] == 'A') "B" else "A") + value.drop(1)
        assertFalse(UpdateSignature.verify(manifest, sig.replace(value, flipped).toByteArray(), listOf(key.raw)))
    }

    @Test
    fun wrongKeyFails() {
        val other = TestKey()
        assertFalse(UpdateSignature.verify(manifest, other.document(manifest), listOf(key.raw)))
        // A valid signature by another key relabeled with our key id still fails.
        val relabeled = other.document(manifest).decodeToString().replace(other.keyId, key.keyId).toByteArray()
        assertFalse(UpdateSignature.verify(manifest, relabeled, listOf(key.raw)))
    }

    @Test
    fun rotationAcceptsAnyEmbeddedKey() {
        val old = TestKey()
        val doc = key.document(manifest, old.keyId to old.signature(manifest))
        assertTrue(UpdateSignature.verify(manifest, doc, listOf(old.raw)))
        assertTrue(UpdateSignature.verify(manifest, doc, listOf(TestKey().raw, key.raw)))
    }

    @Test
    fun malformedDocumentsFail() {
        val sig = key.signature(manifest)
        val cases = listOf(
            """{"schemaVersion":2,"algorithm":"ed25519","signatures":[{"keyId":"${key.keyId}","signature":"$sig"}]}""",
            """{"schemaVersion":"1","algorithm":"ed25519","signatures":[{"keyId":"${key.keyId}","signature":"$sig"}]}""",
            """{"schemaVersion":1,"algorithm":"rsa","signatures":[{"keyId":"${key.keyId}","signature":"$sig"}]}""",
            """{"schemaVersion":1,"algorithm":"ed25519","signatures":[]}""",
            """{"schemaVersion":1,"algorithm":"ed25519","signatures":[{"keyId":"${key.keyId}","signature":"$sig","x":1}]}""",
            """{"schemaVersion":1,"algorithm":"ed25519","extra":true,"signatures":[{"keyId":"${key.keyId}","signature":"$sig"}]}""",
            """{"schemaVersion":1,"algorithm":"ed25519","signatures":[{"keyId":"${key.keyId.uppercase()}","signature":"$sig"}]}""",
            "not json",
            ""
        )
        cases.forEach { assertFalse(it, UpdateSignature.verify(manifest, it.toByteArray(), listOf(key.raw))) }
        val tooMany = (1..5).joinToString(",") { """{"keyId":"${key.keyId}","signature":"$sig"}""" }
        assertFalse(UpdateSignature.verify(manifest, """{"schemaVersion":1,"algorithm":"ed25519","signatures":[$tooMany]}""".toByteArray(), listOf(key.raw)))
        assertFalse(UpdateSignature.verify(manifest, ByteArray(UpdateSignature.MAX_SIGNATURE_BYTES + 1) { ' '.code.toByte() }, listOf(key.raw)))
    }

    @Test
    fun publicKeysMustBeCanonicalBase64Of32Bytes() {
        assertNotNull(UpdateSignature.parsePublicKey(key.base64))
        assertNull(UpdateSignature.parsePublicKey(""))
        assertNull(UpdateSignature.parsePublicKey(key.base64.dropLast(1)))
        assertNull(UpdateSignature.parsePublicKey("A".repeat(43) + "="))
        assertEquals(2, UpdateSignature.parsePublicKeys(" ${key.base64}, junk ,${TestKey().base64}").size)
        assertTrue(UpdateSignature.parsePublicKeys("").isEmpty())
    }
}
