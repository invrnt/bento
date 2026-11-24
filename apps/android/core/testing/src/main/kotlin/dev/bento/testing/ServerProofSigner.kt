package dev.bento.testing

import dev.bento.api.ServerProof
import okhttp3.Interceptor
import okhttp3.Response

/**
 * Plays the embedded API's `ServerProofMiddleware` for JVM tests against MockWebServer: add it as a network
 * interceptor so responses carry the `X-Bento-Proof` the real API would send for [serverKey].
 */
class ServerProofSigner(private val serverKey: String) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val response = chain.proceed(request)
        val nonce = request.header(ServerProof.NONCE_HEADER) ?: return response
        return response.newBuilder()
            .header(ServerProof.PROOF_HEADER, ServerProof.proof(serverKey, request.url.port, nonce))
            .build()
    }
}

/** A server key for test `EngineState.Ready` values. */
const val TEST_SERVER_KEY = "test-server-key-0123456789abcdef0123"
