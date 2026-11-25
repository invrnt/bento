package dev.bento.feature.files

import java.text.Normalizer

/**
 * Names that come from other apps (share sheet, SAF, document trees) are untrusted. They are cleaned before they reach
 * the backend with the same rules as its upload sanitizer (`application/ingestion/metadata.py`): no path components,
 * no control or bidi-override characters, no leading/trailing dots or spaces, Windows reserved stems prefixed, at most
 * 255 characters (extension kept). The backend sanitizes again; this keeps logs, Activity rows and folder paths clean.
 */
object DisplayNames {
    const val MAX_LENGTH = 255
    private val control = Regex("[\\p{Cntrl}\\u200B-\\u200F\\u202A-\\u202E\\u2066-\\u2069\\uFEFF]")
    private val reserved = setOf("CON", "PRN", "AUX", "NUL") + (1..9).flatMap { listOf("COM$it", "LPT$it") }

    /** A file name: only the last path component survives. */
    fun file(raw: String?, fallback: String = "archivo"): String {
        val lastSegment = raw.orEmpty().replace('\\', '/').substringAfterLast('/')
        return clean(lastSegment, fallback)
    }

    /** One folder segment of a Drive path (a `/` inside a name never creates a level). */
    fun folder(raw: String?, fallback: String = "carpeta"): String = clean(raw.orEmpty().replace('/', '_').replace('\\', '_'), fallback)

    private fun clean(value: String, fallback: String): String {
        var name = Normalizer.normalize(value, Normalizer.Form.NFC).replace(control, "").trim().trim('.').trim()
        if (name.isEmpty() || name == "..") name = fallback
        if (name.substringBefore('.').uppercase() in reserved) name = "_$name"
        if (name.length > MAX_LENGTH) {
            val dot = name.lastIndexOf('.')
            val ext = if (dot > 0 && name.length - dot <= 16) name.substring(dot) else ""
            name = name.substring(0, MAX_LENGTH - ext.length) + ext
        }
        return name
    }

    /** "Escaneo 2026-11-24 10.41.pdf" (product/android.md §4.5). */
    fun scan(prefix: String, at: java.time.LocalDateTime): String =
        "%s %04d-%02d-%02d %02d.%02d.pdf".format(prefix, at.year, at.monthValue, at.dayOfMonth, at.hour, at.minute)

    /** A note named from its first line ("Lista de compras.txt"), for text/URLs shared alone (§4.9). */
    fun note(text: String, fallback: String): String {
        val firstLine = text.lineSequence().map { it.trim() }.firstOrNull { it.isNotEmpty() }.orEmpty()
        val stem = firstLine.replace(Regex("^https?://", RegexOption.IGNORE_CASE), "")
            .replace('/', ' ').replace('\\', ' ').take(NOTE_STEM).trim().removeSuffix(".txt").trim()
        return clean(if (clean(stem, "").isEmpty()) "$fallback.txt" else "$stem.txt", "$fallback.txt")
    }

    private const val NOTE_STEM = 60
}
