package dev.bento.feature.files

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createComposeRule
import dev.bento.api.generated.DriveBreadcrumbResponse
import dev.bento.api.generated.TelegramChatResponse
import dev.bento.testing.BentoScreenshots
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = BentoScreenshots.QUALIFIERS)
class FilesScreenshotTest {
    @get:Rule
    val compose = createComposeRule()

    private fun shot(name: String, content: @Composable () -> Unit) = BentoScreenshots.capture(compose, "screenshots", name, content)

    private val items = FolderSort().apply(FilesFixtures.sample)
    private val live = FilesState(loading = false, items = items, pinned = setOf("a_tax"))
    private val crumbs = listOf(DriveBreadcrumbResponse("f_work", "Trabajo"), DriveBreadcrumbResponse("f_2024", "2024"))
    private val tree = mapOf(
        null to items.filter { it.folder != null },
        "f_work" to listOf(FilesFixtures.d(FilesFixtures.folder("f_2024", "2024", "f_work")))
    )

    @Composable
    private fun files(state: FilesState, uploads: UploadsState = UploadsState(), audio: AudioState = AudioState()) =
        FilesContent(state, uploads, audio, FilesActions())

    @Composable
    private fun sheet(content: @Composable () -> Unit) = Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) {
        SheetFrame { content() }
    }

    @Test fun list() = shot("list") { files(live) }

    @Test fun grid() = shot("grid") { files(live.copy(layout = FilesLayout.Grid)) }

    @Test fun subfolderWithBreadcrumbs() = shot("subfolder") {
        files(live.copy(folderId = "f_2024", breadcrumbs = crumbs, items = items.drop(2).take(3)))
    }

    @Test fun cachedOffline() = shot("offline") { files(live.copy(offline = true, fromCache = true)) }

    @Test fun loading() = shot("loading") { files(FilesState()) }

    @Test fun error() = shot("error") { files(FilesState(loading = false, loadFailed = true)) }

    @Test fun emptyRoot() = shot("empty-root") { files(FilesState(loading = false)) }

    @Test fun emptyFolder() = shot("empty-folder") { files(FilesState(loading = false, folderId = "f", breadcrumbs = crumbs.take(1))) }

    @Test fun selection() = shot("selection") { files(live.copy(selection = setOf("a_tax", "a_sheet"))) }

    @Test fun uploading() = shot("uploading") {
        files(
            live,
            UploadsState(
                listOf(
                    UploadRow(1, "IMG_2041.jpg", 3_200_000, UploadStatus.Done),
                    UploadRow(2, "Contrato.pdf", 9_000_000, UploadStatus.Copying),
                    UploadRow(3, "Video.mp4", 28_000_000)
                )
            )
        )
    }

    @Test fun uploadCardExpanded() = shot("upload-card-expanded") {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) {
            UploadCard(
                UploadsState(
                    listOf(
                        UploadRow(1, "IMG_2041.jpg", 3_200_000, UploadStatus.Done),
                        UploadRow(2, "Recibo.pdf", null, UploadStatus.Failed, "content_unreadable"),
                        UploadRow(3, "Contrato.pdf", 9_000_000, UploadStatus.Copying),
                        UploadRow(4, "Notas.txt", 900, UploadStatus.Duplicate)
                    ),
                    paused = true
                ),
                {},
                {},
                {},
                initiallyExpanded = true
            )
        }
    }

    @Test fun audioAndPreparing() = shot("audio-preparing") {
        files(
            live.copy(preparing = Preparing("Copia del proyecto.zip", 300_000_000, 812_000_000)),
            audio = AudioState("a_song", "Voz de la abuela.m4a", playing = true, positionMs = 42_000, durationMs = 185_000)
        )
    }

    @Test fun expandedListDetail() = shot("expanded-tree") {
        files(live.copy(folderId = "f_work", breadcrumbs = crumbs.take(1), tree = tree, expanded = setOf("f_work")))
    }

    @Test fun newSheet() = shot("sheet-new") { sheet { NewSheetBody("Trabajo", true, {}, {}, {}, {}, {}) } }

    @Test fun newFolderSheet() = shot("sheet-new-folder") {
        sheet {
            NameSheetBody("Nueva carpeta", "Nombre de la carpeta", "Crear", rememberTextFieldState("Facturas 2026"), null, false, {
            }, autoFocus = false)
        }
    }

    @Test fun sortSheet() = shot("sheet-sort") { sheet { SortSheetBody(FolderSort(SortField.Modified, descending = true)) {} } }

    @Test fun itemMenu() = shot("sheet-item-menu") { sheet { ItemMenuBody(items.first { it.id == "a_tax" }, pinned = false) {} } }

    @Test fun moveSheet() = shot("sheet-move") {
        sheet {
            FolderPickerBody(
                "Mover a…",
                "Mover aquí",
                FolderBrowserState(
                    loading = false,
                    folders = items.filter { it.folder != null },
                    recent = listOf(Destination("f_x", "Facturas"), Destination("f_y", "Escaneos")),
                    blocked = setOf("f_trips")
                ),
                {},
                {},
                {},
                {},
                {}
            )
        }
    }

    @Test fun detailsSheet() = shot("sheet-details") {
        sheet { DetailsSheetBody(items.first { it.id == "a_tax" }, "Archivos › Trabajo", pinned = true) }
    }

    @Test fun telegramSheet() = shot("sheet-telegram") {
        sheet {
            TelegramSheetBody(
                TelegramPicker(
                    loading = false,
                    chats = listOf(TelegramChatResponse(1, "user", "Mensajes guardados"), TelegramChatResponse(2, "user", "Mamá"))
                ),
                {
                },
                {}
            )
        }
    }

    @Test fun disclosureSheet() = shot("sheet-disclosure") { sheet { DisclosureSheetBody(Disclosure.Share, {}, {}) } }

    @Test fun offlineSheet() = shot("sheet-offline") { sheet { OfflineSheetBody(items.first { it.id == "a_tax" }) {} } }

    @Test fun pdfReader() = shot("pdf-reader") {
        DocumentContent(
            DocumentState(
                asset = FilesFixtures.d(FilesFixtures.file("a", "Contrato de arriendo.pdf")).asset,
                body = DocumentBody.Pdf(FakePdf()),
                page = 1,
                search = PdfSearch(
                    open = true,
                    query = "canon",
                    matches = listOf(PdfMatch(1, listOf(android.graphics.RectF(0.1f, 0.2f, 0.5f, 0.24f))))
                )
            ),
            onBack = {}
        )
    }

    @Test fun textViewer() = shot("text-viewer") {
        DocumentContent(
            DocumentState(
                asset = FilesFixtures.d(FilesFixtures.file("a", "Notas de la reunión.md", mime = "text/markdown")).asset,
                body = DocumentBody.Text(
                    "# Reunión 24 de noviembre\n\n- Revisar el presupuesto\n- Enviar el contrato firmado\n\nfun main() = println(\"Hola\")"
                ),
                monospace = true
            ),
            onBack = {}
        )
    }

    @Test fun documentOffline() = shot("document-offline") {
        DocumentContent(
            DocumentState(
                asset = FilesFixtures.d(FilesFixtures.file("a", "Contrato.pdf")).asset,
                body = DocumentBody.Offline
            ),
            onBack = {
            }
        )
    }
}
