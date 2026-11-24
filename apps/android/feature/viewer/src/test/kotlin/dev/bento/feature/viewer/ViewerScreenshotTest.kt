package dev.bento.feature.viewer

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import androidx.media3.exoplayer.ExoPlayer
import dev.bento.designsystem.component.BentoSnackbarHostState
import dev.bento.designsystem.theme.BentoMediaTheme
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.photos.LandscapeVariant
import dev.bento.feature.photos.MediaSamples
import dev.bento.feature.photos.MediaTestHarness
import dev.bento.feature.photos.ScreenState
import dev.bento.feature.photos.captureVariants
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

private val sampleInfo = ViewerInfo(
    "p4",
    exif = ExifSummary(
        camera = "Google Pixel 7a",
        lens = "Principal",
        exposure = "1/120 s · ƒ/1,8 · ISO 100 · 4,2 mm",
        latitude = 6.24420,
        longitude = -75.58120
    ),
    folderPath = "/Del teléfono/Pixel de Ana/Cámara",
    albums = MediaSamples.albums.take(2)
)

@Composable
private fun Viewer(page: Int = 3, chrome: ViewerChrome = ViewerChrome()) {
    val context = LocalContext.current
    val harness = remember { MediaTestHarness(context, CoroutineScope(SupervisorJob() + Dispatchers.Main)) }
    BentoMediaTheme(reducedMotion = true) {
        ViewerContent(
            items = ViewerItems.Fixed(MediaSamples.library),
            opening = MediaSamples.library[page],
            initialPage = page,
            expectedCount = MediaSamples.library.size,
            info = sampleInfo,
            actions = harness.actions,
            busy = false,
            snackbar = remember { BentoSnackbarHostState() },
            navigation = ViewerNavigation({}, {}, {}),
            animatedScope = null,
            player = { null },
            video = VideoHooks({}, {}),
            onCurrent = { _, _ -> },
            onLoadInfo = {},
            onOffline = { _, _ -> },
            initialChrome = chrome
        )
    }
}

@RunWith(ParameterizedRobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = "es-w840dp-h1800dp-xhdpi")
class ViewerScreenshotTest(private val state: ScreenState) {
    @get:Rule
    val compose = createComposeRule()

    @org.junit.Before
    fun utc() {
        java.util.TimeZone.setDefault(java.util.TimeZone.getTimeZone("UTC"))
    }

    @Test
    fun capture() = compose.captureVariants(state)

    companion object {
        @JvmStatic
        @ParameterizedRobolectricTestRunner.Parameters(name = "{0}")
        fun states(): List<Array<Any>> = listOf(
            ScreenState("viewer-photo") { Viewer(page = 0) },
            // p4 is 3024 × 4032
            ScreenState("viewer-photo-portrait") { Viewer(page = 3) },
            ScreenState("viewer-photo-immersive") { Viewer(chrome = ViewerChrome(chromeVisible = false)) },
            ScreenState("viewer-video-poster") { Viewer(page = 1) },
            ScreenState("viewer-info-pane") { Viewer(chrome = ViewerChrome(infoOpen = true)) },
            ScreenState("viewer-info-content") {
                BentoTheme(darkTheme = false, reducedMotion = true) {
                    Column(
                        Modifier.fillMaxSize().background(BentoTheme.colors.raised).verticalScroll(rememberScrollState()).padding(16.dp)
                    ) {
                        ViewerInfoContent(MediaSamples.library[3], sampleInfo, InfoCallbacks({}, {}, { _, _ -> }, {}))
                    }
                }
            },
            ScreenState("viewer-info-offline") {
                BentoTheme(darkTheme = false, reducedMotion = true) {
                    Column(
                        Modifier.fillMaxSize().background(BentoTheme.colors.raised).verticalScroll(rememberScrollState()).padding(16.dp)
                    ) {
                        ViewerInfoContent(
                            MediaSamples.library[3].copy(offlinePinned = true, locallyAvailable = true),
                            sampleInfo,
                            InfoCallbacks({}, {}, { _, _ -> }, {})
                        )
                    }
                }
            },
            ScreenState("viewer-video-controls") { VideoControlsSample() }
        ).map { arrayOf<Any>(it) }
    }
}

@Composable
private fun VideoControlsSample() {
    val context = LocalContext.current
    val player = remember { ExoPlayer.Builder(context).build() }
    val playback = PlaybackUi(playing = true, positionMs = 12_000, durationMs = 42_000, muted = false, buffering = false)
    BentoMediaTheme(reducedMotion = true) {
        Box(Modifier.fillMaxSize().background(BentoTheme.colors.black)) {
            TransportButtons(player, playback, Modifier.align(Alignment.Center))
            VideoControls(player, playback, Modifier.align(Alignment.BottomCenter))
        }
    }
}

/** Journey 7 viewer on a phone on its side (`screenshots/<state>/landscape.png`). */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = BentoScreenshots.LANDSCAPE_QUALIFIERS)
class ViewerLandscapeScreenshotTest {
    @get:Rule
    val compose = createComposeRule()

    @org.junit.Before
    fun utc() {
        java.util.TimeZone.setDefault(java.util.TimeZone.getTimeZone("UTC"))
    }

    @Test
    fun photo() = compose.captureVariants(ScreenState("viewer-photo") { Viewer(page = 0) }, listOf(LandscapeVariant))

    @Test
    fun videoControls() = compose.captureVariants(ScreenState("viewer-video-controls") { VideoControlsSample() }, listOf(LandscapeVariant))
}
