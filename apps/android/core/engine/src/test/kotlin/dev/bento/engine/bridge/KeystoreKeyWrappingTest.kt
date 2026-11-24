package dev.bento.engine.bridge

import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.fail
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

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
    fun `SEC-11 a different wrapping key cannot unwrap and reports the key as lost`() {
        val file = temp.root.resolve("wrapping.bin")
        KeystoreKeyWrapping(file, { key }).deviceWrappingKey()
        val other = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        try {
            KeystoreKeyWrapping(file, { other }).deviceWrappingKey()
            fail("expected key lost")
        } catch (expected: DeviceKeyLostException) {
            assertEquals(BridgeException.KEY_LOST, expected.code)
        }
    }

    @Test
    fun `SEC-11 unknown formats are reported as a lost key`() {
        val file = temp.root.resolve("wrapping.bin").apply { writeBytes(ByteArray(10)) }
        try {
            KeystoreKeyWrapping(file, { key }).deviceWrappingKey()
            fail("expected key lost")
        } catch (expected: DeviceKeyLostException) {
            assertEquals(BridgeException.KEY_LOST, expected.code)
        }
    }

    @Test
    fun `SEC-11 a missing Keystore key is never regenerated next to an existing wrapping bin`() {
        val file = temp.root.resolve("wrapping.bin")
        KeystoreKeyWrapping(file, { key }).deviceWrappingKey()
        val source = LosableKeySource()
        source.current = null // the Keystore alias is gone
        try {
            KeystoreKeyWrapping(file, source).deviceWrappingKey()
            fail("expected key lost")
        } catch (expected: DeviceKeyLostException) {
            assertEquals(0, source.created)
        }
        // Reset forgets both; the next start creates a fresh pair.
        KeystoreKeyWrapping(file, source).reset()
        assertFalse(file.exists())
        assertEquals(1, source.deleted)
        val fresh = KeystoreKeyWrapping(file, source).deviceWrappingKey()
        assertEquals(1, source.created)
        assertArrayEquals(fresh, KeystoreKeyWrapping(file, source).deviceWrappingKey())
        assertFalse(temp.root.resolve("wrapping.bin.tmp").exists())
    }

    private class LosableKeySource : WrappingKeySource {
        var current: SecretKey? = null
        var created = 0
        var deleted = 0

        override fun key(): SecretKey = current ?: KeyGenerator.getInstance("AES").apply { init(256) }.generateKey().also {
            created += 1
            current = it
        }

        override fun existingKey(): SecretKey? = current

        override fun delete() {
            deleted += 1
            current = null
        }
    }
}
