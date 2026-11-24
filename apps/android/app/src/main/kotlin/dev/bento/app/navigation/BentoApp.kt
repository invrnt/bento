package dev.bento.app.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.unit.dp
import androidx.navigation3.runtime.entryProvider
import androidx.navigation3.ui.NavDisplay
import dev.bento.designsystem.component.BentoNavItem
import dev.bento.designsystem.component.BentoNavigationSuite
import dev.bento.designsystem.component.ErrorState
import dev.bento.designsystem.component.ProgressBar
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.engine.EngineState
import dev.bento.strings.R as StringsR

/**
 * App shell: design-system navigation suite (bar on compact, rail on medium/expanded) around a Navigation 3
 * display with predictive back. The top bar and avatar sheet come from features; this shell proves layout,
 * navigation and the engine status.
 */
@Composable
fun BentoApp(navigator: Navigator, engineState: EngineState, onExit: () -> Unit) {
    val showTabs = TopLevel.of(navigator.current) != null
    val content: @Composable () -> Unit = {
        val insets = if (showTabs) WindowInsets.statusBars else WindowInsets.safeDrawing
        Column(Modifier.fillMaxSize().background(BentoTheme.colors.tray).windowInsetsPadding(insets)) {
            EngineBanner(engineState)
            NavDisplay(
                backStack = navigator.backStack,
                onBack = { if (!navigator.back()) onExit() },
                entryProvider = entryProvider { bentoEntries(navigator) }
            )
        }
    }
    if (!showTabs) {
        content()
        return
    }
    val items = TopLevel.entries.map { tab -> BentoNavItem(tab.name, stringResource(tab.labelRes), tab.icon) }
    BentoNavigationSuite(
        items = items,
        selectedKey = navigator.currentTopLevel.name,
        onSelect = { key -> navigator.selectTab(TopLevel.valueOf(key)) },
        onReselect = { key -> navigator.selectTab(TopLevel.valueOf(key)) }
    ) { content() }
}

/** Engine status while it starts or after a failed start (the avatar ring replaces it, product/android.md §7). */
@Composable
private fun EngineBanner(state: EngineState) {
    when (state) {
        is EngineState.Ready, EngineState.Stopped -> Unit

        EngineState.Starting -> Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
            val label = stringResource(StringsR.string.shell_engine_starting)
            ProgressBar(progress = null, modifier = Modifier.fillMaxWidth(), label = label)
            Text(
                label,
                Modifier.padding(top = 8.dp).clearAndSetSemantics {},
                color = BentoTheme.colors.inkMuted,
                style = BentoTheme.typography.label
            )
        }

        is EngineState.Degraded -> ErrorState(
            body = stringResource(StringsR.string.shell_engine_problem),
            modifier = Modifier.padding(16.dp)
        )
    }
}
