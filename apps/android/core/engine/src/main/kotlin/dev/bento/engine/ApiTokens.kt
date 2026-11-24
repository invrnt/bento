package dev.bento.engine

import java.security.SecureRandom
import java.util.Base64

/** Per-process loopback API tokens (architecture/android-runtime.md §2). */
object ApiTokens {
    private val random = SecureRandom()

    /** 32 random bytes, base64url without padding. */
    fun generate(): String {
        val raw = ByteArray(32).also(random::nextBytes)
        return Base64.getUrlEncoder().withoutPadding().encodeToString(raw)
    }
}
