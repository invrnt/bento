package dev.bento.feature.files

import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.longClick
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performKeyInput
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.pressKey
import androidx.compose.ui.test.requestFocus
import androidx.compose.ui.test.withKeyDown
import dev.bento.api.generated.DriveBreadcrumbResponse
import dev.bento.designsystem.theme.BentoTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(qualifiers = "es-w411dp-h891dp")
class FilesUiTest {
    @get:Rule
    val compose = createComposeRule()

    private val items = FilesFixtures.sample
    private fun state(vararg changes: (FilesState) -> FilesState) =
        changes.fold(FilesState(loading = false, items = FolderSort().apply(items))) { acc, change -> change(acc) }

    private fun content(
        state: FilesState,
        actions: FilesActions = FilesActions(),
        uploads: UploadsState = UploadsState(),
        audio: AudioState = AudioState()
    ) =
        compose.setContent { BentoTheme { FilesContent(state, uploads, audio, actions) } }

    @Test
    fun listShowsFoldersFirstWithSupportingLineAndBadges() {
        content(state())
        compose.onNodeWithText("Trabajo").assertIsDisplayed()
        compose.onNodeWithText("Declaración de renta 2025.pdf").assertExists()
        compose.onNodeWithText("2,4\u00A0MB", substring = true).assertExists()
        compose.onNodeWithText("Ordenado por nombre").assertExists()
        val notes = compose.onNode(hasText("Notas de la reunión.md"), useUnmergedTree = false).fetchSemanticsNode()
        assertEquals("Solo en este teléfono", notes.config.getOrNull(SemanticsProperties.StateDescription))
    }

    @Test
    fun foldersShowTheirItemCountAndFilesTheirOfflineState() {
        content(state())
        // The count goes through BentoFormat (locale digits); one item is singular.
        val count = dev.bento.designsystem.format.BentoFormat.count(1_240, java.util.Locale("es"))
        compose.onNodeWithText("$count elementos", substring = true).assertExists()
        compose.onNodeWithText("1 elemento", substring = true).assertExists()
        val tax = compose.onNode(hasText("Declaración de renta 2025.pdf")).fetchSemanticsNode()
        assertEquals("Disponible sin conexión", tax.config.getOrNull(SemanticsProperties.StateDescription))
        val song = compose.onNode(hasText("Voz de la abuela.m4a")).fetchSemanticsNode()
        assertEquals("En este teléfono", song.config.getOrNull(SemanticsProperties.StateDescription))
    }

    @Test
    fun tapOpensLongPressSelectsAndMenuOpens() {
        val log = mutableListOf<String>()
        content(
            state(),
            FilesActions(onOpen = { log += "open:${it.id}" }, onSelect = { log += "select:${it.id}" }, onMenu = {
                log +=
                    "menu:${it.id}"
            })
        )
        compose.onNodeWithText("Trabajo").performClick()
        compose.onNodeWithText("Presupuesto hogar.xlsx").performTouchInput { longClick() }
        compose.onNodeWithContentDescription("Opciones de «Voz de la abuela.m4a»").performClick()
        assertEquals(listOf("open:f_work", "select:a_sheet", "menu:a_song"), log)
    }

    @Test
    fun customAccessibilityActionsCoverEveryGesture() {
        val log = mutableListOf<String>()
        content(state(), FilesActions(onTrash = { log += "trash:${it.single().id}" }, onShare = { log += "share:${it.single().id}" }))
        val row = compose.onNode(hasText("Declaración de renta 2025.pdf"))
        val actions = row.fetchSemanticsNode().config[SemanticsActions.CustomActions].map { it.label }
        assertEquals(listOf("Abrir", "Seleccionar", "Compartir", "Favorito", "Eliminar"), actions)
        row.fetchSemanticsNode().config[SemanticsActions.CustomActions].first { it.label == "Eliminar" }.action()
        assertEquals(listOf("trash:a_tax"), log)
    }

