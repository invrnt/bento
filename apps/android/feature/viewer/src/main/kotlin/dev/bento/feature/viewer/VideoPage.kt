package dev.bento.feature.viewer

import android.app.PictureInPictureParams
import android.os.Build
import android.util.Rational
import androidx.activity.ComponentActivity
import androidx.activity.compose.LocalActivity
import androidx.annotation.OptIn
import androidx.compose.foundation.background
import androidx.compose.foundation.focusable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.setProgress
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.unit.dp
import androidx.core.app.PictureInPictureModeChangedInfo
import androidx.core.util.Consumer
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.ui.compose.PlayerSurface
import androidx.media3.ui.compose.SURFACE_TYPE_SURFACE_VIEW
import androidx.media3.ui.compose.state.rememberPresentationState
import androidx.window.layout.FoldingFeature
import androidx.window.layout.WindowInfoTracker
import dev.bento.designsystem.component.BentoIconButton
import dev.bento.designsystem.component.BentoIconButtonVariant
import dev.bento.designsystem.component.bentoFocusRing
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.photos.MediaFormat
import dev.bento.strings.R as StringsR
import kotlinx.coroutines.delay

object ViewerTestTags {
    const val Pager = "viewer:pager"
    const val Chrome = "viewer:chrome"
    const val Actions = "viewer:actions"
    const val Info = "viewer:info"
    const val Offline = "viewer:offline"
    const val VideoControls = "viewer:video-controls"
    const val Scrubber = "viewer:scrubber"
    fun page(id: String) = "viewer:page:$id"
}

/** Playback state polled from the player (position 4×/s while playing; Media3 has no position callback). */
class PlaybackUi(val playing: Boolean, val positionMs: Long, val durationMs: Long, val muted: Boolean, val buffering: Boolean)

@Composable
fun rememberPlaybackUi(player: Player): PlaybackUi {
    var playing by remember { mutableStateOf(player.isPlaying) }
    var position by remember { mutableLongStateOf(player.currentPosition) }
    var duration by remember { mutableLongStateOf(player.duration.coerceAtLeast(0)) }
    var muted by remember { mutableStateOf(player.volume == 0f) }
    var buffering by remember { mutableStateOf(player.playbackState == Player.STATE_BUFFERING) }
    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onEvents(player: Player, events: Player.Events) {
                playing = player.isPlaying
                duration = player.duration.coerceAtLeast(0)
                muted = player.volume == 0f
                buffering = player.playbackState == Player.STATE_BUFFERING
                position = player.currentPosition
            }
        }
        player.addListener(listener)
        onDispose { player.removeListener(listener) }
    }
    LaunchedEffect(player, playing) {
        while (playing) {
            position = player.currentPosition
            delay(250)
        }
    }
    return PlaybackUi(playing, position, duration, muted, buffering)
}

/** True while the activity is in picture-in-picture (only the video is drawn then). */
@Composable
fun rememberInPictureInPicture(): Boolean {
    val activity = LocalActivity.current as? ComponentActivity ?: return false
    var pip by remember { mutableStateOf(activity.isInPictureInPictureMode) }
    DisposableEffect(activity) {
        val listener = Consumer<PictureInPictureModeChangedInfo> { pip = it.isInPictureInPictureMode }
        activity.addOnPictureInPictureModeChangedListener(listener)
        onDispose { activity.removeOnPictureInPictureModeChangedListener(listener) }
    }
    return pip
}

