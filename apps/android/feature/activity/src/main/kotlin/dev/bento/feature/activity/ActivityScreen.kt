package dev.bento.feature.activity

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.bento.designsystem.component.EmptyState
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.feature.settings.SettingsPage
import dev.bento.strings.R as StringsR

/**
 * Actividad as a full screen (`Route.Activity`: notification taps, a `CloudOff` tile, deep links). Same content as the
 * Cuenta y actividad sheet's status part, with room for every attention item.
 */
@Composable
fun ActivityScreen(
    onBack: () -> Unit,
    navigation: ActivityNavigation,
    modifier: Modifier = Modifier,
    viewModel: ActivityViewModel = hiltViewModel()
) {
    val overview by viewModel.overview.collectAsStateWithLifecycle()
    val busy by viewModel.busy.collectAsStateWithLifecycle()
    LaunchedEffect(viewModel) { viewModel.refresh() }
    ActivityContent(overview, actions(viewModel), navigation, onBack, modifier, busy)
}

@Composable
fun ActivityContent(
    overview: ActivityOverview,
    actions: ActivityActions,
    navigation: ActivityNavigation,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
    busy: Boolean = false
) {
    SettingsPage(stringResource(StringsR.string.activity_title), onBack, modifier) {
        Column(Modifier.fillMaxWidth().padding(top = 8.dp)) {
            ActivityDetails(overview, actions, navigation, busy)
        }
        if (overview.loaded && overview.attention.isEmpty() && overview.status == StatusLine.UpToDate) {
            EmptyState(
                title = stringResource(StringsR.string.activity_empty_title),
                body = stringResource(StringsR.string.activity_empty_body),
                icon = BentoIcons.CircleCheck,
                compact = true,
                modifier = Modifier.padding(16.dp)
            )
        }
    }
}
