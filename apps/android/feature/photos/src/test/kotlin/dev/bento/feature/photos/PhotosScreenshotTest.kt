package dev.bento.feature.photos

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ApplicationProvider
import com.github.takahirom.roborazzi.captureRoboImage
import com.github.takahirom.roborazzi.captureScreenRoboImage
import dev.bento.api.generated.DriveItemResponse
import dev.bento.api.generated.FolderResponse
import dev.bento.api.generated.TelegramChatResponse
import dev.bento.designsystem.component.AvatarStatus
import dev.bento.designsystem.component.BentoSnackbarHostState
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.testing.BentoScreenshots
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.ParameterizedRobolectricTestRunner
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

private val navigation = PhotosNavigation({ _, _ -> }, {}, {}, {}, {}, {})

@Composable
private fun Photos(
    load: PhotosLoad = PhotosLoad.Live,
    card: PhotosCard? = null,
    density: GridDensity = GridDensity.Comfortable,
    selected: Int = 0,
    scrolledTo: Int = 0
) {
    val context = LocalContext.current
    val harness = remember { MediaTestHarness(context, CoroutineScope(SupervisorJob() + Dispatchers.Main)) }
    val cells = remember { ListMediaCells(cellsOf(MediaSamples.library)) }
    val month = remember { ListMediaCells(cellsOf(MediaSamples.library, dayHeaders = false)) }
    val selection = remember { SelectionState().apply { if (selected > 0) set(MediaSamples.library.take(selected), true) } }
    val grid = remember {
        MediaGridState(density).also { if (scrolledTo > 0) it.gridState().requestScrollToItem(scrolledTo, 0) }
    }
    PhotosContent(
        load = load,
        cellsFor = { if (it.dayHeaders) cells else month },
        layout = MediaSamples.layout,
        gridState = grid,
        card = card,
        account = AccountSummary("Ana Restrepo", AvatarStatus.Idle),
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

@RunWith(ParameterizedRobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = "es-w840dp-h1800dp-xhdpi")
class PhotosScreenshotTest(private val state: ScreenState) {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun capture() = compose.captureVariants(state)

    companion object {
        @JvmStatic
        @ParameterizedRobolectricTestRunner.Parameters(name = "{0}")
        fun states(): List<Array<Any>> = listOf(
            ScreenState("photos-grid") { Photos() },
            ScreenState("photos-grid-scrolled") { Photos(scrolledTo = 30) },
            ScreenState("photos-grid-large") { Photos(density = GridDensity.Large) },
            ScreenState("photos-grid-dense") { Photos(density = GridDensity.Dense) },
            ScreenState("photos-grid-month") { Photos(density = GridDensity.Month) },
            ScreenState("photos-card-backup") { Photos(card = PhotosCard.BackupOff) },
            ScreenState("photos-card-partial") { Photos(card = PhotosCard.PartialAccess(12)) },
            ScreenState("photos-selection") { Photos(selected = 4) },
            ScreenState("photos-empty") { Photos(load = PhotosLoad.Empty, card = PhotosCard.BackupOff) },
            ScreenState("photos-error") { Photos(load = PhotosLoad.Error) },
            ScreenState("photos-first-run") { Photos(load = PhotosLoad.FirstRun) }
        ).map { arrayOf<Any>(it) }
    }
}

/** Journey 7 entry screens on a phone on its side (`screenshots/<state>/landscape.png`). */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = BentoScreenshots.LANDSCAPE_QUALIFIERS)
class PhotosLandscapeScreenshotTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun grid() = compose.captureVariants(ScreenState("photos-grid") { Photos() }, listOf(LandscapeVariant))

    @Test
    fun selection() = compose.captureVariants(ScreenState("photos-selection") { Photos(selected = 4) }, listOf(LandscapeVariant))
}

/** Sheets render in their own window: captured with the whole screen, light and dark. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = "es-w411dp-h891dp-xxhdpi")
class PhotosSheetsScreenshotTest {
    @get:Rule
    val compose = createComposeRule()

    private fun sheet(name: String, dark: Boolean = false, content: @Composable () -> Unit) {
        compose.setContent {
            CompositionLocalProvider(
                LocalBentoImageLoader provides remember {
                    fakeImageLoader(ApplicationProvider.getApplicationContext())
                }
            ) {
                BentoTheme(darkTheme = dark, reducedMotion = true) { content() }
            }
        }
        compose.mainClock.advanceTimeBy(1_000)
        compose.waitForIdle()
        captureScreenRoboImage("screenshots/$name/${if (dark) "dark" else "light"}.png")
    }

    private val folders = listOf("Trabajo", "Viajes", "Recibos 2024").mapIndexed { i, name ->
        DriveItemResponse(
            folder = FolderResponse(
                createdAt = "2024-01-01T00:00:00Z",
                id = "f$i",
                name = name,
                parentId = null,
                updatedAt = "2024-01-01T00:00:00Z"
            ),
            id = "f$i",
            name = name,
            type = "folder",
            updatedAt = "2024-01-01T00:00:00Z"
        )
    }

    @Test
    fun albumSheet() = sheet("sheet-add-to-album") { AddToAlbumSheetContent(SheetData.Ready(MediaSamples.albums), {}, {}, {}) }

    @Test
    fun albumSheetDark() = sheet("sheet-add-to-album", dark = true) {
        AddToAlbumSheetContent(SheetData.Ready(MediaSamples.albums), {}, {}, {})
    }

    @Test
    fun moveSheet() = sheet("sheet-move") {
        MoveToFolderSheetContent(listOf("Archivos", "Fotos"), SheetData.Ready(folders), {}, {}, {}, {})
    }

    @Test
    fun telegramSheet() = sheet("sheet-telegram") {
        val chats = listOf(
            TelegramChatResponse(1, "saved", "Mensajes guardados"),
            TelegramChatResponse(2, "user", "Mamá"),
            TelegramChatResponse(3, "group", "Familia Restrepo")
        )
        TelegramChatSheetContent(SheetData.Ready(chats), rememberTextFieldState(), {}, {})
    }

    @Test
    fun disclosureSheet() = sheet("sheet-disclosure") { PlaintextDisclosureSheet(Disclosure.Share, {}, {}) }

    @Test
    fun disclosureSheetDark() = sheet("sheet-disclosure", dark = true) { PlaintextDisclosureSheet(Disclosure.SaveToPhone, {}, {}) }
}