/** Leaving the app during playback enters PiP (auto-enter on 12+, user-leave hint before). */
@Composable
fun PictureInPictureOnLeave(enabled: Boolean, aspect: Float) {
    val activity = LocalActivity.current as? ComponentActivity ?: return
    val supported =
        remember(activity) { activity.packageManager.hasSystemFeature(android.content.pm.PackageManager.FEATURE_PICTURE_IN_PICTURE) }
    if (!supported) return
    val ratio = remember(aspect) { Rational((aspect.coerceIn(0.42f, 2.38f) * 1000).toInt(), 1000) }
    val current by rememberUpdatedState(enabled)
    DisposableEffect(activity, enabled, ratio) {
        val params = PictureInPictureParams.Builder().setAspectRatio(ratio).apply {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) setAutoEnterEnabled(enabled).setSeamlessResizeEnabled(true)
        }.build()
        runCatching { activity.setPictureInPictureParams(params) }
        val leave = Runnable {
            if (current &&
                Build.VERSION.SDK_INT < Build.VERSION_CODES.S
            ) {
                runCatching { activity.enterPictureInPictureMode(params) }
            }
        }
        activity.addOnUserLeaveHintListener(leave)
        onDispose {
            activity.removeOnUserLeaveHintListener(leave)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                runCatching { activity.setPictureInPictureParams(PictureInPictureParams.Builder().setAutoEnterEnabled(false).build()) }
            }
        }
    }
}

/** Foldable half-opened with a horizontal hinge: video in the upper half, controls in the lower (product/android.md §4.6). */
@Composable
fun rememberTabletopFold(): FoldingFeature? {
    val activity = LocalActivity.current ?: return null
    var fold by remember { mutableStateOf<FoldingFeature?>(null) }
    LaunchedEffect(activity) {
        WindowInfoTracker.getOrCreate(activity).windowLayoutInfo(activity).collect { info ->
            fold = info.displayFeatures.filterIsInstance<FoldingFeature>().firstOrNull {
                it.state == FoldingFeature.State.HALF_OPENED && it.orientation == FoldingFeature.Orientation.HORIZONTAL
            }
        }
    }
    return fold
}

/**
 * A video page: the thumbnail stays until the first frame is rendered (no black flash), tap (or the custom action)
 * toggles the controls, ±10 s buttons and the scrubber seek (TalkBack can set it, arrow keys step it), mute toggle, PiP when leaving during playback, tabletop split.
 */
@OptIn(UnstableApi::class)
@Suppress("LongMethod", "LongParameterList")
@Composable
fun VideoPage(
    player: Player?,
    active: Boolean,
    aspect: Float,
    controlsVisible: Boolean,
    contentDescription: String,
    onTap: () -> Unit,
    poster: @Composable () -> Unit,
    modifier: Modifier = Modifier
) {
    val pip = rememberInPictureInPicture()
    val fold = rememberTabletopFold()
    val toggleLabel = controlsToggleLabel(controlsVisible)
    val tap by rememberUpdatedState(onTap)
    val pageSemantics = Modifier.semantics {
        this.contentDescription = contentDescription
        customActions = listOf(CustomAccessibilityAction(toggleLabel) { tap(); true })
    }
    if (player == null || !active) {
        Box(modifier.fillMaxSize().then(pageSemantics), contentAlignment = Alignment.Center) { poster() }
        return
    }
    val presentation = rememberPresentationState(player)
    val playback = rememberPlaybackUi(player)
    PictureInPictureOnLeave(enabled = playback.playing, aspect = aspect)

    val surface: @Composable (Modifier) -> Unit = { m ->
        Box(m, contentAlignment = Alignment.Center) {
            Box(Modifier.aspectRatio(aspect.coerceAtLeast(0.1f)), contentAlignment = Alignment.Center) {
                PlayerSurface(player, Modifier.fillMaxSize(), SURFACE_TYPE_SURFACE_VIEW)
                if (presentation.coverSurface) poster()
            }
        }
    }
    if (pip) {
        surface(modifier.fillMaxSize())
        return
    }
    Box(modifier.fillMaxSize().pointerInput(Unit) { detectTapGestures(onTap = { tap() }) }.then(pageSemantics)) {
        val split = fold?.bounds?.top?.takeIf { it > 0 }
        if (split != null) {
            Column(Modifier.fillMaxSize()) {
                surface(Modifier.fillMaxWidth().height(with(androidx.compose.ui.platform.LocalDensity.current) { split.toDp() }))
                Column(Modifier.fillMaxWidth().weight(1f), verticalArrangement = Arrangement.Center) {
                    TransportButtons(player, playback, Modifier.align(Alignment.CenterHorizontally))
                    VideoControls(player, playback, Modifier.fillMaxWidth())
                }
            }
        } else {
            surface(Modifier.fillMaxSize())
            if (controlsVisible) {
                TransportButtons(player, playback, Modifier.align(Alignment.Center))
                VideoControls(player, playback, Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(bottom = 88.dp))
            }
        }
    }
}

