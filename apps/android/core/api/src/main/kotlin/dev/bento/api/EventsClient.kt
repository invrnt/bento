package dev.bento.api

import java.io.IOException
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.channels.ProducerScope
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.channelFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

/** One server-sent event. */
data class ServerEvent(val event: String, val data: String, val id: String?)

/** Incremental `text/event-stream` parser (WHATWG rules: `event:`, `data:` joined by newlines, `id:`, blank line dispatches). */
class SseParser {
    private var event: String? = null
    private val data = StringBuilder()
    private var id: String? = null
    private var hasData = false

    /** Last `retry:` value the server sent (reconnection delay in ms), if any. */
    var retryMs: Long? = null
        private set

    /** Feed one line (without the terminator); returns an event when the line dispatches one. */
    fun line(raw: String): ServerEvent? {
        if (raw.isEmpty()) return dispatch()
        if (raw.startsWith(":")) return null
        val colon = raw.indexOf(':')
        val field = if (colon < 0) raw else raw.substring(0, colon)
        var value = if (colon < 0) "" else raw.substring(colon + 1)
        if (value.startsWith(" ")) value = value.substring(1)
        when (field) {
            "event" -> event = value

            "data" -> {
                if (hasData) data.append('\n')
                data.append(value)
                hasData = true
            }

            "id" -> if (!value.contains('\u0000')) id = value

            "retry" -> value.toLongOrNull()?.takeIf { it >= 0 }?.let { retryMs = it }
        }
        return null
    }

    private fun dispatch(): ServerEvent? {
        val result = if (hasData) ServerEvent(event ?: "message", data.toString(), id) else null
        event = null
        data.setLength(0)
        hasData = false
        return result
    }
}

/** Reconnection delays: the server's `retry:` hint first, then doubling up to [maxMs]. */
data class Backoff(val initialMs: Long = 1_000, val maxMs: Long = 30_000) {
    fun delayFor(failures: Int, serverRetryMs: Long?): Long {
        val base = serverRetryMs ?: initialMs
        if (failures <= 1) return base
        val shift = (failures - 1).coerceAtMost(MAX_SHIFT)
        return (base shl shift).coerceAtMost(maxMs)
    }

    private companion object {
        const val MAX_SHIFT = 10
    }
}

/**
 * Invalidation signals for repositories (architecture/android-runtime.md §8: one streaming connection, no polling
 * while connected). [events] follows `GET /api/events` (api/android-endpoints.md §11 Events): `change` events name
 * the topics that moved. A dropped stream reconnects with [Backoff]; after [maxFailures] attempts in a row that never
 * reached `ready`, it polls `/api/jobs` + `/api/sync/status` for [pollFallbackMs] (emitting [CHANGED] when either
 * moves) and then tries the stream again. Nothing is replayed after a reconnect, so a stream that comes back emits one
 * [CHANGE] for every topic.
 */
class EventsClient(
    private val http: BentoHttp,
    private val pollMs: Long = 5_000,
    private val streamPath: String? = STREAM_PATH,
    private val backoff: Backoff = Backoff(),
    private val maxFailures: Int = 3,
    private val pollFallbackMs: Long = 60_000,
    private val streamReadTimeoutMs: Long = 45_000
) {
    private val streamClient by lazy { http.clientWithReadTimeout(streamReadTimeoutMs) }

    fun events(): Flow<ServerEvent> = channelFlow {
        val path = streamPath
        if (path == null) {
            poll(untilMs = null)
            return@channelFlow
        }
        var failures = 0
        var connectedBefore = false
        var serverRetry: Long? = null
        while (currentCoroutineContext().isActive) {
            val parser = SseParser()
            val reachedReady = try {
                connect(path, parser, replayAll = connectedBefore)
            } catch (cancel: CancellationException) {
                throw cancel
            } catch (error: ApiException) {
                false
            } catch (error: IOException) {
                false
            }
            serverRetry = parser.retryMs ?: serverRetry
            if (reachedReady) {
                connectedBefore = true
                failures = 0
                // A clean close (max_seconds) or a dropped stream: reconnect after the server's hint.
                delay(serverRetry ?: backoff.initialMs)
                continue
            }
            failures++
            if (failures >= maxFailures) {
                poll(untilMs = pollFallbackMs)
                failures = 0
                connectedBefore = true
            } else {
                delay(backoff.delayFor(failures, serverRetry))
            }
        }
    }

    /** One stream connection; true once the server said `ready`. */
    private suspend fun ProducerScope<ServerEvent>.connect(path: String, parser: SseParser, replayAll: Boolean): Boolean {
        val response = http.open("GET", path, client = streamClient)
        var ready = false
        coroutineScope {
            // Blocking reads do not see cancellation: closing the response ends them.
            val closer = launch {
                try {
                    awaitCancellation()
                } finally {
                    response.close()
                }
            }
            try {
                withContext(Dispatchers.IO) {
                    val source = response.body.source()
                    while (isActive) {
                        val line = source.readUtf8Line() ?: break
                        val event = parser.line(line) ?: continue
                        if (event.event == READY) {
                            ready = true
                            if (replayAll) send(ServerEvent(CHANGE, ALL_TOPICS_JSON, null))
                        }
                        send(event)
                    }
                }
            } catch (io: IOException) {
                if (!ready) throw io
            } finally {
                closer.cancel()
                response.close()
            }
        }
        return ready
    }

    /** Fingerprint polling; forever when [untilMs] is null. */
    private suspend fun ProducerScope<ServerEvent>.poll(untilMs: Long?) {
        var last: String? = null
        val body: suspend () -> Unit = {
            while (currentCoroutineContext().isActive) {
                val fingerprint = try {
                    val jobs = http.execute("GET", "/api/jobs", listOf("limit" to "20")) { it.body.string() }
                    val sync = http.execute("GET", "/api/sync/status") { it.body.string() }
                    (jobs + sync).hashCode().toString()
                } catch (error: ApiException) {
                    null
                }
                if (fingerprint != null && fingerprint != last) {
                    if (last != null) send(ServerEvent(CHANGED, fingerprint, null))
                    last = fingerprint
                }
                delay(pollMs)
            }
        }
        if (untilMs == null) body() else withTimeoutOrNull(untilMs) { body() }
    }

    companion object {
        const val STREAM_PATH = "/api/events"
        const val READY = "ready"
        const val CHANGE = "change"

        /** Emitted by polling: something moved, topic unknown. */
        const val CHANGED = "changed"
        val ALL_TOPICS = listOf("library", "jobs", "imports", "sync")
        internal val ALL_TOPICS_JSON = ALL_TOPICS.joinToString(",", prefix = """{"topics":[""", postfix = "]}") { "\"$it\"" }
    }
}
