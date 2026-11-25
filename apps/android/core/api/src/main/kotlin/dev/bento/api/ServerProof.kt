package dev.bento.api

import java.io.IOException
import java.security.MessageDigest
import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * `X-Bento-Proof` (architecture/android-runtime.md §2.1): base64url(HMAC-SHA256(serverKey, "bento-server-proof-v1|port|nonce")).
 * Mirrors `bento.interfaces.android.server_proof`; the shared test vector lives in both test suites.
 */
object ServerProof {
    const val NONCE_HEADER = "X-Bento-Nonce"
    const val PROOF_HEADER = "X-Bento-Proof"
    private const val LABEL = "bento-server-proof-v1"

    fun proof(serverKey: String, port: Int, nonce: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(serverKey.toByteArray(Charsets.UTF_8), "HmacSHA256"))
        val digest = mac.doFinal("$LABEL|$port|$nonce".toByteArray(Charsets.US_ASCII))
        return Base64.getUrlEncoder().withoutPadding().encodeToString(digest)
    }

    /** Constant-time check of a received proof. */
    fun verify(serverKey: String, port: Int, nonce: String, received: String?): Boolean {
        if (received.isNullOrEmpty()) return false
        return MessageDigest.isEqual(proof(serverKey, port, nonce).toByteArray(), received.toByteArray())
    }
}

/** Something other than this engine's API answered on its port; the response was dropped unread. */
class UnverifiedServerException(val port: Int) : IOException("loopback server on port $port failed the identity check")
