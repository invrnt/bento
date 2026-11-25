package dev.bento.feature.recovery

import java.text.DateFormat
import java.time.Instant
import java.time.OffsetDateTime
import java.util.Date
import java.util.Locale

/** ISO timestamps from the API shown as calm, localized dates ("24 de noviembre de 2026"). */
object TrustDates {
    fun parse(iso: String?): Instant? = iso?.let { value ->
        runCatching { OffsetDateTime.parse(value).toInstant() }.getOrNull() ?: runCatching { Instant.parse(value) }.getOrNull()
    }

    fun long(iso: String?, locale: Locale = Locale.getDefault()): String? = parse(iso)?.let { long(it, locale) }

    fun long(instant: Instant, locale: Locale = Locale.getDefault()): String = DateFormat.getDateInstance(
        DateFormat.LONG,
        locale
    ).format(Date.from(instant))
}