/** The "Mostrar/Ocultar controles" custom action label: the non-gesture way to toggle the chrome (TalkBack, Switch Access). */
@Composable
internal fun controlsToggleLabel(visible: Boolean): String =
    stringResource(if (visible) StringsR.string.viewer_controls_hide else StringsR.string.viewer_controls_show)

/** Seek steps: ±10 s for the transport buttons, ±5 s for arrow keys on the focused scrubber. */
internal object SeekSteps {
    const val BUTTON_MS = 10_000L
    const val KEY_MS = 5_000L

    fun clamp(target: Long, durationMs: Long): Long = if (durationMs > 0) target.coerceIn(0L, durationMs) else target.coerceAtLeast(0L)
}

/** −10 s · play/pause · +10 s: the button path for seeking (keyboard, Switch Access). */
@Composable
internal fun TransportButtons(player: Player, playback: PlaybackUi, modifier: Modifier = Modifier) {
    val seekBy: (Long) -> Unit = { delta -> player.seekTo(SeekSteps.clamp(player.currentPosition + delta, playback.durationMs)) }
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(24.dp), verticalAlignment = Alignment.CenterVertically) {
        BentoIconButton(
            icon = BentoIcons.RotateCcw,
            contentDescription = stringResource(StringsR.string.viewer_seek_back),
            onClick = { seekBy(-SeekSteps.BUTTON_MS) },
            variant = BentoIconButtonVariant.Overlay
        )
        BentoIconButton(
            icon = if (playback.playing) BentoIcons.Pause else BentoIcons.Play,
            contentDescription = stringResource(if (playback.playing) StringsR.string.viewer_pause else StringsR.string.viewer_play),
            onClick = { if (player.isPlaying) player.pause() else player.play() },
            variant = BentoIconButtonVariant.Overlay
        )
        BentoIconButton(
            icon = BentoIcons.RotateCw,
            contentDescription = stringResource(StringsR.string.viewer_seek_forward),
            onClick = { seekBy(SeekSteps.BUTTON_MS) },
            variant = BentoIconButtonVariant.Overlay
        )
    }
}

/** Time · scrubber · duration · mute · PiP. */
@Composable
fun VideoControls(player: Player, playback: PlaybackUi, modifier: Modifier = Modifier) {
    val c = BentoTheme.colors
    val activity = LocalActivity.current as? ComponentActivity
    val context = LocalContext.current
    val pipSupported =
        remember(context) { context.packageManager.hasSystemFeature(android.content.pm.PackageManager.FEATURE_PICTURE_IN_PICTURE) }
    Row(
        modifier.padding(horizontal = 12.dp).heightIn(min = 48.dp).testTag(ViewerTestTags.VideoControls),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Text(
            MediaFormat.duration(playback.positionMs),
            color = c.white,
            style = BentoTheme.typography.metadata.copy(fontFeatureSettings = "tnum")
        )
        Scrubber(
            positionMs = playback.positionMs,
            durationMs = playback.durationMs,
            onSeek = { player.seekTo(it) },
            modifier = Modifier.weight(1f)
        )
        Text(
            MediaFormat.duration(playback.durationMs),
            color = c.white,
            style = BentoTheme.typography.metadata.copy(fontFeatureSettings = "tnum")
        )
        BentoIconButton(
            icon = if (playback.muted) BentoIcons.VolumeX else BentoIcons.Volume2,
            contentDescription = stringResource(if (playback.muted) StringsR.string.viewer_unmute else StringsR.string.viewer_mute),
            onClick = { player.volume = if (player.volume == 0f) 1f else 0f },
            variant = BentoIconButtonVariant.Overlay,
            dense = true
        )
        if (pipSupported && activity != null) {
            BentoIconButton(
                icon = BentoIcons.PictureInPicture2,
                contentDescription = stringResource(StringsR.string.viewer_pip),
                onClick = { runCatching { activity.enterPictureInPictureMode(PictureInPictureParams.Builder().build()) } },
                variant = BentoIconButtonVariant.Overlay,
                dense = true
            )
        }
    }
}

