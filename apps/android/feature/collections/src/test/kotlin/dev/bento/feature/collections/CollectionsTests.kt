package dev.bento.feature.collections

import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertHasClickAction
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithContentDescription
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import dev.bento.api.generated.TelegramMediaResponse
import dev.bento.data.DocumentEntry
import dev.bento.data.DocumentsRepository
import dev.bento.data.PhoneFolder
import dev.bento.designsystem.component.AvatarStatus
import dev.bento.designsystem.component.BentoSnackbarHostState
import dev.bento.designsystem.component.FileKind
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.photos.AccountSummary
import dev.bento.feature.photos.ListMediaCells
import dev.bento.feature.photos.MediaSamples
import dev.bento.feature.photos.MediaTestHarness
import dev.bento.feature.photos.ScreenState
import dev.bento.feature.photos.captureVariants
import dev.bento.feature.photos.cellsOf
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.ParameterizedRobolectricTestRunner
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

private const val DAY = 86_400_000L
private val NOW = java.time.OffsetDateTime.parse("2024-03-20T12:00:00Z").toInstant().toEpochMilli()

private fun trashItem(
    id: String,
    name: String,
    days: Long,
    size: Long = 2_400_000,
    type: String = "asset",
    thumb: Boolean = true
) = TrashItem(
    id = id,
    type = type,
    name = name,
    sizeBytes = size,
    deletedAt = "2024-03-01T00:00:00Z",
    purgeAt = java.time.Instant.ofEpochMilli(NOW + days * DAY + 3_600_000).toString(),
    hasThumbnail = thumb
)

private val sampleTrash = listOf(
    trashItem("p1", "IMG_p1.jpg", 12),
    trashItem("t2", "Factura de luz.pdf", 3, 180_000, thumb = false),
    trashItem("t3", "Viejo", 0, 0, type = "folder", thumb = false)
)

private val sampleDocs = DocumentsRepository.Result(
    listOf(
        DocumentEntry(
            "d1",
            "Factura de luz marzo.pdf",
            "/Trabajo/Factura de luz marzo.pdf",
            "application/pdf",
            182_000,
            "2024-03-12T09:00:00Z"
        ),
        DocumentEntry(
            "d2",
            "Presupuesto 2024.xlsx",
            "/Casa/Presupuesto 2024.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            48_000,
            "2024-03-02T09:00:00Z"
        ),
        DocumentEntry("d3", "Notas.txt", "/Notas.txt", "text/plain", 2_100, "2024-02-11T09:00:00Z")
    ),
    truncated = false
)

private val sampleFolders = listOf(
    PhoneFolder("s1", "Cámara", "media_store", true, "idle", 1_240, 1_240, 0, "2024-03-20T10:00:00Z", null),
    PhoneFolder("s2", "Capturas de pantalla", "media_store", true, "idle", 312, 300, 12, null, null),
    PhoneFolder("s3", "WhatsApp Images", "media_store", false, "idle", 0, 0, 0, null, null)
)

private val sampleTelegram = TelegramMediaViewModel.MediaUi(
    listOf(
        TelegramMediaResponse("2024-03-14T10:00:00Z", "photo_2024-03-14.jpg", "photo", 11, 2_100_000),
        TelegramMediaResponse("2024-03-13T10:00:00Z", "video_2024-03-13.mp4", "video", 12, 18_000_000),
        TelegramMediaResponse("2024-03-10T10:00:00Z", "Contrato.pdf", "document", 13, 320_000)
    ),
    nextCursor = null
)

private fun navigation(log: MutableList<String> = mutableListOf()) = CollectionsNavigation(
    back = { log += "back" },
    openSearch = { log += "search" },
    openAccount = { log += "account" },
    openAlbum = { log += "album:$it" },
    newAlbum = { log += "new-album" },
    addToAlbum = { log += "add:$it" },
    openFavorites = { log += "favorites" },
    openVideos = { log += "videos" },
    openDocuments = { log += "documents" },
    openPhone = { log += "phone" },
    openTelegram = { log += "telegram" },
    openTelegramChats = { log += "telegram-chats" },
    openTelegramChat = { id, _ -> log += "chat:$id" },
    openTrash = { log += "trash" },
    openBackupSettings = { log += "backup" },
    openViewer = { id, _, _ -> log += "viewer:$id" }
)

