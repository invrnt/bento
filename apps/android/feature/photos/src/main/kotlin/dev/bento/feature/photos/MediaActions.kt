package dev.bento.feature.photos

import android.content.Intent
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import dev.bento.api.ApiException
import dev.bento.api.generated.AssetResponse
import dev.bento.api.generated.TelegramChatResponse
import dev.bento.data.AlbumsRepository
import dev.bento.data.DriveRepository
import dev.bento.data.TelegramMediaRepository
import dev.bento.data.TimelineRepository
import dev.bento.data.Undoable
import dev.bento.strings.R as StringsR
import java.io.IOException
import javax.inject.Inject
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

/** A string to resolve in the UI (resources stay out of view models). */
@Immutable
data class UiText(val res: Int, val args: List<Any> = emptyList(), val plural: Boolean = false, val quantity: Int = 0) {
    @Composable
    fun resolve(): String = if (plural) {
        pluralStringResource(res, quantity, *args.toTypedArray())
    } else {
        stringResource(res, *args.toTypedArray())
    }

    fun resolve(context: android.content.Context): String =
        if (plural) context.resources.getQuantityString(res, quantity, *args.toTypedArray()) else context.getString(res, *args.toTypedArray())
}

/** One-off UI effects of media actions. */
sealed interface MediaEvent {
    /** Snackbar with `Deshacer` for 6 s (product/android.md §1.5). */
    data class Undo(val message: UiText, val undo: Undoable) : MediaEvent

    data class Message(val message: UiText) : MediaEvent

    /** System chooser for share / open with / use as. */
    data class Launch(val intent: Intent, val chooserTitle: Int) : MediaEvent

    /** The trashed items left the current screen (the viewer moves on). */
    data class Trashed(val ids: List<String>) : MediaEvent

    /** Show the plaintext disclosure for [kind]; then [MediaActions.confirmDisclosure] or [MediaActions.cancelDisclosure]. */
    data class Disclose(val kind: Disclosure) : MediaEvent
}

/** Plaintext disclosure kinds (shown the first time per kind; Telegram always shows its line in the chat sheet). */
enum class Disclosure(val body: Int) {
    Share(StringsR.string.common_plaintext_share),
    OpenWith(StringsR.string.common_plaintext_open_with),
    SaveToPhone(StringsR.string.common_plaintext_save_to_phone)
}

/**
 * The media actions shared by Fotos, the viewer and Colecciones: optimistic favorites and trash with undo, albums,
 * moves, plaintext exports and Telegram sends. One instance per view model ([bind] gives it the VM scope).
 */
