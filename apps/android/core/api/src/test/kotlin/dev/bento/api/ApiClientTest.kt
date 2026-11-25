package dev.bento.api

import dev.bento.api.generated.BentoEndpoints
import dev.bento.engine.EngineState
import dev.bento.engine.WorkerMode
import dev.bento.testing.ServerProofSigner
import dev.bento.testing.TEST_SERVER_KEY
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import okhttp3.Request
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

class ApiErrorsTest {
    @Test
    fun `backend error bodies map to typed errors`() {
        val error = ApiErrors.from(
            404,
            """{"error":{"code":"asset_not_found","message":"Asset not found","details":{"id":"a1"},"request_id":"r-1"}}"""
        )
        assertEquals(ApiErrorKind.NOT_FOUND, error.kind)
        assertEquals("asset_not_found", error.code)
        assertEquals("r-1", error.requestId)
        assertEquals("a1", error.details!!["id"].toString().trim('"'))
    }

    @Test
    fun `status mapping follows the error model`() {
        val expected = mapOf(
            400 to ApiErrorKind.BAD_REQUEST, 401 to ApiErrorKind.UNAUTHORIZED, 409 to ApiErrorKind.CONFLICT,
            413 to ApiErrorKind.PAYLOAD_TOO_LARGE, 415 to ApiErrorKind.UNSUPPORTED_MEDIA, 422 to ApiErrorKind.VALIDATION,
            429 to ApiErrorKind.RATE_LIMITED, 500 to ApiErrorKind.SERVER, 503 to ApiErrorKind.UNAVAILABLE
        )
        expected.forEach { (status, kind) -> assertEquals("status $status", kind, ApiErrors.kindFor(status)) }
    }

    @Test
    fun `fastapi validation, empty bodies and retry-after`() {
        val validation = ApiErrors.from(422, """{"detail":[{"loc":["body","x"],"msg":"field required"}]}""")
        assertEquals("validation_failed", validation.code)
        val empty = ApiErrors.from(401, "")
        assertEquals("api_token_required", empty.code)
        val limited = ApiErrors.from(429, """{"error":{"code":"telegram_flood_wait","message":"wait"}}""", retryAfter = "240")
        assertEquals(240L, limited.retryAfterSeconds)
        assertTrue(limited.isRetryable)
        assertTrue(!ApiErrors.from(404, null).isRetryable)
    }
}

class BentoHttpTest {
    private val server = MockWebServer()
    private var ready: EngineState.Ready? = null
    private var stalls = 0
    private val unverified = mutableListOf<Int>()
    private lateinit var http: BentoHttp

    @Before
    fun setUp() {
        server.start()
        ready = EngineState.Ready(server.port, "secret-token", TEST_SERVER_KEY, WorkerMode.FULL)
        val client = OkHttpClient.Builder()
            .addInterceptor(LoopbackAuthInterceptor(onUnverified = { unverified += it }) { ready })
            .addNetworkInterceptor(ServerProofSigner(TEST_SERVER_KEY))
            .readTimeout(500, TimeUnit.MILLISECONDS)
            .build()
        http = BentoHttp(
            client,
            object : EndpointProvider {
                override suspend fun ready(): EngineState.Ready = ready ?: throw ApiException.EngineUnavailable()

                override fun reportStall() {
                    stalls += 1
                }
            }
        )
    }

    @After
    fun tearDown() = server.close()

    @Test
    fun `generated endpoints call the loopback port with the bearer token`() = runTest {
        server.enqueue(
            MockResponse.Builder().body("""{"status":"ok","storage_backend":"fake","telegram_configured":false,"extra":1}""").build()
        )
        val health = BentoEndpoints(http).health()
        assertEquals("ok", health.status)
        val request = server.takeRequest()
        assertEquals("/api/health", request.url.encodedPath)
        assertEquals("Bearer secret-token", request.headers["Authorization"])
        assertTrue(request.headers[ServerProof.NONCE_HEADER].orEmpty().length >= 16)
    }