/** Seek bar built from tokens (no Material slider colors): drag to scrub; adjustable for TalkBack. */
@Composable
fun Scrubber(positionMs: Long, durationMs: Long, onSeek: (Long) -> Unit, modifier: Modifier = Modifier) {
    val c = BentoTheme.colors
    var dragging by remember { mutableStateOf(false) }
    var dragFraction by remember { mutableFloatStateOf(0f) }
    val fraction = if (dragging) {
        dragFraction
    } else if (durationMs > 0) {
        (positionMs.toFloat() / durationMs).coerceIn(0f, 1f)
    } else {
        0f
    }
    val label = stringResource(StringsR.string.viewer_seek)
    val state = stringResource(StringsR.string.viewer_position, MediaFormat.duration(positionMs), MediaFormat.duration(durationMs))
    val updatedSeek by rememberUpdatedState(onSeek)
    val interaction = remember { MutableInteractionSource() }
    BoxWithConstraints(
        modifier
            .heightIn(min = 48.dp)
            .testTag(ViewerTestTags.Scrubber)
            .bentoFocusRing(interaction, BentoShapes.full)
            .onKeyEvent { event ->
                val delta = when (event.key) {
                    Key.DirectionLeft -> -SeekSteps.KEY_MS
                    Key.DirectionRight -> SeekSteps.KEY_MS
                    else -> return@onKeyEvent false
                }
                if (event.type == KeyEventType.KeyDown && durationMs > 0) updatedSeek(SeekSteps.clamp(positionMs + delta, durationMs))
                true
            }
            .focusable(interactionSource = interaction)
            .semantics {
                contentDescription = label
                stateDescription = state
                progressBarRangeInfo = ProgressBarRangeInfo(fraction, 0f..1f)
                setProgress { value ->
                    updatedSeek((value.coerceIn(0f, 1f) * durationMs).toLong())
                    true
                }
            }
            .pointerInput(durationMs) {
                detectTapGestures { offset -> if (durationMs > 0) updatedSeek((offset.x / size.width * durationMs).toLong()) }
            }
            .pointerInput(durationMs) {
                detectHorizontalDragGestures(
                    onDragStart = { offset ->
                        dragging = true
                        dragFraction = (offset.x / size.width).coerceIn(0f, 1f)
                    },
                    onHorizontalDrag = { change, _ -> dragFraction = (change.position.x / size.width).coerceIn(0f, 1f) },
                    onDragEnd = {
                        dragging = false
                        if (durationMs > 0) updatedSeek((dragFraction * durationMs).toLong())
                    },
                    onDragCancel = { dragging = false }
                )
            },
        contentAlignment = Alignment.CenterStart
    ) {
        Box(Modifier.fillMaxWidth().height(4.dp).clip(BentoShapes.full).background(c.white.copy(alpha = 0.3f)))
        Box(Modifier.fillMaxWidth(fraction).height(4.dp).clip(BentoShapes.full).background(c.white))
        Box(
            Modifier
                .padding(start = (maxWidth - 14.dp) * fraction)
                .height(if (dragging) 18.dp else 14.dp)
                .aspectRatio(1f)
                .clip(BentoShapes.full)
                .background(c.white)
        )
    }
}
