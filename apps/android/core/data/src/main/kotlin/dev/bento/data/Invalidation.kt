package dev.bento.data

import androidx.paging.InvalidatingPagingSourceFactory
import androidx.paging.PagingSource
import dev.bento.api.EventsClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach

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

    /** Server events (jobs/sync changes) may affect every view: invalidate all. */
    fun follow(events: EventsClient, scope: CoroutineScope) {
        events.events().onEach { invalidateAll() }.catch { }.launchIn(scope)
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
