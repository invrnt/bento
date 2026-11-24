package dev.bento.engine

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RedactionTest {
    @Test
    fun `bearer tokens, registered secrets and key-like strings are removed`() {
        Redaction.register("s3cret-token-value")
        val text = Redaction.redact(
            "GET /api/health Authorization: Bearer abc.def-123 token=s3cret-token-value key=" + "A".repeat(43),
        )
        assertFalse(text.contains("abc.def-123"))
        assertFalse(text.contains("s3cret-token-value"))
        assertFalse(text.contains("A".repeat(43)))
        assertTrue(text.contains("GET /api/health"))
    }

    @Test
    fun `api tokens are 32 random bytes in base64url`() {
        val token = ApiTokens.generate()
        assertEquals(43, token.length)
        assertTrue(token.matches(Regex("[A-Za-z0-9_-]+")))
        assertFalse(token == ApiTokens.generate())
    }
}
