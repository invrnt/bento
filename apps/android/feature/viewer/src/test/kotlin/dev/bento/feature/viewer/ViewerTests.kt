package dev.bento.feature.viewer

import android.graphics.Bitmap
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.click
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeLeft
import androidx.exifinterface.media.ExifInterface
import androidx.test.core.app.ApplicationProvider
import dev.bento.designsystem.component.BentoSnackbarHostState
import dev.bento.designsystem.theme.BentoMediaTheme
import dev.bento.feature.photos.LocalBentoImageLoader
import dev.bento.feature.photos.MediaSamples
import dev.bento.feature.photos.MediaTestHarness
import dev.bento.feature.photos.fakeImageLoader
import java.io.File
import java.util.Locale
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowLooper

class ViewerReducerTest {
    private fun ViewerChrome.then(vararg intents: ViewerIntent) = intents.fold(this) { s, i -> ViewerReducer.reduce(s, i) }

    @Test
    fun `tap toggles the chrome, and closes the info first when open`() {
        val start = ViewerChrome()
        assertFalse(start.then(ViewerIntent.Tap).chromeVisible)
        assertTrue(start.then(ViewerIntent.Tap, ViewerIntent.Tap).chromeVisible)
        val info = start.then(ViewerIntent.SwipeUp)
        assertTrue(info.infoOpen)
        assertFalse(info.then(ViewerIntent.Tap).infoOpen)
        assertTrue("tap with info open keeps the chrome", info.then(ViewerIntent.Tap).chromeVisible)
    }

    @Test
    fun `zoom hides the chrome, locks paging and vertical gestures, a page change resets it`() {
        val zoomed = ViewerChrome().then(ViewerIntent.Zoom(true))
        assertFalse(zoomed.chromeVisible)
        assertFalse(zoomed.pagingEnabled)
        assertFalse(zoomed.verticalGesturesEnabled)
        assertFalse("swipe up does nothing while zoomed", zoomed.then(ViewerIntent.SwipeUp).infoOpen)
        val next = zoomed.then(ViewerIntent.PageChanged)
        assertTrue(next.pagingEnabled)
    }

    @Test
    fun `swipe-down dismiss commits past the threshold or on a fling, otherwise springs back`() {
        val dragging = ViewerChrome().then(ViewerIntent.DismissDrag(0.1f))
        assertFalse(dragging.pagingEnabled)
        assertEquals(0f, dragging.then(ViewerIntent.DismissRelease(commit = false)).dismissProgress)
        assertTrue(dragging.then(ViewerIntent.DismissRelease(commit = true)).dismissed)
        assertFalse(ViewerReducer.shouldCommitDismiss(0.1f, 200f))
        assertTrue(ViewerReducer.shouldCommitDismiss(0.25f, 0f))
        assertTrue(ViewerReducer.shouldCommitDismiss(0.05f, 2_000f))
        assertEquals(1f, ViewerChrome().then(ViewerIntent.DismissDrag(3f)).dismissProgress)
    }

    @Test
    fun `progressive quality never goes backwards and the original is skipped above 40 MP`() {
        assertEquals(ImageStage.Thumbnail, ProgressiveQuality.stage(previewLoaded = false, originalLoaded = false))
        assertEquals(ImageStage.Preview, ProgressiveQuality.stage(previewLoaded = true, originalLoaded = false))
        assertEquals(ImageStage.Original, ProgressiveQuality.stage(previewLoaded = false, originalLoaded = true))
        assertTrue(ProgressiveQuality.wantsOriginal(8000, 5000, "image/jpeg"))
        assertFalse(ProgressiveQuality.wantsOriginal(9000, 6000, "image/jpeg"))
        assertTrue(ProgressiveQuality.wantsOriginal(null, null, "image/heic"))
        assertFalse(ProgressiveQuality.wantsOriginal(100, 100, "image/gif"))
        assertFalse(ProgressiveQuality.wantsOriginal(100, 100, "video/mp4"))
        assertTrue(ProgressiveQuality.offline(originalFailed = true, networkError = true, stage = ImageStage.Preview))
        assertFalse(ProgressiveQuality.offline(originalFailed = true, networkError = false, stage = ImageStage.Preview))
    }

    @Test
    fun `exposure, camera and storage lines`() {
        val es = Locale.forLanguageTag("es")
        assertEquals("1/120 s · ƒ/1,8 · ISO 100 · 4,2 mm", ExifSummary.exposureLine(1.0 / 120, 1.8, 100, 4.2, es))
        assertEquals("2 s · ƒ/8", ExifSummary.exposureLine(2.0, 8.0, null, null, es))
        assertNull(ExifSummary.exposureLine(null, null, null, null, es))
        assertEquals("Google Pixel 7a", ExifSummary.cameraLine("Google", "Pixel 7a"))
        assertEquals("Canon EOS R6", ExifSummary.cameraLine("Canon", "Canon EOS R6"))
        assertNull(ExifSummary.cameraLine(" ", null))
        assertEquals(StorageLine.LocalOnly, storageLine("local_only"))
        assertEquals(StorageLine.Remote, storageLine(null))
        assertEquals(StorageLine.Failed, storageLine("failed"))
    }
}

