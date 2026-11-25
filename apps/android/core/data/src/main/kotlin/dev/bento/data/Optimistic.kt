package dev.bento.data

import dev.bento.api.ApiException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

/**
 * Local overrides layered over server data while a mutation is in flight (and until the next refresh
 * confirms it). Paging flows apply them with `pagingData.map { overlay.apply(it.id, it) }` /
 * `filter { !overlay.isHidden(it.id) }`.
 */
class OverlayStore<V> {
    sealed interface Change<out V> {
        data class Replace<V>(val value: V) : Change<V>

        data object Hide : Change<Nothing>
    }

    private val _changes = MutableStateFlow<Map<String, Change<V>>>(emptyMap())
    val changes: StateFlow<Map<String, Change<V>>> = _changes.asStateFlow()

    fun replace(id: String, value: V) = _changes.update { it + (id to Change.Replace(value)) }

    fun hide(id: String) = _changes.update { it + (id to Change.Hide) }

    fun clear(id: String) = _changes.update { it - id }

    fun clearAll() = _changes.update { emptyMap() }

    fun isHidden(id: String, snapshot: Map<String, Change<V>> = changes.value): Boolean = snapshot[id] is Change.Hide

    @Suppress("UNCHECKED_CAST")
    fun apply(id: String, original: V, snapshot: Map<String, Change<V>> = changes.value): V =
        (snapshot[id] as? Change.Replace<V>)?.value ?: original
}

/** Result of an optimistic mutation; [undo] reverts it (the `Deshacer` snackbar action). */
class Undoable internal constructor(private val revert: suspend () -> Unit) {
    private var undone = false

    suspend fun undo() {
        if (undone) return
        undone = true
        revert()
    }
}

/**
 * Runs an optimistic mutation: [applyLocal] immediately, [remote] on the API, rollback on failure (the
 * error is rethrown for the UI), and returns an [Undoable] that runs [inverse] and restores the view.
 */
suspend fun optimistic(
    applyLocal: () -> Unit,
    rollbackLocal: () -> Unit,
    remote: suspend () -> Unit,
    inverse: suspend () -> Unit,
    onSettled: () -> Unit = {}
): Undoable {
    applyLocal()
    try {
        remote()
    } catch (error: ApiException) {
        rollbackLocal()
        throw error
    } finally {
        onSettled()
    }
    return Undoable {
        rollbackLocal()
        try {
            inverse()
        } finally {
            onSettled()
        }
    }
}
