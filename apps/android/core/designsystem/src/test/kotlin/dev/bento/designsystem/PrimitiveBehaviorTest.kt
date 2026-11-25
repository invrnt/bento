package dev.bento.designsystem

import androidx.activity.ComponentActivity
import androidx.compose.animation.graphics.ExperimentalAnimationGraphicsApi
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.requiredWidth
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.input.TextFieldState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.painter.ColorPainter
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertHeightIsAtLeast
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.assertWidthIsAtLeast
import androidx.compose.ui.test.click
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.longClick
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.espresso.Espresso
import androidx.test.ext.junit.runners.AndroidJUnit4
import dev.bento.designsystem.component.AvatarStatus
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonSize
import dev.bento.designsystem.component.BentoDialog
import dev.bento.designsystem.component.BentoFilterChip
import dev.bento.designsystem.component.BentoIconButton
import dev.bento.designsystem.component.BentoNavItem
import dev.bento.designsystem.component.BentoNavigationSuite
import dev.bento.designsystem.component.BentoSheet
import dev.bento.designsystem.component.BentoSnackbarHost
import dev.bento.designsystem.component.BentoSnackbarHostState
import dev.bento.designsystem.component.BentoTestTags
import dev.bento.designsystem.component.BentoTextField
import dev.bento.designsystem.component.CodeField
import dev.bento.designsystem.component.CrockfordCode
import dev.bento.designsystem.component.FloatingAction
import dev.bento.designsystem.component.FloatingActionBar
import dev.bento.designsystem.component.SasEmojiRow
import dev.bento.designsystem.component.SegmentOption
import dev.bento.designsystem.component.SegmentedButtons
import dev.bento.designsystem.component.StatusAvatar
import dev.bento.designsystem.component.Thumbnail
import dev.bento.designsystem.component.bentoLoaderAnimatedVector
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.generated.BentoNavIcons
import dev.bento.designsystem.theme.BentoHaptic
import dev.bento.designsystem.theme.BentoHaptics
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.designsystem.theme.LocalBentoHaptics
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config

@RunWith(AndroidJUnit4::class)
@Config(qualifiers = "es-w411dp-h900dp")
class PrimitiveBehaviorTest {
    @get:Rule
    val compose = createAndroidComposeRule<ComponentActivity>()

    private val haptics = mutableListOf<BentoHaptic>()

    private fun setBento(content: @androidx.compose.runtime.Composable () -> Unit) {
        compose.setContent {
            CompositionLocalProvider(LocalBentoHaptics provides BentoHaptics { haptics += it }) {
                BentoTheme(darkTheme = false) { content() }
            }
        }
    }

    /** Writes test state on the UI thread and publishes it before the next frame. */
    private fun update(block: () -> Unit) {
        compose.runOnUiThread {
            block()
            Snapshot.sendApplyNotifications()
        }
    }

    // ---- CodeField -------------------------------------------------------------------------------------------

    @Test
    fun codeFieldGroupsWithDashesAndKeepsNormalizedState() {
        val state = TextFieldState()
        setBento { CodeField(state, "Código de vinculación") }
        compose.onNodeWithContentDescription("Código de vinculación").performTextInput("7kq2m9x")
        compose.runOnIdle { assertEquals("7KQ2M9X", state.text.toString()) }
        compose.onNodeWithContentDescription("Código de vinculación").assert(hasText("7KQ2-M9X"))
        compose.onNodeWithContentDescription("Código de vinculación")
            .assert(SemanticsMatcher.expectValue(SemanticsProperties.StateDescription, "7 de 12 caracteres"))
    }

    @Test
    fun codeFieldAcceptsPastedCodesAndLinksAndCompletesOnce() {
        val state = TextFieldState()
        val completed = mutableListOf<String>()
        setBento { CodeField(state, "Código", onComplete = { completed += it }) }
        val node = compose.onNodeWithContentDescription("Código")
        node.performTextReplacement("https://bento.example/join#v=1&c=7kq2-m9xw-d4ph")
        compose.runOnIdle { assertEquals("7KQ2M9XWD4PH", state.text.toString()) }
        node.assert(hasText("7KQ2-M9XW-D4PH"))
        node.performTextReplacement("bento://join?v=1&c=ABCD-EFGH-JKMN")
        compose.runOnIdle { assertEquals(listOf("7KQ2M9XWD4PH", "ABCDEFGHJKMN"), completed) }
        node.assert(SemanticsMatcher.expectValue(SemanticsProperties.StateDescription, "Código completo"))
    }

