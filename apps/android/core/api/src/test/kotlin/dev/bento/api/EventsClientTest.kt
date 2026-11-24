package dev.bento.api

import dev.bento.engine.EngineState
import dev.bento.engine.WorkerMode
import dev.bento.testing.ServerProofSigner
import dev.bento.testing.TEST_SERVER_KEY
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.flow.take
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import mockwebserver3.Dispatcher
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.RecordedRequest
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** `/api/events` (api/android-endpoints.md §11 Events): stream, reconnect with replay, polling fallback. */
class EventsClientTest {
    private val server = MockWebServer()
    private lateinit var http: BentoHttp

    @Before
    fun setUp() {
        server.start()
        val ready = EngineState.Ready(server.port, "secret-token", TEST_SERVER_KEY, WorkerMode.FULL)
        val client = OkHttpClient.Builder()
            .addInterceptor(LoopbackAuthInterceptor { ready })
            .addNetworkInterceptor(ServerProofSigner(TEST_SERVER_KEY))
            .build()
        http = BentoHttp(client, { ready })
    }

    @After
    fun tearDown() = server.close()

    private fun stream(vararg events: Pair<String, String>) = MockResponse.Builder()
        .addHeader("Content-Type", "text/event-stream")
        .body("retry: 5\n" + events.joinToString("") { (event, data) -> ": ping\nevent: $event\ndata: $data\n\n" })
        .build()

    private fun events(client: EventsClient, count: Int): List<ServerEvent> =
        runBlocking { withTimeout(10_000) { client.events().take(count).toList() } }

    @Test
    fun `stream events pass through with their topics`() {
        server.enqueue(stream("ready" to """{"topics":["library","jobs"]}""", "change" to """{"topics":["library"]}"""))
        val got = events(EventsClient(http), 2)
        assertEquals(listOf("ready", "change"), got.map { it.event })
        assertEquals("""{"topics":["library"]}""", got[1].data)
        val request = server.takeRequest()
        assertEquals("/api/events", request.url.encodedPath)
        assertEquals("Bearer secret-token", request.headers["Authorization"])
    }

    @Test
    fun `a reconnected stream replays every topic once, since nothing is replayed by the server`() {
        server.enqueue(stream("ready" to """{"topics":[]}"""))
        server.enqueue(stream("ready" to """{"topics":[]}""", "change" to """{"topics":["sync"]}"""))
        val got = events(EventsClient(http), 4)
        assertEquals(listOf("ready", "change", "ready", "change"), got.map { it.event })
        assertEquals(EventsClient.ALL_TOPICS_JSON, got[1].data)
        assertEquals("""{"topics":["sync"]}""", got[3].data)
        assertEquals(2, server.requestCount)
    }

    @Test
    fun `failing streams back off, then fall back to polling`() {
        val jobs = AtomicInteger()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when (request.url.encodedPath) {
                "/api/events" -> MockResponse.Builder().code(404).body("""{"error":{"code":"not_found","message":"x"}}""").build()
                "/api/jobs" -> MockResponse.Builder().body("""{"items":[],"n":${jobs.incrementAndGet()}}""").build()
                else -> MockResponse.Builder().body("{}").build()
            }
        }
        val client = EventsClient(http, pollMs = 10, backoff = Backoff(initialMs = 10, maxMs = 20), maxFailures = 2)
        val got = events(client, 1)
        assertEquals(EventsClient.CHANGED, got.single().event)
        assertTrue(jobs.get() >= 2)
    }

    @Test
    fun `backoff starts at the server hint and doubles up to the cap`() {
        val backoff = Backoff(initialMs = 1_000, maxMs = 30_000)
        assertEquals(1_000, backoff.delayFor(1, null))
        assertEquals(3_000, backoff.delayFor(1, 3_000))
        assertEquals(6_000, backoff.delayFor(2, 3_000))
        assertEquals(30_000, backoff.delayFor(9, 3_000))
    }

    @Test
    fun `the parser keeps the retry hint`() {
        val parser = SseParser()
        parser.line("retry: 3000")
        parser.line("retry: nope")
        assertEquals(3_000L, parser.retryMs)
    }
}