    @Test
    fun selectionBarActions() {
        val log = mutableListOf<String>()
        val selected = state({ it.copy(selection = setOf("a_tax", "a_zip")) })
        content(
            selected,
            FilesActions(onMove = { log += "move:${it.size}" }, onTrash = { log += "trash:${it.size}" }, onClearSelection = {
                log +=
                    "clear"
            })
        )
        compose.onNodeWithContentDescription("2 seleccionados").assertExists()
        compose.onNodeWithContentDescription("Mover").performClick()
        compose.onNodeWithContentDescription("Eliminar").performClick()
        compose.onNodeWithContentDescription("Cancelar selección").performClick()
        assertEquals(listOf("move:2", "trash:2", "clear"), log)
    }

    @Test
    fun keyboardShortcuts() {
        val log = mutableListOf<String>()
        content(
            state({
                it.copy(selection = setOf("a_tax"))
            }),
            FilesActions(onSelectAll = { log += "all" }, onTrash = { log += "trash" }, onSearchHere = {
                log +=
                    "find"
            })
        )
        val row = compose.onNodeWithTag("files-root")
        row.requestFocus()
        row.performKeyInput { withKeyDown(Key.CtrlLeft) { pressKey(Key.A) } }
        row.performKeyInput { pressKey(Key.Delete) }
        row.performKeyInput { withKeyDown(Key.CtrlLeft) { pressKey(Key.F) } }
        assertEquals(listOf("all", "trash", "find"), log)
    }

    @Test
    fun emptyErrorAndOfflineStates() {
        var created = 0
        var retried = 0
        var current by androidx.compose.runtime.mutableStateOf(FilesState(loading = false))
        compose.setContent {
            BentoTheme { FilesContent(current, UploadsState(), AudioState(), FilesActions(onNew = { created++ }, onRetry = { retried++ })) }
        }
        compose.onNodeWithText("Tu nube está lista").assertExists()
        compose.onAllNodes(hasText("Nuevo"))[0].performClick()
        current = FilesState(loading = false, folderId = "f", breadcrumbs = listOf(DriveBreadcrumbResponse("f", "Trabajo")))
        compose.onNodeWithText("Esta carpeta está vacía").assertExists()
        current = FilesState(loading = false, loadFailed = true)
        compose.onNodeWithText("Reintentar").performClick()
        current = state({ it.copy(offline = true) })
        compose.onNodeWithText("Sin conexión", substring = true).assertExists()
        assertEquals(1, created)
        assertEquals(1, retried)
    }

    @Test
    fun breadcrumbsNavigateAndLongPressShowsPath() {
        val nav = mutableListOf<String?>()
        content(
            state({
                it.copy(
                    folderId = "f2",
                    breadcrumbs = listOf(DriveBreadcrumbResponse("f1", "Trabajo"), DriveBreadcrumbResponse("f2", "2024"))
                )
            }),
            FilesActions(onNavigate = { nav += it })
        )
        compose.onNode(hasContentDescription("Ruta: Archivos › Trabajo › 2024")).assertExists()
        compose.onAllNodes(hasText("Trabajo"))[0].performClick()
        compose.onNodeWithContentDescription("Subir un nivel").performClick()
        compose.onNodeWithContentDescription("Subir un nivel").performTouchInput { longClick() }
        compose.onAllNodes(hasText("Archivos"))[0].assertExists()
        assertEquals(listOf("f1", "f1"), nav)
    }

    @Test
    fun uploadCardSummarizesAndPauses() {
        var paused = 0
        val uploads = UploadsState(
            rows = listOf(
                UploadRow(1, "a.jpg", 12_000_000, UploadStatus.Done),
                UploadRow(2, "b.pdf", 18_000_000, UploadStatus.Copying),
                UploadRow(3, "c.mov", 10_000_000, UploadStatus.Queued)
            )
        )
        compose.setContent { BentoTheme { UploadCard(uploads, onPause = { paused++ }, onResume = {}, onDismiss = {}) } }
        compose.onNodeWithText("Subiendo 2 archivos · 12\u00A0MB de 40\u00A0MB").assertExists()
        compose.onNodeWithText("Pausar").performClick()
        compose.onNodeWithContentDescription("Ver archivos").performClick()
        compose.onNodeWithText("Copiando…").assertExists()
        assertEquals(1, paused)
    }