    @Test
    fun codeFieldNormalizesCrockfordAndCapsLength() {
        val state = TextFieldState()
        setBento { CodeField(state, "Código") }
        val node = compose.onNodeWithContentDescription("Código")
        node.performTextInput("iLoU-o")
        compose.runOnIdle { assertEquals("1100", state.text.toString()) }
        node.performTextReplacement("0123456789ABCDEFGHJK")
        compose.runOnIdle { assertEquals(CrockfordCode.PAIRING_LENGTH, state.text.length) }
    }

    @Test
    fun codeFieldErrorIsAnnouncedAndPlaysReject() {
        var error by mutableStateOf<String?>(null)
        setBento { CodeField(TextFieldState("7KQ2M9XWD4PA"), "Código", error = error) }
        compose.runOnIdle { assertTrue(haptics.isEmpty()) }
        error = "El código no coincide."
        compose.onNodeWithContentDescription("Código")
            .assert(SemanticsMatcher.expectValue(SemanticsProperties.Error, "El código no coincide."))
        compose.runOnIdle { assertEquals(listOf(BentoHaptic.Reject), haptics) }
    }

    @Test
    fun fieldErrorIsAnAssertiveLiveRegionSoAutoSubmittedCodesAnnounceIt() {
        var error by mutableStateOf<String?>(null)
        setBento { CodeField(TextFieldState("7KQ2M9XWD4PA"), "Código", hint = "Lo ves en tu computador", error = error) }
        val message = compose.onNodeWithTag(BentoTestTags.FieldMessage)
        message.assert(SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Assertive))
        message.assert(SemanticsMatcher.keyNotDefined(SemanticsProperties.ContentDescription))
        update { error = "El código no coincide." }
        message.assert(SemanticsMatcher.expectValue(SemanticsProperties.ContentDescription, listOf("El código no coincide.")))
        message.assert(SemanticsMatcher.expectValue(SemanticsProperties.LiveRegion, LiveRegionMode.Assertive))
    }

    // ---- SAS, avatar -----------------------------------------------------------------------------------------

    @Test
    fun sasEmojiRowIsOneSentenceForTalkBack() {
        setBento { SasEmojiRow(listOf("🐶", "🔑", "🌵", "🎈")) }
        compose.onNodeWithContentDescription("Emojis de verificación: 🐶 🔑 🌵 🎈")
            .assert(SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Image))
        compose.onAllNodesWithText("🐶").assertCountEquals(0)
    }

    @Test
    fun statusAvatarReadsNameAndEveryState() {
        var status by mutableStateOf(AvatarStatus.Idle)
        var progress by mutableStateOf<Float?>(null)
        var clicks = 0
        setBento { StatusAvatar("Ana", status, onClick = { clicks++ }, progress = progress) }
        val expected = mapOf(
            AvatarStatus.Idle to "Todo al día",
            AvatarStatus.Syncing to "Sincronizando",
            AvatarStatus.Attention to "Algo necesita tu atención",
            AvatarStatus.Offline to "Sin conexión",
            AvatarStatus.Paused to "Respaldo en pausa"
        )
        for ((s, text) in expected) {
            status = s
            compose.onNodeWithContentDescription("Cuenta y actividad de Ana. $text").assertExists()
        }
        status = AvatarStatus.Syncing
        progress = 0.42f
        compose.onNodeWithContentDescription("Sincronizando, 42", substring = true)
            .assert(SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Button))
            .performClick()
        compose.runOnIdle { assertEquals(1, clicks) }
    }

    // ---- Thumbnail ---------------------------------------------------------------------------------------------

    @Test
    fun thumbnailShowsPlaceholderThenFadesTheImageIn() {
        var painter by mutableStateOf<Painter?>(null)
        compose.mainClock.autoAdvance = false
        setBento { Thumbnail(painter, "Foto", Modifier.width(96.dp)) }
        compose.mainClock.advanceTimeByFrame()
        compose.onNodeWithTag(BentoTestTags.ThumbnailPlaceholder, useUnmergedTree = true).assertExists()
        compose.onNodeWithTag(BentoTestTags.ThumbnailImage, useUnmergedTree = true).assertDoesNotExist()

        update { painter = ColorPainter(Color.Gray) }
        compose.mainClock.advanceTimeByFrame()
        compose.mainClock.advanceTimeBy(64)
        // Mid-fade: the image is drawn over the placeholder.
        compose.onNodeWithTag(BentoTestTags.ThumbnailImage, useUnmergedTree = true).assertExists()
        compose.onNodeWithTag(BentoTestTags.ThumbnailPlaceholder, useUnmergedTree = true).assertExists()

        compose.mainClock.advanceTimeBy(400)
        compose.onNodeWithTag(BentoTestTags.ThumbnailPlaceholder, useUnmergedTree = true).assertDoesNotExist()
    }

    @Test
    fun cachedThumbnailAppearsWithoutFade() {
        compose.mainClock.autoAdvance = false
        setBento { Thumbnail(ColorPainter(Color.Gray), "Foto", Modifier.width(96.dp)) }
        compose.mainClock.advanceTimeByFrame()
        compose.onNodeWithTag(BentoTestTags.ThumbnailImage, useUnmergedTree = true).assertExists()
        compose.onNodeWithTag(BentoTestTags.ThumbnailPlaceholder, useUnmergedTree = true).assertDoesNotExist()
    }

    // ---- Floating action bar -----------------------------------------------------------------------------------

    @Test
    fun floatingActionBarSlidesInRunsActionsAndCloses() {
        var visible by mutableStateOf(false)
        val events = mutableListOf<String>()
        setBento {
            FloatingActionBar(
                visible = visible,
                actions = listOf(
                    FloatingAction(BentoIcons.Share2, "Compartir", { events += "share" }),
                    FloatingAction(BentoIcons.Trash2, "Eliminar", { events += "delete" }, destructive = true)
                ),
                overflow = listOf(FloatingAction(BentoIcons.Send, "Enviar por Telegram…", { events += "telegram" })),
                onClose = { events += "close" },
                title = "2 seleccionados"
            )
        }
        compose.onNodeWithTag(BentoTestTags.FloatingActionBar).assertDoesNotExist()
        visible = true
        compose.onNodeWithTag(BentoTestTags.FloatingActionBar).assertExists()
        compose.onNodeWithContentDescription("Eliminar").assertHeightIsAtLeast(48.dp).performClick()
        compose.onNodeWithContentDescription("Más opciones").performClick()
        compose.onNodeWithText("Enviar por Telegram…").performClick()
        compose.onNodeWithContentDescription("Cancelar selección").performClick()
        compose.runOnIdle { assertEquals(listOf("delete", "telegram", "close"), events) }
        visible = false
        compose.onNodeWithTag(BentoTestTags.FloatingActionBar).assertDoesNotExist()
    }

    @Test
    fun floatingActionBarShowsOnlyTheCountWhenTheTitleDoesNotFit() {
        var scale by mutableStateOf(1f)
        var actions by mutableStateOf(1)
        setBento {
            CompositionLocalProvider(LocalDensity provides Density(LocalDensity.current.density, scale)) {
                Box(Modifier.width(411.dp)) {
                    FloatingActionBar(
                        visible = true,
                        actions = List(actions) { FloatingAction(BentoIcons.Share2, "Acción $it", {}) },
                        overflow = listOf(FloatingAction(BentoIcons.Send, "Enviar", {})),
                        onClose = {},
                        title = "2 seleccionados",
                        compactTitle = "2"
                    )
                }
            }
        }
        compose.onNodeWithText("2 seleccionados").assertExists()
        update {
            scale = 2f
            actions = 4
        }
        compose.onNodeWithText("2").assert(SemanticsMatcher.expectValue(SemanticsProperties.ContentDescription, listOf("2 seleccionados")))
        compose.onAllNodesWithText("2 seleccionados").assertCountEquals(0)
    }

    // ---- Snackbar ------------------------------------------------------------------------------------------------

    @Test
    fun undoSnackbarStaysSixSecondsThenDismisses() {
        val host = BentoSnackbarHostState()
        lateinit var scope: CoroutineScope
        var undone: Boolean? = null
        compose.mainClock.autoAdvance = false
        setBento {
            scope = rememberCoroutineScope()
            BentoSnackbarHost(host)
        }
        compose.runOnIdle { scope.launch { undone = host.showUndo("Se movió a la Papelera", "Deshacer") } }
        compose.mainClock.advanceTimeBy(5_800)
        compose.onNodeWithText("Se movió a la Papelera").assertExists()
        compose.onNodeWithText("Deshacer").assertExists()
        compose.mainClock.advanceTimeBy(800)
        compose.onNodeWithText("Se movió a la Papelera").assertDoesNotExist()
        compose.runOnIdle { assertEquals(false, undone) }
    }

    @Test
    fun undoActionResolvesTheSnackbar() {
        val host = BentoSnackbarHostState()
        lateinit var scope: CoroutineScope
        var undone: Boolean? = null
        setBento {
            scope = rememberCoroutineScope()
            BentoSnackbarHost(host)
        }
        compose.runOnIdle { scope.launch { undone = host.showUndo("Se movió a la Papelera", "Deshacer") } }
        compose.onNodeWithText("Deshacer").performClick()
        compose.runOnIdle { assertEquals(true, undone) }
        compose.onNodeWithText("Se movió a la Papelera").assertDoesNotExist()
        assertEquals(6_000L, BentoSnackbarHostState.UNDO_DURATION_MS)
    }

    // ---- Targets, buttons, selection --------------------------------------------------------------------------

    @Test
    fun denseControlsAcceptTouchesAcrossFortyEightDp() {
        // 40 dp visuals (36 dp for chips) must still take a tap 3 dp outside their drawn edge.
        val clicks = mutableListOf<String>()
        setBento {
            androidx.compose.foundation.layout.Column(
                verticalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(24.dp)
            ) {
                BentoButton("Guardar", { clicks += "button" }, size = BentoButtonSize.Small)
                BentoIconButton(BentoIcons.EllipsisVertical, "Más opciones", { clicks += "icon" }, dense = true)
                BentoFilterChip("Fotos", selected = false, onSelectedChange = { clicks += "chip" })
            }
        }
        for (node in listOf(
            compose.onNodeWithText("Guardar"),
            compose.onNodeWithContentDescription("Más opciones"),
            compose.onNodeWithText("Fotos")
        )) {
            node.performTouchInput { click(androidx.compose.ui.geometry.Offset(centerX, -3.dp.toPx())) }
        }
        compose.runOnIdle { assertEquals(listOf("button", "icon", "chip"), clicks) }
    }

    @Test
    fun loadingButtonIsBusyAndNotClickable() {
        var clicks = 0
        setBento { BentoButton("Subir archivos", { clicks++ }, loading = true) }
        compose.onNodeWithText("Subir archivos")
            .assertIsNotEnabled()
            .assert(SemanticsMatcher.expectValue(SemanticsProperties.StateDescription, "Cargando…"))
            .performClick()
        compose.runOnIdle { assertEquals(0, clicks) }
    }

    @Test
    fun segmentedButtonsAreARadioGroupWithTickHaptic() {
        var selected by mutableStateOf("grid")
        setBento {
            SegmentedButtons(
                listOf(SegmentOption("grid", "Cuadrícula"), SegmentOption("list", "Lista")),
                selected = selected,
                onSelect = { selected = it },
                tickHaptic = true
            )
        }
        compose.onNodeWithText("Cuadrícula").assertIsSelected()
            .assert(SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.RadioButton))
        compose.onNodeWithText("Lista").performClick().assertIsSelected()
        compose.runOnIdle { assertEquals(listOf(BentoHaptic.SegmentTick), haptics) }
    }

    @Test
    fun iconButtonTooltipAnchorIsNotASecondFocusStop() {
        setBento { BentoIconButton(BentoIcons.Share2, "Compartir", {}) }
        // Exactly one actionable node: the tooltip anchor must not add an unlabeled one for TalkBack / Switch Access.
        compose.onAllNodes(
            SemanticsMatcher.keyIsDefined(SemanticsActions.OnClick).or(SemanticsMatcher.keyIsDefined(SemanticsActions.OnLongClick))
        )
            .assertCountEquals(1)
        compose.onNodeWithContentDescription("Compartir")
            .assert(SemanticsMatcher.keyIsDefined(SemanticsActions.OnClick))
    }

    @Test
    fun iconButtonShowsItsTooltipOnLongPress() {
        setBento { BentoIconButton(BentoIcons.Share2, "Compartir", {}) }
        compose.onNodeWithContentDescription("Compartir").performTouchInput { longClick() }
        compose.onNodeWithText("Compartir").assertExists()
    }

    @Test
    fun secureFieldTogglesVisibility() {
        setBento { BentoTextField(TextFieldState("secreto"), "Contraseña", secure = true) }
        compose.onNodeWithContentDescription("Mostrar contraseña").performClick()
        compose.onNodeWithContentDescription("Ocultar contraseña").assertExists()
    }

    // ---- Navigation, overlays ------------------------------------------------------------------------------------

    @Test
    fun navigationSuiteUsesBarOnCompactAndRailOnWideAndReportsReselect() {
        var width by mutableStateOf(400)
        val events = mutableListOf<String>()
        setBento {
            Box(Modifier.requiredWidth(width.dp)) {
                BentoNavigationSuite(
                    listOf(
                        BentoNavItem("photos", "Fotos", BentoNavIcons.Images),
                        BentoNavItem("files", "Archivos", BentoNavIcons.FolderClosed)
                    ),
                    selectedKey = "photos",
                    onSelect = { events += "select:$it" },
                    onReselect = { events += "reselect:$it" }
                ) {}
            }
        }
        compose.onNodeWithTag(BentoTestTags.NavigationBar).assertExists()
        compose.onNodeWithText("Fotos").assertIsSelected().assert(SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Tab))
        compose.onNodeWithText("Archivos").performClick()
        compose.onNodeWithText("Fotos").performClick()
        compose.runOnIdle { assertEquals(listOf("select:files", "reselect:photos"), events) }
        width = 700
        compose.onNodeWithTag(BentoTestTags.NavigationRail).assertExists()
        compose.onNodeWithTag(BentoTestTags.NavigationBar).assertDoesNotExist()
    }

    @Test
    fun sheetDismissesWithBack() {
        // Material's ModalBottomSheet registers the predictive-back handler (scale + dismiss); back must close it.
        var open by mutableStateOf(true)
        setBento { if (open) BentoSheet(onDismissRequest = { open = false }, title = "Cuenta y actividad") {} }
        compose.onNodeWithText("Cuenta y actividad").assertExists()
        Espresso.pressBack()
        compose.waitForIdle()
        compose.runOnIdle { assertEquals(false, open) }
        compose.onNodeWithText("Cuenta y actividad").assertDoesNotExist()
    }

    @Test
    fun destructiveDialogConfirmsAndCancels() {
        val events = mutableListOf<String>()
        setBento {
            BentoDialog(
                title = "¿Quitar este dispositivo?",
                consequence = "Dejará de sincronizar.",
                confirmLabel = "Quitar dispositivo",
                onConfirm = { events += "confirm" },
                onDismissRequest = { events += "dismiss" }
            )
        }
        compose.onNodeWithText("Dejará de sincronizar.").assertExists()
        compose.onNodeWithText("Cancelar").performClick()
        compose.onNodeWithText("Quitar dispositivo").performClick()
        compose.runOnIdle { assertEquals(listOf("dismiss", "confirm"), events) }
    }

    @OptIn(ExperimentalAnimationGraphicsApi::class)
    @Test
    fun loaderAnimatedVectorLoadsForTheSplash() {
        var viewport = 0f
        var duration = 0
        setBento {
            val avd = bentoLoaderAnimatedVector()
            viewport = avd.imageVector.viewportWidth
            duration = avd.totalDuration
        }
        // 108-unit adaptive/splash canvas; the cells loop forever (repeatCount infinite).
        compose.runOnIdle {
            assertEquals(108f, viewport)
            assertEquals(Int.MAX_VALUE, duration)
        }
    }
}