    @Test
    fun `SEC-01 a response without a valid server proof is dropped and reported`() {
        val squatter = MockWebServer().apply { start() }
        // Another app answering on the engine's port: it cannot sign with the per-start server key.
        squatter.enqueue(MockResponse.Builder().body("{}").build())
        squatter.enqueue(MockResponse.Builder().addHeader(ServerProof.PROOF_HEADER, "forged").body("{}").build())
        val current = EngineState.Ready(squatter.port, "secret-token", TEST_SERVER_KEY, WorkerMode.FULL)
        val reported = mutableListOf<Int>()
        val client = OkHttpClient.Builder().addInterceptor(LoopbackAuthInterceptor(onUnverified = { reported += it }) { current })
            .addNetworkInterceptor(ServerProofSigner("some-other-key-0123456789abcdef0123")).build()
        repeat(2) {
            try {
                client.newCall(Request.Builder().url("http://127.0.0.1:${squatter.port}/api/health").build()).execute().close()
                fail("expected UnverifiedServerException")
            } catch (expected: UnverifiedServerException) {
                assertEquals(squatter.port, expected.port)
            }
        }
        assertEquals(listOf(squatter.port, squatter.port), reported)
        squatter.close()
    }

    @Test
    fun `SEC-01 a request built for an old port gets no token`() {
        val old = MockWebServer().apply { start() }
        old.enqueue(MockResponse.Builder().body("ok").build())
        val client = OkHttpClient.Builder().addInterceptor(LoopbackAuthInterceptor { ready }).build()
        client.newCall(Request.Builder().url("http://127.0.0.1:${old.port}/api/health").build()).execute().close()
        val request = old.takeRequest()
        assertNull(request.headers["Authorization"])
        assertNull(request.headers[ServerProof.NONCE_HEADER])
        old.close()
    }

    @Test
    fun `SEC-01 server proof matches the backend test vector`() {
        // Same vector as tests/unit/android/test_security_review_findings.py (Python).
        assertEquals(
            "gUIkCMgwLLTTAlQIPwi9Rt5QVQlaB93G7MgR42IWw8g",
            ServerProof.proof("server-key-0123456789abcdef0123456789", 41000, "nonce-0123456789ab")
        )
        assertTrue(ServerProof.verify("k".repeat(32), 1, "n", ServerProof.proof("k".repeat(32), 1, "n")))
        assertTrue(!ServerProof.verify("k".repeat(32), 2, "n", ServerProof.proof("k".repeat(32), 1, "n")))
        assertTrue(!ServerProof.verify("k".repeat(32), 1, "n", null))
    }

    @Test
    fun `query parameters skip nulls and encode values`() = runTest {
        server.enqueue(MockResponse.Builder().body("""{"groups":[],"next_cursor":null}""").build())
        val page = BentoEndpoints(http).photosTimeline(cursor = null, limit = 120)
        assertNull(page.nextCursor)
        val request = server.takeRequest()
        assertEquals("limit=120", request.url.encodedQuery)
    }

    @Test
    fun `error responses throw ApiException Http`() = runTest {
        server.enqueue(MockResponse.Builder().code(409).body("""{"error":{"code":"invalid_folder_move","message":"cycle"}}""").build())
        try {
            BentoEndpoints(http).health()
            fail("expected ApiException")
        } catch (expected: ApiException.Http) {
            assertEquals("invalid_folder_move", expected.code)
            assertEquals(ApiErrorKind.CONFLICT, expected.kind)
        }
    }

    @Test
    fun `stalled calls report a stall`() = runTest {
        server.enqueue(MockResponse.Builder().body("{}").headersDelay(2, TimeUnit.SECONDS).build())
        try {
            BentoEndpoints(http).health()
            fail("expected stall")
        } catch (expected: ApiException.Stalled) {
            assertEquals(1, stalls)
        }
    }

