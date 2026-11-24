package dev.bento.engine.bridge

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.fail
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import javax.crypto.KeyGenerator

/** Round trip with a software AES key (AndroidKeystore itself is covered by the instrumented test). */
class KeystoreKeyWrappingTest {
    @get:Rule
    val temp = TemporaryFolder()

    private val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()

    @Test
    fun `creates once and unwraps the same key on later starts`() {
        val file = temp.root.resolve("secure/wrapping.bin")
        val first = KeystoreKeyWrapping(file, { key }).deviceWrappingKey()
        assertEquals(32, first.size)
        val blob = file.readBytes()
        assertEquals(1 + 12 + 32 + 16, blob.size)
        assertFalse("never stored in plaintext", blob.toList().windowed(32).any { it == first.toList() })
        assertArrayEquals(first, KeystoreKeyWrapping(file, { key }).deviceWrappingKey())
    }

    @Test
    fun `a different wrapping key cannot unwrap`() {
        val file = temp.root.resolve("wrapping.bin")
        KeystoreKeyWrapping(file, { key }).deviceWrappingKey()
        val other = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        try {
            KeystoreKeyWrapping(file, { other }).deviceWrappingKey()
            fail("expected io")
        } catch (expected: BridgeException) {
            assertEquals(BridgeException.IO, expected.code)
        }
    }

    @Test
    fun `unknown formats are rejected`() {
        val file = temp.root.resolve("wrapping.bin").apply { writeBytes(ByteArray(10)) }
        try {
            KeystoreKeyWrapping(file, { key }).deviceWrappingKey()
            fail("expected io")
        } catch (expected: BridgeException) {
            assertEquals(BridgeException.IO, expected.code)
        }
    }
}
