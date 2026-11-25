package dev.bento.feature.search

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.DateRangePicker
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.rememberDateRangePickerState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.feature.files.SheetBody
import dev.bento.strings.R as StringsR
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset

/** Fecha: presets (Este mes, El año pasado, detected years) and a range picker. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DateSheetBody(state: SearchState, actions: SearchActions, showPicker: Boolean = true) {
    val current = state.filters.date
    val picker = rememberDateRangePickerState(
        initialSelectedStartDateMillis = current?.from?.toEpochMillis(),
        initialSelectedEndDateMillis = current?.to?.toEpochMillis()
    )
    SheetBody(stringResource(StringsR.string.search_filter_date_title)) {
        DateChips(state, actions)
        if (showPicker) {
            DateRangePicker(
                state = picker,
                modifier = Modifier.fillMaxWidth().heightIn(max = 460.dp).padding(top = 12.dp),
                title = null,
                headline = null,
                showModeToggle = false
            )
            BentoButton(
                stringResource(StringsR.string.search_date_apply),
                {
                    val start = picker.selectedStartDateMillis
                    val end = picker.selectedEndDateMillis ?: start
                    if (start != null && end != null) actions.onDate(DateFilter.Range(start.toLocalDate(), end.toLocalDate()))
                },
                Modifier.fillMaxWidth().padding(top = 12.dp),
                variant = BentoButtonVariant.Primary,
                enabled = picker.selectedStartDateMillis != null
            )
        }
    }
}

private fun LocalDate.toEpochMillis(): Long = atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()

private fun Long.toLocalDate(): LocalDate = Instant.ofEpochMilli(this).atZone(ZoneOffset.UTC).toLocalDate()
