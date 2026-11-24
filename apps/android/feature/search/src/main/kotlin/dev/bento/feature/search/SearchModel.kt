package dev.bento.feature.search

import dev.bento.api.generated.SearchItemResponse
import dev.bento.api.generated.SearchResultType
import dev.bento.feature.files.Destination
import dev.bento.feature.files.FileKinds
import java.text.Normalizer
import java.time.LocalDate
import java.time.YearMonth
import java.util.Locale

/** Type filter / suggestion chip (product/android.md §4.7): Fotos, Videos, PDF, Documentos, Hojas de cálculo, … */
enum class SearchKind(val type: SearchResultType?, val extensions: Set<String> = emptySet()) {
    Photos(SearchResultType.PHOTO),
    Videos(SearchResultType.VIDEO),
    Pdf(SearchResultType.DOCUMENT, setOf("pdf")),
    Documents(SearchResultType.DOCUMENT),
    Sheets(SearchResultType.DOCUMENT, setOf("xls", "xlsx", "ods", "csv", "tsv", "numbers")),
    Folders(SearchResultType.FOLDER),
    Albums(SearchResultType.ALBUM);

    /** The backend has no PDF/spreadsheet type: those are `document` hits narrowed by extension here. */
    fun accepts(item: SearchItemResponse): Boolean = extensions.isEmpty() || FileKinds.extension(item.title) in extensions
}

/** Date filter: a preset ("Este mes", "El año pasado", a detected year) or a custom range from the picker. */
sealed interface DateFilter {
    val from: LocalDate
    val to: LocalDate

    data class ThisMonth(val today: LocalDate) : DateFilter {
        override val from: LocalDate get() = today.withDayOfMonth(1)
        override val to: LocalDate get() = YearMonth.from(today).atEndOfMonth()
    }

    data class LastYear(val today: LocalDate) : DateFilter {
        override val from: LocalDate get() = LocalDate.of(today.year - 1, 1, 1)
        override val to: LocalDate get() = LocalDate.of(today.year - 1, 12, 31)
    }

    data class Year(val year: Int) : DateFilter {
        override val from: LocalDate get() = LocalDate.of(year, 1, 1)
        override val to: LocalDate get() = LocalDate.of(year, 12, 31)
    }

    data class Range(override val from: LocalDate, override val to: LocalDate) : DateFilter
}

data class SearchFilters(
    val kind: SearchKind? = null,
    val date: DateFilter? = null,
    /** Carpeta filter or the scope the search was opened from (`Buscar en esta carpeta`). */
    val folder: Destination? = null
) {
    val active: Boolean get() = kind != null || date != null || folder != null
}

/** Result groups in display order: Fotos as a strip, then rows. */
enum class ResultGroup { Photos, Folders, Files, Documents }

fun groupOf(item: SearchItemResponse): ResultGroup = when (item.type) {
    "photo", "video" -> ResultGroup.Photos

    "folder", "album" -> ResultGroup.Folders

    "document", "pdf_page" -> ResultGroup.Documents

    // OCR blocks of PDF pages say "Pagina N"; blocks of images say "OCR".
    "ocr_block" -> if (isPage(item)) ResultGroup.Documents else ResultGroup.Files

    else -> ResultGroup.Files
}

fun isPage(item: SearchItemResponse): Boolean =
    item.type == "pdf_page" || item.subtitle.orEmpty().let { MatchReasons.fold(it).startsWith("pagina") }

/** Page number of a PDF hit ("Pagina 3" → 3), if any. */
fun pageOf(item: SearchItemResponse): Int? = item.subtitle?.filter { it.isDigit() }?.toIntOrNull()?.takeIf { isPage(item) }

/** Why it matched, from the backend's explanation (`api/search-contract.md`). */
enum class MatchReason { ImageText, Name, Folder, DocumentType, Date, Album, DocumentText, Details, Recent, Meaning, Generic }

/**
 * The backend explains every hit in one Spanish sentence ("Coincidio por OCR y nombre de archivo"); the phone shows
 * localized, specific reasons. Until the API returns reason codes, the known labels are mapped here.
 */
object MatchReasons {
    private val labels = listOf(
        "ocr" to MatchReason.ImageText,
        "nombre de archivo" to MatchReason.Name,
        "nombre de carpeta" to MatchReason.Folder,
        "tipo de documento" to MatchReason.DocumentType,
        "fecha" to MatchReason.Date,
        "album" to MatchReason.Album,
        "texto indexado" to MatchReason.DocumentText,
        "metadata" to MatchReason.Details,
        "actividad reciente" to MatchReason.Recent,
        "busqueda semantica" to MatchReason.Meaning
    )

    fun parse(reason: String): List<MatchReason> {
        val text = fold(reason)
        val found = labels.filter { (label) -> label in text }.map { it.second }
        // Search by meaning is not offered on Android (product/android.md §4.7): never surfaced as a reason.
        return found.filterNot { it == MatchReason.Meaning }.ifEmpty { listOf(MatchReason.Generic) }
    }

    fun fold(value: String): String = Normalizer.normalize(value, Normalizer.Form.NFD).replace(Regex("\\p{M}"), "").lowercase(Locale.ROOT)
}

/** Character ranges of [text] that match any token of [query] (accent and case insensitive). */
fun highlights(text: String, query: String): List<IntRange> {
    val tokens = query.split(Regex("\\s+")).map { MatchReasons.fold(it) }.filter { it.length >= MIN_TOKEN }
    if (tokens.isEmpty()) return emptyList()
    // Folding keeps one char per char for Latin text (diacritics are separate code points after NFD and removed).
    val folded = text.map { MatchReasons.fold(it.toString()).firstOrNull() ?: it }.joinToString("")
    val ranges = tokens.flatMap { token ->
        generateSequence(folded.indexOf(token)) { previous -> folded.indexOf(token, previous + 1).takeIf { it >= 0 } }
            .takeWhile { it >= 0 }
            .map { it until it + token.length }
            .toList()
    }
    return ranges.sortedBy { it.first }.fold(mutableListOf()) { merged, range ->
        val last = merged.lastOrNull()
        if (last != null &&
            range.first <= last.last + 1
        ) {
            merged[merged.lastIndex] = last.first..maxOf(last.last, range.last)
        } else {
            merged += range
        }
        merged
    }
}

private const val MIN_TOKEN = 2

/** Years to suggest ("2024", "2023") from the timeline's month index, newest first. */
fun detectedYears(months: List<String>, today: LocalDate, max: Int = 3): List<Int> =
    months.mapNotNull { it.take(4).toIntOrNull() }.distinct().filter { it < today.year - 1 }.sortedDescending().take(max)
