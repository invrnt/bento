package dev.bento.api

import kotlin.coroutines.coroutineContext
import kotlinx.coroutines.channels.trySendBlocking
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.channelFlow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.isActive

/** One server-sent event. */
data class ServerEvent(val event: String, val data: String, val id: String?)

/** Incremental `text/event-stream` parser (WHATWG rules: `event:`, `data:` joined by newlines, `id:`, blank line dispatches). */
class SseParser {
    private var event: String? = null
    private val data = StringBuilder()
    private var id: String? = null
    private var hasData = false

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

/**
 * Invalidation signals for repositories (architecture/android-runtime.md §8: one streaming connection, no
 * polling while connected). The backend has no event stream yet (api/jobs-events-contract.md is
 * request/response), so [events] polls `/api/jobs` + `/api/sync/status` every [pollMs] and emits a
 * `changed` event when either fingerprint moves. When a stream route lands, switch [streamPath] on and the
 * same flow carries server events.
 */
class EventsClient(
    private val http: BentoHttp,
    private val pollMs: Long = 5_000,
    private val streamPath: String? = null
) {
    fun events(): Flow<ServerEvent> = streamPath?.let(::stream) ?: poll()

    private fun stream(path: String): Flow<ServerEvent> = channelFlow {
        val parser = SseParser()
        http.execute("GET", path) { response ->
            val source = response.body.source()
            while (!source.exhausted()) {
                val line = source.readUtf8Line() ?: break
                parser.line(line)?.let { trySendBlocking(it) }
            }
        }
    }

    private fun poll(): Flow<ServerEvent> = flow {
        var last: String? = null
        while (coroutineContext.isActive) {
            val fingerprint = runCatching {
                val jobs = http.execute("GET", "/api/jobs", listOf("limit" to "20")) { it.body.string() }
                val sync = http.execute("GET", "/api/sync/status") { it.body.string() }
                (jobs + sync).hashCode().toString()
            }.getOrNull()
            if (fingerprint != null && fingerprint != last) {
                if (last != null) emit(ServerEvent("changed", fingerprint, null))
                last = fingerprint
            }
            delay(pollMs)
        }
    }
}
