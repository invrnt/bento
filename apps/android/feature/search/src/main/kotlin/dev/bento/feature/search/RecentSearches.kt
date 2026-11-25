package dev.bento.feature.search

import android.content.Context
import android.content.SharedPreferences
import androidx.core.content.edit
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

/** Recent searches: local to this phone only, never synced (product/android.md §4.7). */
open class RecentSearches(initial: List<String> = emptyList()) {
    private val _items = MutableStateFlow(initial)
    val items: StateFlow<List<String>> = _items.asStateFlow()

    fun add(query: String) {
        val clean = query.trim()
        if (clean.length < MIN_LENGTH) return
        _items.value = (listOf(clean) + _items.value.filterNot { it.equals(clean, ignoreCase = true) }).take(MAX)
        persist(_items.value)
    }

    fun remove(query: String) {
        _items.value = _items.value - query
        persist(_items.value)
    }

    fun clear() {
        _items.value = emptyList()
        persist(emptyList())
    }

    protected open fun persist(items: List<String>) = Unit

    companion object {
        const val MAX = 12
        private const val MIN_LENGTH = 2
    }
}

class SharedRecentSearches private constructor(private val prefs: SharedPreferences, initial: List<String>) : RecentSearches(initial) {
    override fun persist(items: List<String>) {
        prefs.edit { putString(KEY, json.encodeToString(ListSerializer(String.serializer()), items)) }
    }

    companion object {
        private const val KEY = "recent"
        private val json = Json { ignoreUnknownKeys = true }

        fun create(context: Context): SharedRecentSearches {
            val prefs = context.getSharedPreferences("bento_search", Context.MODE_PRIVATE)
            val initial = prefs.getString(KEY, null)?.let {
                runCatching { json.decodeFromString(ListSerializer(String.serializer()), it) }.getOrNull()
            }
            return SharedRecentSearches(prefs, initial.orEmpty())
        }
    }
}
