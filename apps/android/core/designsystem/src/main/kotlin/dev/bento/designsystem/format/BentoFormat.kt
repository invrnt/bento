package dev.bento.designsystem.format

import android.content.res.Resources
import android.icu.text.NumberFormat
import android.icu.util.ULocale
import androidx.annotation.PluralsRes
import androidx.compose.runtime.Composable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.pluralStringResource
import dev.bento.strings.R as StringsR
import java.util.Locale

/**
 * The one place counts and sizes become text (product/android.md §5, §8): CLDR digits and grouping for the
 * locale ("18.000" in es, "18,000" in en), and the shared `common_unit_*` strings for sizes. Notifications, workers
 * and every screen go through here so a number reads the same everywhere.
 */
public object BentoFormat {
    private const val STEP = 1000.0
    private const val WHOLE_FROM = 100

    private val units = listOf(
        StringsR.string.common_unit_bytes,
        StringsR.string.common_unit_kilobytes,
        StringsR.string.common_unit_megabytes,
        StringsR.string.common_unit_gigabytes,
        StringsR.string.common_unit_terabytes
    )

    /** A count with the locale's grouping: `18.000` (es), `18,000` (en). */
    public fun count(value: Number, locale: Locale): String = NumberFormat.getInstance(ULocale.forLocale(locale)).format(value)

    /** A count with the [resources]' locale, for code outside composition (notifications, workers). */
    public fun count(resources: Resources, value: Number): String = count(value, resources.configuration.locales[0])

    /** A quantity string whose `%1$s` is [count], grouped for the locale; extra args follow it. */
    public fun plural(resources: Resources, @PluralsRes id: Int, count: Int, vararg extra: Any): String =
        resources.getQuantityString(id, count, count(resources, count), *extra)

    /**
     * `1,5 MB` with SI steps (1 kB = 1000 B, as Android's own file sizes), one decimal below 100 and none from there.
     */
    public fun bytes(resources: Resources, bytes: Long, locale: Locale = resources.configuration.locales[0]): String {
        var value = bytes.coerceAtLeast(0).toDouble()
        var unit = 0
        while (value >= STEP && unit < units.lastIndex) {
            value /= STEP
            unit++
        }
        val number = NumberFormat.getInstance(ULocale.forLocale(locale)).apply {
            maximumFractionDigits = if (unit == 0 || value >= WHOLE_FROM) 0 else 1
            minimumFractionDigits = 0
        }.format(value)
        return resources.getString(units[unit], number)
    }
}

/** [BentoFormat.count] in the composition's locale. */
@Composable
@ReadOnlyComposable
public fun formatCount(value: Number): String = BentoFormat.count(value, LocalConfiguration.current.locales[0])

/** `pluralStringResource(id, count, formatCount(count), *extra)`: the count placeholder is always grouped. */
@Composable
public fun pluralCountResource(@PluralsRes id: Int, count: Int, vararg extra: Any): String =
    pluralStringResource(id, count, formatCount(count), *extra)
