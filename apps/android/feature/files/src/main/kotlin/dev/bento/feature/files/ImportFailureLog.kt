package dev.bento.feature.files

import java.io.File
import java.util.UUID
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

/** One item that did not make it into Bento (shown in Activity with its file name; product/android.md §4.9). */
@Serializable
data class ImportFailure(val name: String, val reason: String, val atMs: Long)

/**
 * Failed and interrupted imports, persisted on this phone (`filesDir/bento/imports/`). The backend keeps import progress
 * per process only, so a batch still in the [journal] when the process starts again was interrupted by a process death:
 * its items are reported here as [REASON_INTERRUPTED] (the share grant died with the process; sharing again works).
 * Read by Cuenta y actividad (agent 41) through [entries]; never holds content, only sanitized names.
 */
class ImportFailureLog(private val directory: File, private val clock: () -> Long = System::currentTimeMillis) {
    @Serializable
    private data class JournalEntry(val id: String, val names: List<String>)

    private val json = Json { ignoreUnknownKeys = true }
    private val failuresFile get() = File(directory, "failures.json")
    private val journalFile get() = File(directory, "journal.json")
    private val _entries = MutableStateFlow(read(failuresFile, ListSerializer(ImportFailure.serializer())).orEmpty())
    val entries: StateFlow<List<ImportFailure>> = _entries.asStateFlow()

    @Synchronized
    fun record(name: String, reason: String) {
        val next = (_entries.value + ImportFailure(DisplayNames.file(name), reason, clock())).takeLast(MAX_ENTRIES)
        _entries.value = next
        write(failuresFile, ListSerializer(ImportFailure.serializer()), next)
    }

    @Synchronized
    fun dismiss(failure: ImportFailure) {
        _entries.value = _entries.value - failure
        write(failuresFile, ListSerializer(ImportFailure.serializer()), _entries.value)
    }

    @Synchronized
    fun clear() {
        _entries.value = emptyList()
        failuresFile.delete()
    }

    @Synchronized
    fun journalStart(names: List<String>): String {
        val id = UUID.randomUUID().toString()
        val journal = readJournal() + JournalEntry(id, names)
        write(journalFile, ListSerializer(JournalEntry.serializer()), journal)
        return id
    }

    @Synchronized
    fun journalFinish(id: String) {
        write(journalFile, ListSerializer(JournalEntry.serializer()), readJournal().filterNot { it.id == id })
    }

    /** At start: batches left in the journal were cut by a process death. */
    @Synchronized
    fun recoverInterrupted() {
        val pending = readJournal()
        if (pending.isEmpty()) return
        journalFile.delete()
        pending.flatMap { it.names }.forEach { record(it, REASON_INTERRUPTED) }
    }

    private fun readJournal() = read(journalFile, ListSerializer(JournalEntry.serializer())).orEmpty()

    private fun <T> read(file: File, serializer: kotlinx.serialization.KSerializer<T>): T? =
        file.takeIf { it.exists() }?.let { runCatching { json.decodeFromString(serializer, it.readText()) }.getOrNull() }

    private fun <T> write(file: File, serializer: kotlinx.serialization.KSerializer<T>, value: T) {
        directory.mkdirs()
        val tmp = File(directory, ".${file.name}.tmp")
        tmp.writeText(json.encodeToString(serializer, value))
        tmp.renameTo(file)
    }

    companion object {
        const val REASON_UNREADABLE = "content_unreadable"
        const val REASON_INTERRUPTED = "interrupted"
        const val REASON_FAILED = "import_failed"
        private const val MAX_ENTRIES = 200
    }
}
