package dev.bento.data

import androidx.paging.InvalidatingPagingSourceFactory
import androidx.paging.PagingSource
import dev.bento.api.EventsClient
import dev.bento.api.ServerEvent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/** What changed; repositories invalidate the matching paging sources and caches. */
enum class Topic { TIMELINE, DRIVE, SEARCH, ALBUMS, TRASH, ACTIVITY, DEVICES, SETTINGS, ACCOUNT }

/** Fan-out of invalidations from server events and local mutations. */
class Invalidations {
    private val _topics = MutableSharedFlow<Set<Topic>>(extraBufferCapacity = 16, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val topics: SharedFlow<Set<Topic>> = _topics.asSharedFlow()

    fun invalidate(vararg topics: Topic) {
        _topics.tryEmit(topics.toSet())
    }

    fun invalidateAll() {
        _topics.tryEmit(Topic.entries.toSet())
    }

    /** Server events: a stream `change` invalidates what its topics feed; a polling `changed` (topic unknown) all. */
    fun follow(events: EventsClient, scope: CoroutineScope) {
        events.events().onEach { event ->
            when (event.event) {
                EventsClient.CHANGE -> topicsOf(event)?.let { _topics.tryEmit(it) } ?: invalidateAll()
                EventsClient.CHANGED -> invalidateAll()
            }
        }.catch { }.launchIn(scope)
    }

    /** A paging-source factory that is invalidated whenever one of [topics] changes. */
    fun <K : Any, V : Any> pagingFactory(
        scope: CoroutineScope,
        vararg topics: Topic,
        create: () -> PagingSource<K, V>
    ): InvalidatingPagingSourceFactory<K, V> {
        val factory = InvalidatingPagingSourceFactory(create)
        val wanted = topics.toSet()
        this.topics.onEach { changed -> if (changed.any { it in wanted }) factory.invalidate() }.launchIn(scope)
        return factory
    }
}

/**
 * What each `/api/events` topic feeds (api/android-endpoints.md §11 Events): `library` → Drive, Photos, albums, search;
 * `jobs` → jobs, Activity, backup status; `imports` → import progress (Activity); `sync` → sync status, vault, devices.
 */
internal val EVENT_TOPICS: Map<String, Set<Topic>> = mapOf(
    "library" to setOf(Topic.TIMELINE, Topic.DRIVE, Topic.SEARCH, Topic.ALBUMS, Topic.TRASH),
    "jobs" to setOf(Topic.ACTIVITY, Topic.SETTINGS),
    "imports" to setOf(Topic.ACTIVITY),
    "sync" to setOf(Topic.ACTIVITY, Topic.DEVICES, Topic.ACCOUNT)
)

/** The repository topics a `change` event names; null when its data is unreadable (callers invalidate all). */
internal fun topicsOf(event: ServerEvent): Set<Topic>? {
    val root = runCatching { Json.parseToJsonElement(event.data) }.getOrNull() as? JsonObject ?: return null
    val names = (root["topics"] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull } ?: return null
    val topics = names.flatMap { EVENT_TOPICS[it].orEmpty() }.toSet()
    // An unknown topic from a newer backend: refresh everything rather than miss it.
    return if (names.any { it !in EVENT_TOPICS }) Topic.entries.toSet() else topics
}
