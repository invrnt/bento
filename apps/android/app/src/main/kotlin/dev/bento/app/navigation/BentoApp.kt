package dev.bento.app.navigation

import androidx.compose.animation.ExperimentalSharedTransitionApi
import androidx.compose.animation.SharedTransitionLayout
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
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
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.movableContentOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.navigation3.rememberViewModelStoreNavEntryDecorator
import androidx.navigation3.runtime.EntryProviderScope
import androidx.navigation3.runtime.NavEntryDecorator
import androidx.navigation3.runtime.entryProvider
import androidx.navigation3.runtime.rememberSaveableStateHolderNavEntryDecorator
import androidx.navigation3.ui.NavDisplay
import dev.bento.designsystem.component.BentoNavItem
import dev.bento.designsystem.component.BentoNavigationSuite
import dev.bento.designsystem.component.ErrorState
import dev.bento.designsystem.component.LocalBentoSharedTransitionScope
import dev.bento.designsystem.component.ProgressBar
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.engine.DegradedReason
import dev.bento.engine.EngineState
import dev.bento.strings.R as StringsR

/**
 * App shell: design-system navigation suite (bar on compact, rail on medium/expanded) around a Navigation 3
 * display with predictive back. The top bar and avatar sheet come from features.
 *
 * Window insets are applied per entry (metadata [EntryInsets]): tab roots pad the status bar, full-bleed entries
 * (the viewer) pad nothing, everything else pads safe drawing. Because each entry keeps its own padding, the screen
 * underneath does not move while a full-bleed entry animates in. The [SharedTransitionLayout] hosts the tile → viewer
 * shared element; each entry gets its own ViewModelStore.
 */
@OptIn(ExperimentalSharedTransitionApi::class)
@Composable
fun BentoApp(
    navigator: Navigator,
    engineState: EngineState,
    onExit: () -> Unit,
    onResetDevice: () -> Unit = {},
    resetFailed: Boolean = false,
    entries: EntryProviderScope<Route>.() -> Unit = { bentoEntries(navigator) }
) {
    if ((engineState as? EngineState.Degraded)?.reason == DegradedReason.KEY_LOST) {
        KeyLostScreen(onReset = onResetDevice, failed = resetFailed)
        return
    }
    val showTabs = TopLevel.of(navigator.current) != null
    val engine = rememberUpdatedState(engineState)
    val exit = rememberUpdatedState(onExit)
    val currentEntries = rememberUpdatedState(entries)
    // Movable so the NavDisplay (and every entry's saved state and ViewModels) survives moving between the tab
    // scaffold and full-screen routes, and between the bar and the rail.
    val content = remember(navigator) {
        movableContentOf {
            SharedTransitionLayout(Modifier.fillMaxSize().background(BentoTheme.colors.tray)) {
                CompositionLocalProvider(LocalBentoSharedTransitionScope provides this) {
                    NavDisplay(
                        backStack = navigator.backStack,
                        onBack = { if (!navigator.back()) exit.value() },
                        entryDecorators = listOf(
                            rememberSaveableStateHolderNavEntryDecorator(),
                            rememberViewModelStoreNavEntryDecorator(),
                            remember { insetsDecorator { engine.value } }
                        ),
                        sharedTransitionScope = this,
                        entryProvider = entryProvider { currentEntries.value(this) }
                    )
                }
            }
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

/** Pads each entry by its [EntryInsets] metadata and shows the engine banner on padded entries. */
private fun insetsDecorator(engineState: () -> EngineState) = NavEntryDecorator<Route> { entry ->
    when (entry.metadata[EntryInsets.KEY]) {
        EntryInsets.FULL_BLEED -> entry.Content()

        else -> {
            val insets = if (entry.metadata[EntryInsets.KEY] == EntryInsets.TABS) WindowInsets.statusBars else WindowInsets.safeDrawing
            Column(Modifier.fillMaxSize().background(BentoTheme.colors.tray).windowInsetsPadding(insets)) {
                EngineBanner(engineState())
                Box(Modifier.weight(1f).fillMaxWidth()) { entry.Content() }
            }
        }
    }
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