class CollectionsModelTest {
    @Test
    fun `trash entries parse and count days left`() {
        val json = buildJsonObject {
            put("id", "a1")
            put("type", "asset")
            put("name", "foto.jpg")
            put("size_bytes", 10)
            put("deleted_at", "2024-03-01T00:00:00Z")
            put("purge_at", "2024-03-31T00:00:00Z")
            put("thumbnail_url", "/api/assets/a1/thumbnail")
        }
        val item = TrashItem.from(json)!!
        assertEquals("foto.jpg", item.name)
        assertEquals(true, item.hasThumbnail)
        assertEquals(10, TrashItem.daysLeft(item.purgeAt, NOW))
        assertEquals(0, TrashItem.daysLeft("2024-03-19T00:00:00Z", NOW))
        assertNull(TrashItem.daysLeft(null, NOW))
        assertNull(TrashItem.from(buildJsonObject { put("name", JsonPrimitive("sin id")) }))
    }

    @Test
    fun `file kinds come from the MIME type`() {
        assertEquals(FileKind.Pdf, fileKindOf("application/pdf"))
        assertEquals(FileKind.Sheet, fileKindOf("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
        assertEquals(FileKind.Sheet, fileKindOf("", "datos.csv"))
        assertEquals(FileKind.Slides, fileKindOf("application/vnd.ms-powerpoint"))
        assertEquals(FileKind.Archive, fileKindOf("application/zip"))
        assertEquals(FileKind.Text, fileKindOf("text/markdown"))
        assertEquals(FileKind.Doc, fileKindOf("application/msword"))
    }
}

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = "es-w411dp-h891dp-xxhdpi")
class CollectionsUiTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun `hub rows and album covers navigate`() {
        val log = mutableListOf<String>()
        compose.setContent {
            BentoTheme(reducedMotion = true) {
                CollectionsContent(MediaSamples.albums, false, AccountSummary("Ana", AvatarStatus.Idle), navigation(log))
            }
        }
        compose.onNodeWithText("Favoritos").performClick()
        compose.onNodeWithText("Papelera").performClick()
        compose.onNodeWithText("Importado de Telegram").performClick()
        compose.onNodeWithTag(CollectionsTestTags.Hub).performScrollToNode(hasText("Viaje a Cartagena"))
        compose.onNodeWithText("12 elementos", useUnmergedTree = true).assertExists()
        compose.onNodeWithText("Viaje a Cartagena").performClick()
        compose.onNodeWithText("Nuevo álbum").performClick()
        assertEquals(listOf("favorites", "trash", "telegram", "album:a1", "new-album"), log)
    }

    @Test
    fun `vaciar papelera states count and size before the irreversible confirm`() {
        val emptied = mutableListOf<Unit>()
        compose.setContent {
            BentoTheme(reducedMotion = true) {
                TrashContent(sampleTrash, false, false, 3 to 2_580_000L, remember { BentoSnackbarHostState() }, {}, {}, {}, {}, {
                    emptied +=
                        Unit
                }, {}, nowMs = NOW)
            }
        }
        compose.onNodeWithText("Se eliminará en 12 días · 2,4\u00A0MB").assertExists()
        compose.onNodeWithText("Se eliminará hoy · 0\u00A0B").assertExists()
        compose.onNodeWithText("Vaciar papelera").performClick()
        compose.onNodeWithText("Se eliminarán para siempre 3 elementos (2,6\u00A0MB). No se puede deshacer.").assertIsDisplayed()
        compose.onAllNodesWithText("Vaciar papelera").assertCountEquals(2)
        compose.onNodeWithText("Cancelar").performClick()
        assertEquals(0, emptied.size)
    }

