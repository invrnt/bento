package dev.bento.feature.photos

import android.content.Context
import android.icu.text.DateFormat
import android.icu.text.DisplayContext
import android.icu.text.NumberFormat
import android.icu.util.TimeZone
import android.icu.util.ULocale
import dev.bento.api.generated.AssetResponse
import dev.bento.strings.R as StringsR
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneOffset
import java.util.Date
import java.util.Locale

/**
 * Dates, durations and sizes for media, through android.icu (product/android.md §13a). Timeline days and months are
 * the backend's UTC calendar days, so they are formatted in UTC to match the grouping exactly.
 */
object MediaFormat {
    private fun utcDate(date: LocalDate): Date = Date.from(date.atStartOfDay().toInstant(ZoneOffset.UTC))

    private fun format(skeleton: String, locale: Locale, date: Date, utc: Boolean = true): String {
        val formatter = DateFormat.getInstanceForSkeleton(skeleton, ULocale.forLocale(locale))
        if (utc) formatter.timeZone = TimeZone.GMT_ZONE
        formatter.setContext(DisplayContext.CAPITALIZATION_FOR_BEGINNING_OF_SENTENCE)
        return formatter.format(date)
    }

    /** `0:42`, `12:05`, `1:02:03` (tabular in the UI). */
    fun duration(ms: Long): String {
        val total = (ms / 1000).coerceAtLeast(0)
        val h = total / 3600
        val m = (total % 3600) / 60
        val s = total % 60
        return if (h > 0) "%d:%02d:%02d".format(Locale.ROOT, h, m, s) else "%d:%02d".format(Locale.ROOT, m, s)
    }

    /** Month header: "Marzo de 2024" / "March 2024". [month] is `YYYY-MM`. */
    fun monthTitle(month: String, locale: Locale): String = monthDate(month)?.let { format("MMMMy", locale, utcDate(it)) } ?: month

    /** Fast-scroller bubble: "mar 2024". */
    fun monthShort(month: String, locale: Locale): String = monthDate(month)?.let { format("MMMy", locale, utcDate(it)) } ?: month

    /** Day sub-header: "Mar, 12 de mar" (with the year when it is not [today]'s). */
    fun dayTitle(date: String, locale: Locale, today: LocalDate = LocalDate.now(ZoneOffset.UTC)): String {
        val day = parseDay(date) ?: return date
        return format(if (day.year == today.year) "EEEMMMd" else "EEEMMMdy", locale, utcDate(day))
    }

    /** Long date for TalkBack and the info sheet: "12 de marzo de 2024". */
    fun longDate(date: String, locale: Locale): String = parseDay(date)?.let { format("yMMMMd", locale, utcDate(it)) } ?: date

    /** Date and time in the phone's zone for the info sheet: "martes, 12 de marzo de 2024, 18:04". */
    fun dateTime(iso: String, locale: Locale): String {
        val instant = runCatching { OffsetDateTime.parse(iso).toInstant() }.getOrNull()
            ?: runCatching { java.time.LocalDateTime.parse(iso).toInstant(ZoneOffset.UTC) }.getOrNull()
            ?: return iso
        return format("yMMMMEEEEdjm", locale, Date.from(instant), utc = false)
    }

    /** `1,5 MB` with the shared unit strings. */
    fun bytes(context: Context, bytes: Long, locale: Locale = context.resources.configuration.locales[0]): String {
        val units = listOf(
            StringsR.string.common_unit_bytes,
            StringsR.string.common_unit_kilobytes,
            StringsR.string.common_unit_megabytes,
            StringsR.string.common_unit_gigabytes,
            StringsR.string.common_unit_terabytes
        )
        var value = bytes.toDouble().coerceAtLeast(0.0)
        var unit = 0
        while (value >= 1000 && unit < units.lastIndex) {
            value /= 1000
            unit++
        }
        val number = NumberFormat.getInstance(ULocale.forLocale(locale)).apply {
            maximumFractionDigits =
                if (unit == 0 || value >= 100) 0 else 1
        }
        return context.getString(units[unit], number.format(value))
    }

    fun number(value: Number, locale: Locale): String = NumberFormat.getInstance(ULocale.forLocale(locale)).format(value)

    /** The calendar day a timeline item belongs to (`taken_at`, else `created_at`), `YYYY-MM-DD`. */
    fun dayOf(asset: AssetResponse): String = (asset.takenAt ?: asset.createdAt).take(10)

    fun isVideo(asset: AssetResponse): Boolean = asset.kind == "video" || asset.mimeType.startsWith("video/")

    private fun monthDate(month: String): LocalDate? = runCatching { LocalDate.parse("$month-01") }.getOrNull()

    private fun parseDay(date: String): LocalDate? = runCatching { LocalDate.parse(date.take(10)) }.getOrNull()
}