    @Test
    fun sheetsCallBack() {
        val log = mutableListOf<String>()
        compose.setContent {
            BentoTheme {
                androidx.compose.foundation.layout.Column {
                    NewSheetBody("Trabajo", scanAvailable = false, { log += "files" }, { log += "media" }, { log += "tree" }, {
                        log +=
                            "scan"
                    }, { log += "folder" })
                    ItemMenuBody(items.first { it.id == "a_tax" }, pinned = true) { log += it.name }
                }
            }
        }
        compose.onNodeWithText("Añadir a «Trabajo»").assertExists()
        compose.onNodeWithText("Escanear documento").assertDoesNotExist()
        compose.onNodeWithText("Subir una carpeta").performClick()
        compose.onNodeWithText("Nueva carpeta").performClick()
        compose.onNodeWithText("Quitar de sin conexión").performClick()
        compose.onNodeWithText("Enviar por Telegram…").performClick()
        assertEquals(listOf("tree", "folder", "Offline", "Telegram"), log)
    }

    @Test
    fun sortSheetChangesFieldAndDirection() {
        val picked = mutableListOf<FolderSort>()
        compose.setContent { BentoTheme { SortSheetBody(FolderSort()) { picked += it } } }
        compose.onNodeWithText("Tamaño").performClick()
        compose.onNodeWithText("Descendente").performClick()
        assertEquals(listOf(FolderSort(SortField.Size), FolderSort(descending = true)), picked)
    }

    @Test
    fun movePickerBlocksTheMovedFolderAndConfirms() {
        val picked = mutableListOf<Destination>()
        val work = items.first { it.id == "f_work" }
        val browser =
            FolderBrowserState(loading = false, folders = listOf(work, items.first { it.id == "f_trips" }), blocked = setOf("f_work"))
        compose.setContent {
            BentoTheme { FolderPickerBody("Mover a…", "Mover aquí", browser, {}, {}, {}, {}, { picked += it }) }
        }
        compose.onNode(hasText("Trabajo")).assertIsNotEnabled()
        compose.onNodeWithText("Mover aquí").performClick()
        assertEquals(listOf(Destination(null, "Archivos")), picked)
    }

    @Test
    fun disclosureRemembersDontShowAgain() {
        val result = mutableListOf<Boolean>()
        compose.setContent { BentoTheme { DisclosureSheetBody(Disclosure.OpenWith, { result += it }, {}) } }
        compose.onNodeWithText("La otra app recibirá una copia sin cifrar.").assertExists()
        compose.onNodeWithText("No volver a mostrar").performClick()
        compose.onNodeWithText("Continuar").performClick()
        assertEquals(listOf(true), result)
    }

    @Test
    fun newFolderFieldShowsErrors() {
        compose.setContent {
            BentoTheme {
                NameSheetBody(
                    "Nueva carpeta",
                    "Nombre de la carpeta",
                    "Crear",
                    rememberTextFieldState(
                        "Trabajo"
                    ),
                    UiText.of(dev.bento.strings.R.string.files_new_folder_exists),
                    false,
                    {
                    },
                    autoFocus = false
                )
            }
        }
        compose.onNodeWithText("Ya hay una carpeta con ese nombre aquí.").assertExists()
    }

    @Test
    fun pdfReaderCountsPagesAndSearches() {
        val queries = mutableListOf<String>()
        val pdf = FakePdf()
        val state = DocumentState(
            asset = FilesFixtures.d(FilesFixtures.file("a", "Contrato.pdf")).asset,
            body = DocumentBody.Pdf(pdf),
            search = PdfSearch(open = true, query = "factura", matches = listOf(PdfMatch(1, emptyList()), PdfMatch(3, emptyList())))
        )
        compose.setContent { BentoTheme { DocumentContent(state, onBack = {}, onQuery = { queries += it }) } }
        compose.onNodeWithText("1 de 2").assertExists()
        compose.onAllNodes(hasText("Página 1 de 5"))[0].assertExists()
        compose.onNodeWithContentDescription("Ir a la página 3").assertExists()
        assertTrue(queries.isEmpty())
    }

    @Test
    fun audioMiniPlayer() {
        var toggled = 0
        compose.setContent {
            BentoTheme {
                AudioMiniPlayer(AudioState("a", "Voz.m4a", playing = true, positionMs = 65_000, durationMs = 180_000), { toggled++ }, {})
            }
        }
        compose.onNodeWithText("1:05 de 3:00").assertExists()
        compose.onNodeWithContentDescription("Pausar").performClick()
        assertEquals(1, toggled)
    }
}
