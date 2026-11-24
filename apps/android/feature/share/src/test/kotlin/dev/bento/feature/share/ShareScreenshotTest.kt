package dev.bento.feature.share

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createComposeRule
import dev.bento.api.BentoJson
import dev.bento.api.generated.DriveItemResponse
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.files.Destination
import dev.bento.feature.files.FolderBrowserState
import dev.bento.feature.files.SheetFrame
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
class ShareScreenshotTest {
    @get:Rule
    val compose = createComposeRule()

    private fun folder(id: String, name: String) = BentoJson.decodeFromString(
        DriveItemResponse.serializer(),
        """{"id":"$id","name":"$name","type":"folder","updated_at":"2026-11-18T10:00:00+00:00","asset":null,""" +
            """"folder":{"id":"$id","name":"$name","parent_id":null,"created_at":"2026-11-18T10:00:00+00:00","updated_at":"2026-11-18T10:00:00+00:00"}}"""
    )

    private val browser = FolderBrowserState(
        loading = false,
        folders = listOf(folder("f1", "Recibos"), folder("f2", "Trabajo"), folder("f3", "Viajes 2024")),
        recent = listOf(Destination("f1", "Recibos"))
    )

    /** The sheet over the sending app: the translucent window shows the scrim, then the sheet. */
    private fun shot(name: String, state: ShareState, picker: FolderBrowserState = FolderBrowserState(loading = false)) =
        BentoScreenshots.capture(compose, "screenshots", name) {
            Box(Modifier.fillMaxSize().background(BentoTheme.colors.scrim), contentAlignment = Alignment.BottomCenter) {
                SheetFrame { ShareSheetBody(state, picker, ShareActions()) }
            }
        }

    @Test fun loading() = shot("loading", ShareState())

    @Test fun media() = shot("media", ShareFixtures.media.copy(album = ShareFixtures.album))

    @Test fun mixedWithUnreadable() = shot("mixed-unreadable", ShareFixtures.mixed)

    @Test fun note() = shot("note", ShareFixtures.note)

    @Test fun nothing() = shot("nothing", ShareState(loading = false))

    @Test fun albumPicker() = shot(
        "album-picker",
        ShareFixtures.media.copy(picker = SharePicker.Album, albums = listOf(ShareFixtures.album))
    )

    @Test fun folderPicker() = shot("folder-picker", ShareFixtures.media.copy(picker = SharePicker.Folder), browser)
}
