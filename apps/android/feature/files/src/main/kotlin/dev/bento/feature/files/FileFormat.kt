package dev.bento.feature.files

import android.content.res.Resources
import android.icu.text.NumberFormat
import dev.bento.api.generated.AssetResponse
import dev.bento.api.generated.DriveItemResponse
import dev.bento.designsystem.component.FileKind
import dev.bento.strings.R as StringsR
import java.text.DateFormat
import java.time.Instant
import java.time.OffsetDateTime
import java.util.Date
import java.util.Locale

/** How Archivos, Buscar and the share sheet open and label a file (product/android.md §4.5). */
enum class OpenKind { Folder, Image, Video, Pdf, Text, Audio, Other }

object FileKinds {
    private val textExtensions = setOf(
        "txt", "md", "markdown", "csv", "tsv", "json", "xml", "yaml", "yml", "toml", "ini", "log", "kt", "kts", "java", "py",
        "js", "ts", "tsx", "jsx", "html", "css", "sh", "c", "h", "cpp", "rs", "go", "rb", "swift", "sql", "gradle", "properties"
    )
    private val sheetExtensions = setOf("xls", "xlsx", "ods", "numbers", "csv", "tsv")
    private val slideExtensions = setOf("ppt", "pptx", "odp", "key")
    private val docExtensions = setOf("doc", "docx", "odt", "rtf", "pages")
    private val archiveExtensions = setOf("zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz")

    fun extension(name: String): String = name.substringAfterLast('.', "").lowercase(Locale.ROOT)

    fun openKind(mime: String?, name: String): OpenKind {
        val type = mime.orEmpty().lowercase(Locale.ROOT)
        val ext = extension(name)
        return when {
            type.startsWith("image/") -> OpenKind.Image
            type.startsWith("video/") -> OpenKind.Video
            type == "application/pdf" || ext == "pdf" -> OpenKind.Pdf
            type.startsWith("audio/") -> OpenKind.Audio
            type.startsWith("text/") || ext in textExtensions || type == "application/json" || type == "application/xml" -> OpenKind.Text
            else -> OpenKind.Other
        }
    }

    fun openKind(asset: AssetResponse): OpenKind = openKind(asset.mimeType, asset.filename)

    /** Tile color/icon (design-system `kind-*`). */
    fun fileKind(mime: String?, name: String): FileKind {
        val ext = extension(name)
        return when (openKind(mime, name)) {
            OpenKind.Folder -> FileKind.Folder

            OpenKind.Image -> FileKind.Image

            OpenKind.Video -> FileKind.Video

            OpenKind.Pdf -> FileKind.Pdf

            OpenKind.Audio -> FileKind.Audio

            OpenKind.Text, OpenKind.Other -> when (ext) {
                in sheetExtensions -> FileKind.Sheet
                in slideExtensions -> FileKind.Slides
                in docExtensions -> FileKind.Doc
                in archiveExtensions -> FileKind.Archive
                else -> FileKind.Text
            }
        }
    }

    fun fileKind(item: DriveItemResponse): FileKind = item.asset?.let { fileKind(it.mimeType, it.filename) } ?: FileKind.Folder

    /** Sort key for "Tipo": folders, then by kind and extension. */
    fun typeKey(item: DriveItemResponse): String = if (item.folder != null) "" else "${fileKind(item).ordinal}:${extension(item.name)}"
}

/** Sizes with android.icu digits and the shared unit strings ("1,5 MB"). */
object Sizes {
    private const val STEP = 1024.0

    fun format(resources: Resources, bytes: Long, locale: Locale = Locale.getDefault()): String {
        val units = listOf(
            StringsR.string.common_unit_bytes,
            StringsR.string.common_unit_kilobytes,
            StringsR.string.common_unit_megabytes,
            StringsR.string.common_unit_gigabytes,
            StringsR.string.common_unit_terabytes
        )
        var value = bytes.coerceAtLeast(0).toDouble()
        var unit = 0
        while (value >= STEP && unit < units.lastIndex) {
            value /= STEP
            unit++
        }
        val number = NumberFormat.getInstance(locale).apply {
            maximumFractionDigits = if (unit == 0 || value >= 100) 0 else 1
            minimumFractionDigits = 0
        }.format(value)
        return resources.getString(units[unit], number)
    }
}

/** API timestamps as calm, localized dates. */
object FileDates {
    fun parse(iso: String?): Instant? = iso?.let { value ->
        runCatching { OffsetDateTime.parse(value).toInstant() }.getOrNull() ?: runCatching { Instant.parse(value) }.getOrNull()
    }

    fun medium(iso: String?, locale: Locale = Locale.getDefault()): String? =
        parse(iso)?.let { DateFormat.getDateInstance(DateFormat.MEDIUM, locale).format(Date.from(it)) }

    fun epochMs(iso: String?): Long = parse(iso)?.toEpochMilli() ?: 0L
}
