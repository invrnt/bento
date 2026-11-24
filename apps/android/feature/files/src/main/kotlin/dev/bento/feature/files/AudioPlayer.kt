package dev.bento.feature.files

import android.content.Context
import androidx.annotation.OptIn
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import dev.bento.api.BentoMediaUris
import dev.bento.api.bentoDataSourceFactory
import dev.bento.engine.BentoEngine
import dev.bento.engine.EngineState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import okhttp3.OkHttpClient

/** What the audio mini player shows. */
data class AudioState(
    val assetId: String? = null,
    val title: String = "",
    val playing: Boolean = false,
    val buffering: Boolean = false,
    val positionMs: Long = 0,
    val durationMs: Long = 0,
    val failed: Boolean = false
) {
    val visible: Boolean get() = assetId != null
}

/** Audio control surface (the mini player and tests use this; [AudioPlayer] is the Media3 implementation). */
interface AudioControls {
    val state: StateFlow<AudioState>

    fun play(assetId: String, title: String)

    fun toggle()

    fun seekTo(positionMs: Long)

    /** Refreshes the position (the mini player calls it while visible). */
    fun tick()

    fun close()
}

/**
 * Audio files play in a mini player above the navigation bar (product/android.md §4.5), streamed from the local
 * `/content` route through Media3 (Range requests, so remote files seek without a full download). Main thread only.
 */
class AudioPlayer(
    private val context: Context,
    private val client: OkHttpClient,
    private val engine: BentoEngine
) : AudioControls {
    private val _state = MutableStateFlow(AudioState())
    override val state: StateFlow<AudioState> = _state.asStateFlow()
    private var player: ExoPlayer? = null

    @OptIn(UnstableApi::class)
    private fun player(): ExoPlayer = player ?: ExoPlayer.Builder(context)
        .setMediaSourceFactory(DefaultMediaSourceFactory(bentoDataSourceFactory(client) { engine.state.value as? EngineState.Ready }))
        .build()
        .also { created ->
            created.addListener(object : Player.Listener {
                override fun onIsPlayingChanged(isPlaying: Boolean) = _state.update { it.copy(playing = isPlaying) }

                override fun onPlaybackStateChanged(playbackState: Int) {
                    _state.update {
                        it.copy(buffering = playbackState == Player.STATE_BUFFERING, durationMs = created.duration.coerceAtLeast(0))
                    }
                }

                override fun onPlayerError(error: androidx.media3.common.PlaybackException) = _state.update {
                    it.copy(failed = true, playing = false)
                }
            })
            player = created
        }

    override fun play(assetId: String, title: String) {
        val exo = player()
        _state.value = AudioState(assetId = assetId, title = title, buffering = true)
        exo.setMediaItem(MediaItem.fromUri(BentoMediaUris.asset(assetId)))
        exo.prepare()
        exo.play()
    }

    override fun toggle() {
        val exo = player ?: return
        if (exo.isPlaying) exo.pause() else exo.play()
    }

    override fun seekTo(positionMs: Long) {
        player?.seekTo(positionMs)
        tick()
    }

    override fun tick() {
        val exo = player ?: return
        _state.update { it.copy(positionMs = exo.currentPosition.coerceAtLeast(0), durationMs = exo.duration.coerceAtLeast(0)) }
    }

    override fun close() {
        player?.release()
        player = null
        _state.value = AudioState()
    }
}