class MediaActions @Inject constructor(
    private val timeline: TimelineRepository,
    private val albums: AlbumsRepository,
    private val drive: DriveRepository,
    private val telegram: TelegramMediaRepository,
    private val exporter: MediaExporter,
    private val prefs: MediaPreferences
) {
    private var pendingExport: (() -> Unit)? = null
    private lateinit var scope: CoroutineScope
    private val _events = Channel<MediaEvent>(Channel.BUFFERED)
    val events: Flow<MediaEvent> = _events.receiveAsFlow()
    private val _busy = MutableStateFlow(false)

    /** True while a decrypted copy is being prepared (the UI shows "Preparando una copia…"). */
    val busy: StateFlow<Boolean> = _busy.asStateFlow()

    fun bind(scope: CoroutineScope): MediaActions = apply { this.scope = scope }

    fun favorite(assets: List<AssetResponse>, favorite: Boolean) = run {
        val undo = timeline.setFavorite(assets, favorite)
        if (assets.size > 1) {
            send(MediaEvent.Undo(UiText(if (favorite) StringsR.string.photos_favorites_added else StringsR.string.photos_favorites_removed), undo))
        }
    }

    fun trash(ids: List<String>) = run {
        val undo = if (ids.size == 1) timeline.trash(ids.single()) else timeline.trash(ids)
        send(MediaEvent.Trashed(ids))
        val message = if (ids.size == 1) {
            UiText(StringsR.string.photos_trashed_one)
        } else {
            UiText(StringsR.plurals.photos_trashed_many, listOf(ids.size), plural = true, quantity = ids.size)
        }
        send(MediaEvent.Undo(message, undo))
    }

    fun addToAlbum(albumId: String, title: String, ids: List<String>) = run {
        send(MediaEvent.Undo(UiText(StringsR.string.photos_added_to_album, listOf(title)), albums.addAll(albumId, ids)))
    }

    fun createAlbum(title: String, ids: List<String>) = run {
        val album = albums.createWith(title, ids)
        send(MediaEvent.Message(UiText(StringsR.string.photos_added_to_album, listOf(album.title))))
    }

    fun move(assets: List<AssetResponse>, folderId: String?, folderName: String) = run {
        val undos = assets.map { drive.move(it.id, folderId, it.folderId) }
        val combined = undos.singleOrNull() ?: dev.bento.data.optimistic({}, {}, {}, { undos.forEach { it.undo() } })
        send(MediaEvent.Undo(UiText(StringsR.string.photos_moved_to_folder, listOf(folderName)), combined))
    }

    fun rename(asset: AssetResponse, name: String) = run {
        timeline.rename(asset, name)
    }

    /** Runs [action] after the plaintext disclosure for [kind] (skipped when the person chose not to see it again). */
    fun export(kind: Disclosure, action: () -> Unit) {
        scope.launch {
            if (prefs.disclosureHidden(kind)) {
                action()
            } else {
                pendingExport = action
                send(MediaEvent.Disclose(kind))
            }
        }
    }

    fun confirmDisclosure(kind: Disclosure, hideNextTime: Boolean) {
        val action = pendingExport ?: return
        pendingExport = null
        scope.launch {
            if (hideNextTime) prefs.hideDisclosure(kind)
            action()
        }
    }

    fun cancelDisclosure() {
        pendingExport = null
    }

    fun share(assets: List<AssetResponse>) = runBusy {
        val uris = assets.map { exporter.temporaryCopy(it) }
        send(MediaEvent.Launch(exporter.shareIntent(uris, assets.map { it.mimeType }), StringsR.string.viewer_chooser_share))
    }

    fun openWith(asset: AssetResponse) = runBusy {
        send(MediaEvent.Launch(exporter.viewIntent(exporter.temporaryCopy(asset), asset.mimeType), StringsR.string.viewer_chooser_open_with))
    }

    fun useAs(asset: AssetResponse) = runBusy {
        send(MediaEvent.Launch(exporter.attachIntent(exporter.temporaryCopy(asset), asset.mimeType), StringsR.string.viewer_chooser_use_as))
    }

    fun saveToPhone(assets: List<AssetResponse>) = runBusy {
        assets.forEach { exporter.saveToPhone(it) }
        send(MediaEvent.Message(UiText(StringsR.string.photos_saved_to_phone)))
    }

    fun sendTelegram(assets: List<AssetResponse>, chat: TelegramChatResponse) = runBusy {
        assets.forEach { telegram.send(it.id, chat.id) }
        send(MediaEvent.Message(UiText(StringsR.string.photos_sent_telegram, listOf(chat.title))))
    }

    private fun send(event: MediaEvent) {
        _events.trySend(event)
    }

    private fun run(block: suspend () -> Unit) {
        scope.launch {
            try {
                block()
            } catch (error: ApiException) {
                send(MediaEvent.Message(UiText(StringsR.string.photos_action_failed)))
            }
        }
    }

    private fun runBusy(block: suspend () -> Unit) {
        scope.launch {
            _busy.value = true
            try {
                block()
            } catch (error: ApiException) {
                send(MediaEvent.Message(UiText(StringsR.string.photos_action_failed)))
            } catch (error: IOException) {
                send(MediaEvent.Message(UiText(StringsR.string.photos_action_failed)))
            } catch (error: IllegalStateException) {
                send(MediaEvent.Message(UiText(StringsR.string.photos_action_failed)))
            } finally {
                _busy.value = false
            }
        }
    }
}

/** Starts a chooser for a [MediaEvent.Launch] (the plaintext disclosure was already shown). */
@Composable
fun rememberLauncher(): (MediaEvent.Launch) -> Unit {
    val context = LocalContext.current
    return { event ->
        val title = context.getString(event.chooserTitle)
        runCatching { context.startActivity(Intent.createChooser(event.intent, title).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
    }
}