    @Test
    fun `engine unavailable surfaces as ApiException`() = runTest {
        ready = null
        try {
            BentoEndpoints(http).health()
            fail("expected EngineUnavailable")
        } catch (expected: ApiException.EngineUnavailable) {
            assertTrue(expected.isRetryable)
        }
    }

    @Test
    fun `decoding drift is reported as Decoding`() = runTest {
        server.enqueue(MockResponse.Builder().body("""{"unexpected":true}""").build())
        try {
            BentoEndpoints(http).health()
            fail("expected Decoding")
        } catch (expected: ApiException.Decoding) {
            assertTrue(!expected.isRetryable)
        }
    }

    @Test
    fun `path segments are encoded`() {
        assertEquals("a%20b%2Fc", http.encodePath("a b/c"))
    }

    @Test
    fun `token is never sent to another origin`() {
        val other = MockWebServer().apply { start() }
        other.enqueue(MockResponse.Builder().body("ok").build())
        val client = OkHttpClient.Builder().addInterceptor(LoopbackAuthInterceptor { ready }).build()
        client.newCall(Request.Builder().url(other.url("/x")).build()).execute().close()
        assertNull(other.takeRequest().headers["Authorization"])
        other.close()
    }
}

class SseParserTest {
    @Test
    fun `parses events, multi-line data, comments and ids`() {
        val parser = SseParser()
        val lines = listOf(": keepalive", "event: job", "data: {\"a\":1}", "data: {\"b\":2}", "id: 7", "", "data: plain", "")
        val events = lines.mapNotNull(parser::line)
        assertEquals(
            listOf(ServerEvent("job", "{\"a\":1}\n{\"b\":2}", "7"), ServerEvent("message", "plain", "7")), // last event id persists
            events
        )
    }

    @Test
    fun `blank line without data dispatches nothing`() {
        val parser = SseParser()
        assertNull(parser.line("event: x"))
        assertNull(parser.line(""))
    }
}

class MediaAndImageKeysTest {
    @Test
    fun `thumbnail sizes pick the nearest stored size not smaller`() {
        assertEquals(ThumbnailSize.SMALL, ThumbnailSize.atLeast(100))
        assertEquals(ThumbnailSize.MEDIUM, ThumbnailSize.atLeast(257))
        assertEquals(ThumbnailSize.LARGE, ThumbnailSize.atLeast(1024))
        assertEquals(ThumbnailSize.LARGE, ThumbnailSize.atLeast(4000))
    }

    @Test
    fun `cache keys are port independent and include the etag`() {
        assertEquals("bento:thumbnail:a1:512:e9", cacheKey(BentoImage.thumbnail("a1", "e9"), ThumbnailSize.MEDIUM))
        assertEquals("bento:preview:a1", cacheKey(BentoImage.preview("a1"), null))
    }

    @Test
    fun `bento media uris resolve to the content route on the current port`() {
        val ready = EngineState.Ready(4321, "t", "k", WorkerMode.FULL)
        assertEquals("http://127.0.0.1:4321/api/assets/a1/content", resolveBentoMediaUri("bento://asset/a1", ready))
        assertNull(resolveBentoMediaUri("https://example.com/v.mp4", ready))
        try {
            resolveBentoMediaUri("bento://asset/a1", null)
            fail("expected EngineUnavailable")
        } catch (expected: ApiException.EngineUnavailable) {
            // expected
        }
    }

    @Test
    fun `asset paths reject ids that would change the route`() {
        assertEquals("/api/assets/a1/thumbnail", AssetPaths.thumbnail("a1"))
        for (bad in listOf("", "a/b", "a?b", "a b")) {
            try {
                AssetPaths.content(bad)
                fail("expected rejection of '$bad'")
            } catch (expected: IllegalArgumentException) {
                // expected
            }
        }
    }
}