    @Test
    fun `eliminar para siempre asks first, restore is one tap`() {
        val purged = mutableListOf<String>()
        val restored = mutableListOf<String>()
        compose.setContent {
            BentoTheme(reducedMotion = true) {
                TrashContent(
                    sampleTrash, false, false, null,
                    remember {
                        BentoSnackbarHostState()
                    },
                    {}, { restored += it }, { purged += it }, {}, {}, {}, nowMs = NOW
                )
            }
        }
        compose.onNodeWithText("Factura de luz.pdf").performClick()
        compose.onNodeWithText("Eliminar para siempre").performClick()
        compose.onNodeWithText("Se borrará de tu nube y de todos tus dispositivos. No se puede deshacer.").assertIsDisplayed()
        compose.onNodeWithText("Eliminar para siempre").performClick()
        assertEquals(listOf("t2"), purged)
        compose.onAllNodesWithContentDescription("Restaurar", useUnmergedTree = true).assertCountEquals(sampleTrash.size)
    }

    @Test
    fun `telegram import counts the selection`() {
        compose.setContent {
            BentoTheme(reducedMotion = true) {
                TelegramMediaContent("Mensajes guardados", Loadable.Ready(sampleTelegram), "all", setOf(11L, 13L), {}, {}, {}, {}, {}, {})
            }
        }
        compose.onNodeWithText("Importar 2").assertIsEnabled()
        compose.onNodeWithText("Seleccionar todo").assertIsDisplayed()
    }

    @Test
    fun `album menu offers rename and delete, and delete explains the photos stay`() {
        val log = mutableListOf<String>()
        var confirm by mutableStateOf(false)
        compose.setContent {
            BentoTheme(reducedMotion = true) {
                AlbumGrid(onRename = { log += "rename" }, onDelete = { confirm = true })
                if (confirm) AlbumDeleteDialog("Viaje a Cartagena", onConfirm = { log += "delete" }, onDismiss = { confirm = false })
            }
        }
        compose.onNodeWithContentDescription("Opciones del álbum").assertHasClickAction().performClick()
        compose.onNodeWithText("Cambiar nombre").performClick()
        compose.onNodeWithContentDescription("Opciones del álbum").performClick()
        compose.onNodeWithText("Eliminar álbum").performClick()
        compose.onNodeWithText("¿Eliminar «Viaje a Cartagena»?").assertIsDisplayed()
        compose.onNodeWithText("El álbum desaparece en todos tus dispositivos. Las fotos siguen en Fotos.").assertIsDisplayed()
        compose.onNodeWithText("Eliminar álbum").performClick()
        assertEquals(listOf("rename", "delete"), log)
    }

    @Test
    fun `rename refuses an empty name`() {
        val saved = mutableListOf<String>()
        compose.setContent {
            BentoTheme(reducedMotion = true) {
                androidx.compose.foundation.layout.Column { AlbumRenameBody("Viaje", false) { saved += it } }
            }
        }
        val field = compose.onNode(androidx.compose.ui.test.hasSetTextAction())
        field.performTextClearance()
        compose.onNodeWithText("Guardar").performClick()
        compose.onNodeWithText("Escribe un nombre para el álbum.", useUnmergedTree = true).assertExists()
        field.performTextInput("Cartagena")
        compose.onNodeWithText("Guardar").performClick()
        assertEquals(listOf("Cartagena"), saved)
    }

    @Test
    fun `telegram import is disabled without a selection`() {
        compose.setContent {
            BentoTheme(reducedMotion = true) {
                TelegramMediaContent("Mamá", Loadable.Ready(sampleTelegram), "photo", emptySet(), {}, {}, {}, {}, {}, {})
            }
        }
        compose.onNodeWithText("Importar 0").assertIsNotEnabled()
    }
}

