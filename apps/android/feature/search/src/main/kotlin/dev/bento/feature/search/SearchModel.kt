package dev.bento.feature.search

import dev.bento.api.generated.SearchItemResponse
import dev.bento.api.generated.SearchOrigin
import dev.bento.api.generated.SearchResultType
import dev.bento.feature.files.Destination
import dev.bento.feature.files.FileKinds
import java.text.Normalizer
import java.time.LocalDate
import java.time.YearMonth
import java.util.Locale
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull

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

/** Origen filter (product/android.md §4.7): how this phone got the file (`api/search-contract.md` `origin`). */
enum class OriginFilter(val wire: SearchOrigin) {
    ThisPhone(SearchOrigin.DEVICE),
    OtherDevices(SearchOrigin.PEER),
    Telegram(SearchOrigin.TELEGRAM)
}

data class SearchFilters(
    val kind: SearchKind? = null,
    val date: DateFilter? = null,
    /** Carpeta filter or the scope the search was opened from (`Buscar en esta carpeta`). */
    val folder: Destination? = null,
    val origin: OriginFilter? = null
) {
    val active: Boolean get() = kind != null || date != null || folder != null || origin != null
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

/** Why it matched (`api/search-contract.md` `match_reasons`), strongest first. */
enum class MatchReason {
    ImageText,
    Name,
    Folder,
    DocumentType,
    Date,
    CaptureDate,
    Album,
    DocumentText,
    Details,
    Recent,
    Meaning,
    Generic
}

/**
 * Reason codes of a hit, localized on the phone. The backend sends `match_reasons` codes; older answers only carry the
 * Spanish `reason` sentence ("Coincidio por OCR y nombre de archivo"), whose known labels are still mapped.
 */
object MatchReasons {
    private val codes = mapOf(
        "ocr_text" to MatchReason.ImageText,
        "filename" to MatchReason.Name,
        "folder_name" to MatchReason.Folder,
        "album" to MatchReason.Album,
        "semantic" to MatchReason.Meaning,
        "metadata" to MatchReason.Details,
        "document_type" to MatchReason.DocumentType,
        "exif_date" to MatchReason.CaptureDate,
        "date" to MatchReason.Date,
        "indexed_text" to MatchReason.DocumentText,
        "recent" to MatchReason.Recent
    )

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

    /** The hit's reasons: its codes when present (unknown codes are skipped), else the parsed sentence. */
    fun of(item: SearchItemResponse): List<MatchReason> {
        if (item.matchReasons.isEmpty()) return parse(item.reason)
        return visible(item.matchReasons.mapNotNull { codes[it] }.distinct())
    }

    fun parse(reason: String): List<MatchReason> {
        val text = fold(reason)
        return visible(labels.filter { (label) -> label in text }.map { it.second })
    }

    // Search by meaning is not offered on Android (product/android.md §4.7): never surfaced as a reason.
    private fun visible(found: List<MatchReason>): List<MatchReason> =
        found.filterNot { it == MatchReason.Meaning }.ifEmpty { listOf(MatchReason.Generic) }

    fun fold(value: String): String = Normalizer.normalize(value, Normalizer.Form.NFD).replace(Regex("\\p{M}"), "").lowercase(Locale.ROOT)
}

/** A snippet of matched text with its `[start, end)` highlight ranges (UTF-16 offsets, clamped to the text). */
data class Snippet(val text: String, val ranges: List<IntRange>, val source: String)

/**
 * The backend's snippet as [Snippet], or null when nothing textual matched. A snippet of the file name repeats the
 * row's title, so it is left out ([SearchItemResponse.title] carries the name).
 */
fun snippetOf(item: SearchItemResponse): Snippet? {
    val snippet = item.snippet ?: return null
    if (snippet.source == "filename" || snippet.text.isBlank()) return null
    val length = snippet.text.length
    val ranges = snippet.highlights.mapNotNull { pair ->
        val start = (pair.getOrNull(0) as? JsonPrimitive)?.intOrNull?.coerceIn(0, length) ?: return@mapNotNull null
        val end = (pair.getOrNull(1) as? JsonPrimitive)?.intOrNull?.coerceIn(0, length) ?: return@mapNotNull null
        if (end > start) start until end else null
    }.sortedBy { it.first }
    return Snippet(snippet.text, ranges, snippet.source)
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
