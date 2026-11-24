package dev.bento.feature.files

import dev.bento.api.generated.DriveItemResponse
import java.text.Collator
import java.util.Locale
import kotlinx.serialization.Serializable

/** Sort sheet fields (product/android.md §4.5): Nombre, Fecha de modificación, Tamaño, Tipo. */
enum class SortField { Name, Modified, Size, Type }

/** Remembered per folder; folders always come first. */
@Serializable
data class FolderSort(val field: SortField = SortField.Name, val descending: Boolean = false) {
    fun apply(items: List<DriveItemResponse>, locale: Locale = Locale.getDefault()): List<DriveItemResponse> {
        val collator = Collator.getInstance(locale).apply { strength = Collator.SECONDARY }
        val byName = Comparator<DriveItemResponse> { a, b -> collator.compare(a.name, b.name) }
        val primary: Comparator<DriveItemResponse> = when (field) {
            SortField.Name -> byName
            SortField.Modified -> compareBy { FileDates.epochMs(it.updatedAt) }
            SortField.Size -> compareBy { it.asset?.sizeBytes ?: 0L }
            SortField.Type -> compareBy { FileKinds.typeKey(it) }
        }
        val ordered = if (descending) primary.reversed() else primary
        val (folders, files) = items.partition { it.folder != null }
        val folderOrder = if (field == SortField.Size || field == SortField.Type) byName else ordered
        return folders.sortedWith(folderOrder.thenBy { it.id }) + files.sortedWith(ordered.then(byName).thenBy { it.id })
    }
}
