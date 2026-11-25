package dev.bento.feature.viewer

import android.graphics.Bitmap
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsFocused
import androidx.compose.ui.test.click
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performKeyInput
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.pressKey
import androidx.compose.ui.test.requestFocus
import androidx.compose.ui.test.swipeLeft
import androidx.exifinterface.media.ExifInterface
import androidx.media3.common.ForwardingPlayer
import androidx.media3.exoplayer.ExoPlayer
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

    @Test
    fun `backend exif summary becomes the info lines`() {
        val es = Locale.forLanguageTag("es")
        val exif = dev.bento.api.generated.ExifSummaryResponse(
            cameraMake = "Google",
            cameraModel = "Pixel 7a",
            lensModel = " ",
            exposureTimeS = 1.0 / 120,
            fNumber = 1.8,
            iso = 100,
            focalLengthMm = 4.2,
            latitude = 6.2442,
            longitude = -75.5812
        )
        val summary = ExifSummary.from(exif, es)!!
        assertEquals("Google Pixel 7a", summary.camera)
        assertNull(summary.lens)
        assertEquals("1/120 s · ƒ/1,8 · ISO 100 · 4,2 mm", summary.exposure)
        assertEquals(true, summary.hasLocation)
        // Half a coordinate is no location; nothing to show is null.
        assertEquals(false, ExifSummary.from(exif.copy(longitude = null), es)!!.hasLocation)
        assertNull(ExifSummary.from(dev.bento.api.generated.ExifSummaryResponse(), es))
    }

    @Test
    fun `availability follows offline_pinned, locally_available and a fresh pin`() {
        val asset = MediaSamples.library.first()
        assertEquals(Availability.NeedsConnection, availabilityOf(asset.copy(offlinePinned = false, locallyAvailable = false)))
        assertEquals(Availability.OnDevice, availabilityOf(asset.copy(offlinePinned = false, locallyAvailable = true)))
        assertEquals(Availability.Pinned, availabilityOf(asset.copy(offlinePinned = true, locallyAvailable = true)))
        assertEquals(Availability.Pinned, availabilityOf(asset.copy(offlinePinned = false), pinned = true))
        assertEquals(Availability.OnDevice, availabilityOf(asset.copy(offlinePinned = true, locallyAvailable = true), pinned = false))
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
        compose.onNodeWithText("El original necesita conexión").assertExists()
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

    private fun toggleAction(page: String, label: String) {
        val node = compose.onNode(
            hasTestTag(ViewerTestTags.page(page)).or(hasAnyAncestor(hasTestTag(ViewerTestTags.page(page))))
                .and(hasCustomAction(label)),
            useUnmergedTree = true
        )
        val action = node.fetchSemanticsNode().config[SemanticsActions.CustomActions].first { it.label == label }
        compose.runOnUiThread { action.action() }
        compose.mainClock.advanceTimeBy(500)
    }

    @Test
    fun `the controls custom action hides and restores the chrome on a photo and on a video (TalkBack, Switch Access)`() {
        compose.setContent { Viewer(harness(), initialPage = 3) }
        await { current.isNotEmpty() }
        toggleAction("p4", "Ocultar controles")
        compose.onNodeWithTag(ViewerTestTags.Actions).assertDoesNotExist()
        toggleAction("p4", "Mostrar controles")
        compose.onNodeWithTag(ViewerTestTags.Actions).assertIsDisplayed()
    }

    @Test
    fun `a video page exposes the same controls toggle`() {
        compose.setContent { Viewer(harness(), initialPage = 1) }
        await { current.isNotEmpty() }
        toggleAction("p2", "Ocultar controles")
        compose.onNodeWithTag(ViewerTestTags.Actions).assertDoesNotExist()
        toggleAction("p2", "Mostrar controles")
        compose.onNodeWithTag(ViewerTestTags.Actions).assertIsDisplayed()
    }
}

private fun hasCustomAction(label: String) = SemanticsMatcher("has custom action \"$label\"") { node ->
    node.config.getOrElseNullable(SemanticsActions.CustomActions) { null }?.any { it.label == label } == true
}

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = "es-w411dp-h891dp-xxhdpi")
class VideoSeekTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun `the scrubber is a focusable progress range, set-progress seeks and arrow keys step 5 s`() {
        val seeks = mutableListOf<Long>()
        var position by mutableLongStateOf(12_000L)
        compose.setContent {
            BentoMediaTheme(reducedMotion = true) {
                Scrubber(positionMs = position, durationMs = 42_000, onSeek = {
                    seeks += it
                    position = it
                })
            }
        }
        val scrubber = compose.onNodeWithTag(ViewerTestTags.Scrubber)
        scrubber.assert(SemanticsMatcher.expectValue(SemanticsProperties.ContentDescription, listOf("Posición de reproducción")))
        scrubber.assert(SemanticsMatcher.expectValue(SemanticsProperties.StateDescription, "0:12 de 0:42"))
        val range = scrubber.fetchSemanticsNode().config[SemanticsProperties.ProgressBarRangeInfo]
        assertEquals(12f / 42f, range.current, 0.001f)
        assertEquals(0f..1f, range.range)
        scrubber.performSemanticsAction(SemanticsActions.SetProgress) { it(0.5f) }
        assertEquals(21_000L, seeks.last())
        scrubber.requestFocus()
        scrubber.assertIsFocused()
        scrubber.performKeyInput { pressKey(Key.DirectionRight) }
        assertEquals(26_000L, seeks.last())
        scrubber.performKeyInput { pressKey(Key.DirectionLeft) }
        scrubber.performKeyInput { pressKey(Key.DirectionLeft) }
        assertEquals(16_000L, seeks.last())
    }

    @Test
    fun `the transport buttons seek 10 s back and forward, clamped to the video`() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val seeks = mutableListOf<Long>()
        val exo = ExoPlayer.Builder(context).build()
        val player = object : ForwardingPlayer(exo) {
            var at = 35_000L
            override fun getCurrentPosition(): Long = at
            override fun seekTo(positionMs: Long) {
                seeks += positionMs
                at = positionMs
            }
        }
        compose.setContent {
            BentoMediaTheme(reducedMotion = true) {
                TransportButtons(
                    player,
                    PlaybackUi(playing = false, positionMs = 35_000, durationMs = 42_000, muted = false, buffering = false)
                )
            }
        }
        compose.onNodeWithContentDescription("Avanzar 10 segundos").performClick()
        assertEquals(42_000L, seeks.last())
        compose.onNodeWithContentDescription("Retroceder 10 segundos").performClick()
        compose.onNodeWithContentDescription("Retroceder 10 segundos").performClick()
        assertEquals(22_000L, seeks.last())
        compose.onNodeWithContentDescription("Reproducir").assertExists()
        exo.release()
    }

    @Test
    fun `seek targets clamp to the duration`() {
        assertEquals(0L, SeekSteps.clamp(-3_000, 42_000))
        assertEquals(42_000L, SeekSteps.clamp(50_000, 42_000))
        assertEquals(50_000L, SeekSteps.clamp(50_000, 0))
    }
}
