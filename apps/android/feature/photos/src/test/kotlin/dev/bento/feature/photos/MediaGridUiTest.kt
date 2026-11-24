package dev.bento.feature.photos

import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToIndex
import androidx.compose.ui.test.performTouchInput
import androidx.test.core.app.ApplicationProvider
import dev.bento.designsystem.component.AvatarStatus
import dev.bento.designsystem.component.BentoSnackbarHostState
import dev.bento.designsystem.theme.BentoTheme
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

private fun customAction(label: String) = SemanticsMatcher("has custom action $label") { node ->
    node.config.getOrNull(SemanticsActions.CustomActions).orEmpty().any { it.label == label }
}

private fun androidx.compose.ui.test.SemanticsNodeInteraction.runCustomAction(label: String) {
    val action = fetchSemanticsNode().config[SemanticsActions.CustomActions].first { it.label == label }
    action.action()
}

/** Waits for [condition] while driving the Compose clock and the Robolectric main looper (coroutines on Main). */
fun androidx.compose.ui.test.junit4.ComposeContentTestRule.awaitCondition(timeoutMs: Long = 3_000, condition: () -> Boolean) {
    var waited = 0L
    while (!condition()) {
        check(waited < timeoutMs) { "condition not met in $timeoutMs ms" }
        mainClock.advanceTimeBy(50)
        org.robolectric.shadows.ShadowLooper.idleMainLooper()
        waited += 50
    }
}

private fun descriptionContains(text: String) = SemanticsMatcher("description contains $text") { node ->
    node.config.getOrNull(SemanticsProperties.ContentDescription).orEmpty().any { it.contains(text) }
}

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = "es-w411dp-h891dp-xxhdpi")
class MediaGridUiTest {
    @get:Rule
    val compose = createComposeRule()

    private val cells = ListMediaCells(cellsOf(MediaSamples.library))
    private val monthCells = ListMediaCells(cellsOf(MediaSamples.library, dayHeaders = false))
    private val opened = mutableListOf<Pair<String, Int>>()

    private fun grid(selection: SelectionState = SelectionState(), state: MediaGridState = MediaGridState()) {
        compose.setContent {
            BentoTheme(reducedMotion = true) {
                MediaGrid(
                    cellsFor = { if (it.dayHeaders) cells else monthCells },
                    state = state,
                    selection = selection,
                    layout = MediaSamples.layout,
                    callbacks = MediaGridCallbacks(onOpen = { cell, position -> opened += cell.asset.id to position })
                )
            }
        }
    }

    @Test
    fun `tap opens the viewer with the photo position`() {
        grid()
        compose.onNodeWithTag(MediaTestTags.tile("p4")).performClick()
        assertEquals(listOf("p4" to 3), opened)
    }

    @Test
    fun `long-press and drag range-selects across rows without opening anything`() {
        val selection = SelectionState()
        grid(selection)
        val start = compose.onNodeWithTag(MediaTestTags.tile("p1")).fetchSemanticsNode().boundsInRoot.center
        val end = compose.onNodeWithTag(MediaTestTags.tile("p6")).fetchSemanticsNode().boundsInRoot.center
        compose.onNodeWithTag(MediaTestTags.Grid).performTouchInput {
            down(start)
            advanceEventTime(viewConfiguration.longPressTimeoutMillis + 100)
            moveTo(end)
            moveTo(end)
            up()
        }
        compose.waitForIdle()
        assertEquals((1..6).map { "p$it" }.toSet(), selection.selected.keys)
        assertTrue("the long press never opens the viewer", opened.isEmpty())
        compose.onNodeWithTag(MediaTestTags.tile("p3")).assert(SemanticsMatcher.expectValue(SemanticsProperties.Selected, true))
    }

    @Test
    fun `TalkBack custom actions select without gestures, then taps toggle`() {
        val selection = SelectionState()
        grid(selection)
        val tile = compose.onNodeWithTag(MediaTestTags.tile("p2"))
        tile.assert(customAction("Abrir")).assert(customAction("Seleccionar"))
        compose.runOnIdle { tile.runCustomAction("Seleccionar") }
        compose.waitForIdle()
        assertEquals(setOf("p2"), selection.selected.keys)
        compose.onNodeWithTag(MediaTestTags.tile("p7")).performClick()
        assertEquals(setOf("p2", "p7"), selection.selected.keys)
        assertTrue(opened.isEmpty())
        compose.onNodeWithTag(MediaTestTags.tile("p2")).assert(customAction("Quitar selección"))
    }

    @Test
    fun `tiles read type, date, favorite and upload state`() {
        grid()
        compose.onNodeWithTag(
            MediaTestTags.tile("p2")
        ).assert(descriptionContains("Video, 0:42")).assert(descriptionContains("14 de marzo de 2024"))
        compose.onNodeWithTag(MediaTestTags.tile("p3")).assert(descriptionContains("pendiente de respaldo"))
        compose.onNodeWithTag(MediaTestTags.tile("p5")).assert(descriptionContains("no se pudo respaldar"))
        compose.onNodeWithTag(MediaTestTags.tile("p6")).assert(descriptionContains("Foto")).assert(descriptionContains("en favoritos"))
    }

