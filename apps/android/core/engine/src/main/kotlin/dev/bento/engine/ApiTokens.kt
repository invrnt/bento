package dev.bento.engine

import java.security.SecureRandom
import java.util.Base64

/** Per-start loopback API secrets (architecture/android-runtime.md §2.1). */
object ApiTokens {
    private val random = SecureRandom()

    /** 32 random bytes, base64url without padding. */
    fun generate(): String = random(32)

    /** A request nonce for `X-Bento-Nonce` (16 random bytes, base64url). */
    fun nonce(): String = random(16)

    private fun random(size: Int): String {
        val raw = ByteArray(size).also(random::nextBytes)
        return Base64.getUrlEncoder().withoutPadding().encodeToString(raw)
    }
}

/** The bearer [token] one API start accepts and the [serverKey] it signs `X-Bento-Proof` with. Never logged. */
class ApiCredentials(val token: String, val serverKey: String) {
    override fun toString(): String = "ApiCredentials(<redacted>)"
}
