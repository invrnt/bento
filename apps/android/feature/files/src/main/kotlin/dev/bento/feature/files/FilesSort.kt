package dev.bento.feature.files

import dev.bento.api.generated.DriveItemResponse
import dev.bento.api.generated.DriveSort
import dev.bento.api.generated.SortOrder
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
        // As the backend (`GET /drive/items?sort=`): folders by item count for size, by name for type.
        val folderOrder = when (field) {
            SortField.Size -> compareBy<DriveItemResponse> { it.itemCount ?: 0L }.let { if (descending) it.reversed() else it }.then(byName)
            SortField.Type -> byName
            else -> ordered
        }
        return folders.sortedWith(folderOrder.thenBy { it.id }) + files.sortedWith(ordered.then(byName).thenBy { it.id })
    }

    /** `sort` of `GET /api/drive/items`. */
    val wireSort: DriveSort
        get() = when (this.field) {
            SortField.Name -> DriveSort.NAME
            SortField.Modified -> DriveSort.MODIFIED
            SortField.Size -> DriveSort.SIZE
            SortField.Type -> DriveSort.KIND
        }

    /** `order` of `GET /api/drive/items`. */
    val wireOrder: SortOrder get() = if (descending) SortOrder.DESC else SortOrder.ASC
}