    @Test
    fun `the month header sticks once its own header scrolls away`() {
        grid()
        compose.onNodeWithTag(MediaTestTags.StickyHeader).assertDoesNotExistCompat()
        val februaryPhoto = cellsOf(MediaSamples.library).indexOfFirst { it is GridCell.Media && it.month == "2024-02" } + 3
        compose.onNodeWithTag(MediaTestTags.Grid).performScrollToIndex(februaryPhoto)
        compose.waitForIdle()
        compose.onNodeWithTag(MediaTestTags.StickyHeader).assertIsDisplayed()
        compose.onNodeWithText("Febrero de 2024", useUnmergedTree = true).assertIsDisplayed()
    }

    @Test
    fun `density changes through accessibility actions (no pinch needed)`() {
        val state = MediaGridState()
        grid(state = state)
        val grid = compose.onNode(customAction("Ver más fotos por fila"))
        compose.runOnIdle { grid.runCustomAction("Ver más fotos por fila") }
        compose.waitForIdle()
        assertEquals(GridDensity.Dense, state.density)
        compose.runOnIdle { grid.runCustomAction("Ver fotos más grandes") }
        compose.runOnIdle { grid.runCustomAction("Ver fotos más grandes") }
        compose.waitForIdle()
        assertEquals(GridDensity.Large, state.density)
    }

    private fun androidx.compose.ui.test.SemanticsNodeInteraction.assertDoesNotExistCompat() = assertDoesNotExist()
}

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = "es-w411dp-h891dp-xxhdpi")
class PhotosContentTest {
    @get:Rule
    val compose = createComposeRule()

    private val navigation = PhotosNavigation({ _, _ -> }, {}, {}, {}, {}, {})

    @Composable
    private fun Screen(harness: MediaTestHarness, load: PhotosLoad = PhotosLoad.Live, card: PhotosCard? = null, selection: SelectionState) {
        val cells = remember { ListMediaCells(cellsOf(MediaSamples.library)) }
        CompositionLocalProvider(LocalBentoImageLoader provides fakeImageLoader(LocalContext.current)) {
            PhotosContent(
                load = load,
                cellsFor = { cells },
                layout = MediaSamples.layout,
                gridState = remember { MediaGridState() },
                card = card,
                account = AccountSummary("Ana", AvatarStatus.Idle),
                actions = harness.actions,
                snackbar = remember { BentoSnackbarHostState() },
                busy = false,
                navigation = navigation,
                onJump = {},
                onRetry = {},
                onUpload = {},
                onDismissBackupCard = {},
                selection = selection
            )
        }
    }

    private fun harness() = MediaTestHarness(
        ApplicationProvider.getApplicationContext(),
        CoroutineScope(SupervisorJob() + Dispatchers.Main)
    )

    @Test
    fun `delete offers Deshacer for 6 s and undo restores from the trash`() {
        val harness = harness()
        compose.setContent { BentoTheme(reducedMotion = true) { Screen(harness, selection = remember { SelectionState() }) } }
        val tile = compose.onNodeWithTag(MediaTestTags.tile("p4"))
        compose.runOnIdle { tile.runCustomAction("Eliminar") }
        compose.awaitCondition { harness.transport.count("DELETE /api/assets/p4") == 1 }
        compose.awaitCondition { compose.onAllNodesWithText("Se movió a la papelera").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("Deshacer").performClick()
        compose.awaitCondition { harness.transport.count("POST /api/trash/restore") == 1 }
        assertTrue(harness.transport.calls.last { it.path == "/api/trash/restore" }.body!!.contains("p4"))
    }

    @Test
    fun `selection swaps the top bar and shows the floating action bar`() {
        val selection = SelectionState()
        compose.setContent { BentoTheme(reducedMotion = true) { Screen(harness(), selection = selection) } }
        compose.runOnIdle { selection.set(MediaSamples.library.take(3), true) }
        compose.onNodeWithTag(MediaTestTags.SelectionBar).assertIsDisplayed()
        compose.onNodeWithText("3 seleccionados", useUnmergedTree = true).assertExists()
        compose.onNodeWithTag(dev.bento.designsystem.component.BentoTestTags.FloatingActionBar).assertIsDisplayed()
        compose.onNodeWithContentDescription("Seleccionar todo").assertIsDisplayed()
    }

    @Test
    fun `the top card and the empty state`() {
        compose.setContent {
            BentoTheme(reducedMotion = true) {
                Screen(harness(), load = PhotosLoad.Empty, card = PhotosCard.BackupOff, selection = remember { SelectionState() })
            }
        }
        compose.onNodeWithText("Respalda las fotos de este teléfono").assertIsDisplayed()
        compose.onNodeWithText("Tus fotos aparecerán aquí").assertIsDisplayed()
        compose.onNodeWithText("Subir fotos").assertIsDisplayed()
    }
}
