package dev.bento.feature.files

import android.content.Context
import android.content.SharedPreferences
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.SetSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

/** A Drive folder the person used as a destination (move, upload, share). `id == null` is the Archivos root. */
@Serializable
data class Destination(val id: String?, val name: String)

enum class FilesLayout { List, Grid }

/** Plaintext disclosures shown the first time per action type (product/android.md §10). */
enum class Disclosure { Share, OpenWith, SaveToPhone }

/**
 * Local, per-phone view preferences of Archivos (never synced): sort per folder, list/grid, recent destinations
 * (move sheet, share sheet, Direct Share, search suggestions), offline pins this phone asked for, and disclosures the
 * person chose not to see again.
 */
interface FilesPreferences {
    val layout: StateFlow<FilesLayout>
    val recentDestinations: StateFlow<List<Destination>>
    val pinned: StateFlow<Set<String>>

    fun sort(folderId: String?): FolderSort

    fun setSort(folderId: String?, sort: FolderSort)

    fun setLayout(layout: FilesLayout)

    fun rememberDestination(destination: Destination)

    fun setPinned(assetId: String, pinned: Boolean)

    fun skipsDisclosure(kind: Disclosure): Boolean

    fun skipDisclosure(kind: Disclosure)

    companion object {
        const val MAX_RECENT = 8
        const val ROOT_KEY = "__root__"
    }
}

/** Shared logic; [persist] writes the snapshot (SharedPreferences on the device, nothing in tests). */
open class InMemoryFilesPreferences(
    sorts: Map<String, FolderSort> = emptyMap(),
    layout: FilesLayout = FilesLayout.List,
    recent: List<Destination> = emptyList(),
    pinned: Set<String> = emptySet(),
    skipped: Set<Disclosure> = emptySet()
) : FilesPreferences {
    protected val sorts = sorts.toMutableMap()
    protected val skipped = skipped.toMutableSet()
    private val _layout = MutableStateFlow(layout)
    private val _recent = MutableStateFlow(recent)
    private val _pinned = MutableStateFlow(pinned)
    override val layout: StateFlow<FilesLayout> = _layout.asStateFlow()
    override val recentDestinations: StateFlow<List<Destination>> = _recent.asStateFlow()
    override val pinned: StateFlow<Set<String>> = _pinned.asStateFlow()

    override fun sort(folderId: String?): FolderSort = synchronized(sorts) { sorts[folderId ?: FilesPreferences.ROOT_KEY] } ?: FolderSort()

    override fun setSort(folderId: String?, sort: FolderSort) {
        synchronized(sorts) { sorts[folderId ?: FilesPreferences.ROOT_KEY] = sort }
        persist()
    }

    override fun setLayout(layout: FilesLayout) {
        _layout.value = layout
        persist()
    }

    override fun rememberDestination(destination: Destination) {
        _recent.update { list -> (listOf(destination) + list.filterNot { it.id == destination.id }).take(FilesPreferences.MAX_RECENT) }
        persist()
    }

    override fun setPinned(assetId: String, pinned: Boolean) {
        _pinned.update { if (pinned) it + assetId else it - assetId }
        persist()
    }

    override fun skipsDisclosure(kind: Disclosure): Boolean = synchronized(skipped) { kind in skipped }

    override fun skipDisclosure(kind: Disclosure) {
        synchronized(skipped) { skipped += kind }
        persist()
    }

    protected open fun persist() = Unit
}

class SharedFilesPreferences(private val prefs: SharedPreferences) :
    InMemoryFilesPreferences(
        sorts = prefs.decode(KEY_SORTS, MapSerializer(String.serializer(), FolderSort.serializer())).orEmpty(),
        layout = prefs.getString(KEY_LAYOUT, null)?.let { runCatching { FilesLayout.valueOf(it) }.getOrNull() } ?: FilesLayout.List,
        recent = prefs.decode(KEY_RECENT, ListSerializer(Destination.serializer())).orEmpty(),
        pinned = prefs.decode(KEY_PINNED, SetSerializer(String.serializer())).orEmpty(),
        skipped = prefs.getStringSet(KEY_SKIPPED, emptySet()).orEmpty().mapNotNull {
            runCatching { Disclosure.valueOf(it) }.getOrNull()
        }.toSet()
    ) {
    override fun persist() {
        val sortsSnapshot = synchronized(sorts) { sorts.toMap() }.entries.toList().takeLast(MAX_SORTS).associate { it.key to it.value }
        prefs.edit()
            .putString(KEY_SORTS, json.encodeToString(MapSerializer(String.serializer(), FolderSort.serializer()), sortsSnapshot))
            .putString(KEY_LAYOUT, layout.value.name)
            .putString(KEY_RECENT, json.encodeToString(ListSerializer(Destination.serializer()), recentDestinations.value))
            .putString(KEY_PINNED, json.encodeToString(SetSerializer(String.serializer()), pinned.value))
            .putStringSet(KEY_SKIPPED, synchronized(skipped) { skipped.map { it.name }.toSet() })
            .apply()
    }

    companion object {
        private const val MAX_SORTS = 500
        private const val KEY_SORTS = "sorts"
        private const val KEY_LAYOUT = "layout"
        private const val KEY_RECENT = "recent_destinations"
        private const val KEY_PINNED = "pinned"
        private const val KEY_SKIPPED = "skipped_disclosures"
        private val json = Json { ignoreUnknownKeys = true }

        fun create(context: Context): SharedFilesPreferences =
            SharedFilesPreferences(context.getSharedPreferences("bento_files", Context.MODE_PRIVATE))

        private fun <T> SharedPreferences.decode(key: String, serializer: kotlinx.serialization.KSerializer<T>): T? =
            getString(key, null)?.let { runCatching { json.decodeFromString(serializer, it) }.getOrNull() }
    }
}