@RunWith(RobolectricTestRunner::class)
class ExifReaderTest {
    @Test
    fun `reads camera, exposure and GPS from a JPEG header`() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val file = File(context.cacheDir, "exif.jpg")
        Bitmap.createBitmap(32, 24, Bitmap.Config.ARGB_8888).compress(Bitmap.CompressFormat.JPEG, 90, file.outputStream())
        ExifInterface(file).apply {
            setAttribute(ExifInterface.TAG_MAKE, "Google")
            setAttribute(ExifInterface.TAG_MODEL, "Pixel 7a")
            setAttribute(ExifInterface.TAG_EXPOSURE_TIME, "0.008")
            setAttribute(ExifInterface.TAG_F_NUMBER, "1.9")
            setAttribute(ExifInterface.TAG_PHOTOGRAPHIC_SENSITIVITY, "200")
            setLatLong(6.2442, -75.5812)
            saveAttributes()
        }
        val summary = file.inputStream().use { ExifReader.parse(it, Locale.ENGLISH) }
        assertEquals("Google Pixel 7a", summary.camera)
        assertEquals("1/125 s · ƒ/1.9 · ISO 200", summary.exposure)
        assertEquals(6.2442, summary.latitude!!, 0.0001)
        assertEquals(-75.5812, summary.longitude!!, 0.0001)
    }
}

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = "es-w411dp-h891dp-xxhdpi")
class ViewerContentTest {
    @get:Rule
    val compose = createComposeRule()

    private val current = mutableListOf<String>()
    private var backs = 0

    private fun await(condition: () -> Boolean) {
        var waited = 0
        while (!condition()) {
            check(waited < 3_000) { "condition not met" }
            compose.mainClock.advanceTimeBy(50)
            ShadowLooper.idleMainLooper()
            waited += 50
        }
    }

    @Composable
    private fun Viewer(harness: MediaTestHarness, initialPage: Int = 0) {
        CompositionLocalProvider(LocalBentoImageLoader provides remember { fakeImageLoader(ApplicationProvider.getApplicationContext()) }) {
            BentoMediaTheme(reducedMotion = true) {
                ViewerContent(
                    items = ViewerItems.Fixed(MediaSamples.library),
                    opening = MediaSamples.library[initialPage],
                    initialPage = initialPage,
                    expectedCount = MediaSamples.library.size,
                    info = ViewerInfo(
                        MediaSamples.library[initialPage].id,
                        exif = ExifSummary(
                            camera = "Google Pixel 7a",
                            exposure = "1/120 s · ƒ/1,8 · ISO 100",
                            latitude = 6.2442,
                            longitude = -75.5812
                        ),
                        folderPath = "/Fotos/Cámara",
                        albums = MediaSamples.albums.take(1)
                    ),
                    actions = harness.actions,
                    busy = false,
                    snackbar = remember { BentoSnackbarHostState() },
                    navigation = ViewerNavigation(back = { backs++ }, openFolder = {}, openActivity = {}),
                    animatedScope = null,
                    player = { null },
                    video = VideoHooks({}, {}),
                    onCurrent = { asset, _ -> current += asset.id },
                    onLoadInfo = {},
                    onOffline = { _, _ -> }
                )
            }
        }
    }

    private fun harness() = MediaTestHarness(
        ApplicationProvider.getApplicationContext(),
        CoroutineScope(SupervisorJob() + Dispatchers.Main)
    )

    @Test
    fun `opens on the tapped photo, swipes to the next, and a tap hides the chrome`() {
        compose.setContent { Viewer(harness(), initialPage = 3) }
        await { current.isNotEmpty() }
        assertEquals("p4", current.last())
        compose.onNodeWithTag(ViewerTestTags.Chrome).assertIsDisplayed()
        compose.onNodeWithTag(ViewerTestTags.Pager).performTouchInput { swipeLeft() }
        await { current.last() == "p5" }
        compose.onNodeWithTag(ViewerTestTags.page("p5")).performTouchInput { click(center) }
        await { compose.onAllNodesWithText("IMG_p5.jpg").fetchSemanticsNodes().isEmpty() }
        compose.onNodeWithTag(ViewerTestTags.Actions).assertDoesNotExist()
    }

    @Test
    fun `Detalles opens the info with EXIF, location, folder, albums and storage`() {
        compose.setContent { Viewer(harness()) }
        compose.onNodeWithContentDescription("Más opciones").performClick()
        compose.onNodeWithText("Detalles").performClick()
        await { compose.onAllNodesWithText("Google Pixel 7a").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("Abrir en Mapas").assertExists()
        compose.onNodeWithText("/Fotos/Cámara").assertExists()
        compose.onNodeWithText("Viaje a Cartagena").assertExists()
        compose.onNodeWithText("En tu nube · cifrado").assertExists()
    }

    @Test
    fun `delete moves to the trash with Deshacer and favorite is a toggle`() {
        val harness = harness()
        compose.setContent { Viewer(harness) }
        compose.onNodeWithContentDescription("Añadir a favoritos").performClick()
        await { harness.transport.count("POST /api/photos/p1/favorite") == 1 }
        compose.onNodeWithContentDescription("Eliminar").performClick()
        await { compose.onAllNodesWithText("Deshacer").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("Se movió a la papelera").assertExists()
        compose.onNodeWithText("Deshacer").performClick()
        await { harness.transport.count("POST /api/trash/restore") == 1 }
    }
}