@Composable
private fun AlbumGrid(empty: Boolean = false, onRename: () -> Unit = {}, onDelete: () -> Unit = {}) {
    val context = LocalContext.current
    val harness = remember { MediaTestHarness(context, CoroutineScope(SupervisorJob() + Dispatchers.Main)) }
    val assets = if (empty) emptyList() else MediaSamples.library.take(12)
    val cells = remember { ListMediaCells(cellsOf(assets)) }
    CollectionGridScreen(
        title = "Viaje a Cartagena",
        cellsFor = { cells },
        isEmpty = empty,
        loading = false,
        failed = false,
        actions = harness.actions,
        onBack = {},
        onOpen = { _, _ -> },
        onRetry = {},
        empty = {
            dev.bento.designsystem.component.EmptyState(
                title = androidx.compose.ui.res.stringResource(dev.bento.strings.R.string.collections_album_empty_title),
                body = androidx.compose.ui.res.stringResource(dev.bento.strings.R.string.collections_album_empty_body),
                icon = dev.bento.designsystem.generated.BentoIcons.SquareLibrary
            )
        },
        bottomAction = {
            dev.bento.designsystem.component.BentoFab(
                androidx.compose.ui.res.stringResource(dev.bento.strings.R.string.collections_album_add_photos),
                dev.bento.designsystem.generated.BentoIcons.ImagePlus,
                {}
            )
        },
        onRemoveFromAlbum = {},
        onSetCover = {},
        topActions = { AlbumMenu(onRename = onRename, onDelete = onDelete) }
    )
}

@RunWith(ParameterizedRobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = "es-w840dp-h1800dp-xhdpi")
class CollectionsScreenshotTest(private val state: ScreenState) {
    @get:Rule
    val compose = createComposeRule()

    @org.junit.Before
    fun utc() {
        java.util.TimeZone.setDefault(java.util.TimeZone.getTimeZone("UTC"))
    }

    @Test
    fun capture() = compose.captureVariants(state)

    companion object {
        private val account = AccountSummary("Ana Restrepo", AvatarStatus.Idle)

        @JvmStatic
        @ParameterizedRobolectricTestRunner.Parameters(name = "{0}")
        fun states(): List<Array<Any>> = listOf(
            ScreenState("collections-hub") { CollectionsContent(MediaSamples.albums, false, account, navigation()) },
            ScreenState("collections-hub-no-albums") { CollectionsContent(emptyList(), false, account, navigation()) },
            ScreenState("collections-album") { AlbumGrid() },
            ScreenState("collections-album-empty") { AlbumGrid(empty = true) },
            ScreenState("collections-trash") {
                TrashContent(sampleTrash, false, false, null, remember { BentoSnackbarHostState() }, {}, {}, {}, {}, {}, {}, nowMs = NOW)
            },
            ScreenState("collections-trash-empty") {
                TrashContent(emptyList(), false, false, null, remember { BentoSnackbarHostState() }, {}, {}, {}, {}, {}, {}, nowMs = NOW)
            },
            ScreenState("collections-documents") { DocumentsContent(Loadable.Ready(sampleDocs), {}, {}, {}) },
            ScreenState("collections-documents-empty") {
                DocumentsContent(Loadable.Ready(DocumentsRepository.Result(emptyList(), false)), {}, {}, {})
            },
            ScreenState("collections-documents-error") { DocumentsContent(Loadable.Failed, {}, {}, {}) },
            ScreenState("collections-phone") { PhoneFoldersContent(Loadable.Ready(sampleFolders), {}, {}, {}) },
            ScreenState("collections-phone-empty") { PhoneFoldersContent(Loadable.Ready(emptyList()), {}, {}, {}) },
            ScreenState("collections-telegram") { TelegramImportsContent({}, {}) },
            ScreenState("collections-telegram-media") {
                TelegramMediaContent("Mensajes guardados", Loadable.Ready(sampleTelegram), "all", setOf(11L), {}, {}, {}, {}, {}, {})
            },
            ScreenState("collections-telegram-media-loading") {
                Box { TelegramMediaContent("Mamá", Loadable.Loading, "all", emptySet(), {}, {}, {}, {}, {}, {}) }
            }
        ).map { arrayOf<Any>(it) }
    }
}
