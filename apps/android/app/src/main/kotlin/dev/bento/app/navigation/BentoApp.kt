package dev.bento.app.navigation

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.adaptive.navigationsuite.NavigationSuiteScaffold
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.navigation3.runtime.entryProvider
import androidx.navigation3.ui.NavDisplay
import dev.bento.app.R
import dev.bento.engine.EngineState

/**
 * App shell: adaptive navigation suite (bar on compact, rail on medium/expanded) around a Navigation 3
 * display with predictive back. The top bar, avatar sheet and real tab icons come from features and the
 * design system; this shell only proves layout and navigation.
 */
@Composable
fun BentoApp(navigator: Navigator, engineState: EngineState, onExit: () -> Unit) {
    val showTabs = TopLevel.of(navigator.current) != null
    val content: @Composable () -> Unit = {
        Column(Modifier.fillMaxSize()) {
            EngineBanner(engineState)
            NavDisplay(
                backStack = navigator.backStack,
                onBack = { if (!navigator.back()) onExit() },
                entryProvider = entryProvider { bentoEntries(navigator) },
            )
        }
    }
    if (!showTabs) {
        content()
        return
    }
    NavigationSuiteScaffold(
        navigationSuiteItems = {
            TopLevel.entries.forEach { tab ->
                item(
                    selected = navigator.currentTopLevel == tab,
                    onClick = { navigator.selectTab(tab) },
                    icon = { Text(tab.glyph) },
                    label = { Text(stringResource(tab.labelRes)) },
                )
            }
        },
    ) { content() }
}

/** TEMPORARY engine status line (the avatar ring replaces it, product/android.md §7). */
@Composable
private fun EngineBanner(state: EngineState) {
    when (state) {
        is EngineState.Ready, EngineState.Stopped -> Unit
        EngineState.Starting -> Column(Modifier.fillMaxWidth().semantics { liveRegion = LiveRegionMode.Polite }) {
            LinearProgressIndicator(Modifier.fillMaxWidth())
            Text(stringResource(R.string.engine_starting), Modifier.padding(16.dp), style = MaterialTheme.typography.bodyMedium)
        }
        is EngineState.Degraded -> Text(
            stringResource(R.string.engine_problem),
            Modifier.fillMaxWidth().padding(16.dp).semantics { liveRegion = LiveRegionMode.Polite },
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}
