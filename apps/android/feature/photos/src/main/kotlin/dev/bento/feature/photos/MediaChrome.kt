package dev.bento.feature.photos

import android.util.Log
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.metrics.performance.JankStats
import androidx.metrics.performance.PerformanceMetricsState
import dev.bento.api.generated.AssetResponse
import dev.bento.designsystem.component.BentoIconButton
import dev.bento.designsystem.component.BentoSnackbarHostState
import dev.bento.designsystem.component.FloatingAction
import dev.bento.designsystem.format.pluralCountResource
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.strings.R as StringsR
import kotlinx.coroutines.launch

/** Selection top bar: close, "12 seleccionados", select all (product/android.md §4.3). */
@Composable
fun SelectionTopBar(count: Int, onClose: () -> Unit, onSelectAll: (() -> Unit)?, modifier: Modifier = Modifier) {
    val c = BentoTheme.colors
    Row(
        modifier
            .fillMaxWidth()
            .background(c.surface)
            .windowInsetsPadding(WindowInsets.statusBars)
            .heightIn(min = 64.dp)
            .padding(horizontal = 4.dp)
            .testTag(MediaTestTags.SelectionBar),
        verticalAlignment = Alignment.CenterVertically
    ) {
        BentoIconButton(BentoIcons.X, stringResource(StringsR.string.ds_clear_selection), onClose)
        // One line, never hyphenated: select-all is an icon so the count keeps the room at 200 % font.
        Text(
            pluralCountResource(StringsR.plurals.common_count_selected, count),
            color = c.ink,
            style = BentoTheme.typography.sectionTitle.copy(fontFeatureSettings = "tnum"),
            maxLines = 1,
            softWrap = false,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f).padding(start = 4.dp).semantics { liveRegion = LiveRegionMode.Polite }
        )
        if (onSelectAll != null) {
            BentoIconButton(BentoIcons.Check, stringResource(StringsR.string.common_action_select_all), onSelectAll)
        }
    }
}

/** What the floating action bar can do with the current selection. */
class SelectionHandlers(
    val share: () -> Unit,
    val addToAlbum: () -> Unit,
    val favorite: () -> Unit,
    val delete: () -> Unit,
    val move: () -> Unit,
    val saveToPhone: () -> Unit,
    val sendTelegram: () -> Unit,
    val removeFromAlbum: (() -> Unit)? = null
)

@Composable
fun selectionActions(selected: Collection<AssetResponse>, handlers: SelectionHandlers): Pair<List<FloatingAction>, List<FloatingAction>> {
    val allFavorite = selected.isNotEmpty() && selected.all { it.favorite }
    val primary = listOf(
        FloatingAction(BentoIcons.Share2, stringResource(StringsR.string.common_action_share), handlers.share),
        FloatingAction(BentoIcons.SquareLibrary, stringResource(StringsR.string.common_action_add_to_album), handlers.addToAlbum),
        FloatingAction(
            if (allFavorite) BentoIcons.HeartFilled else BentoIcons.Heart,
            stringResource(if (allFavorite) StringsR.string.photos_action_favorite_remove else StringsR.string.photos_action_favorite_add),
            handlers.favorite
        ),
        FloatingAction(BentoIcons.Trash2, stringResource(StringsR.string.common_action_delete), handlers.delete, destructive = true)
    )
    val overflow = buildList {
        handlers.removeFromAlbum?.let { add(FloatingAction(BentoIcons.X, stringResource(StringsR.string.collections_album_remove), it)) }
        add(FloatingAction(BentoIcons.FolderInput, stringResource(StringsR.string.photos_action_move_to_folder), handlers.move))
        add(FloatingAction(BentoIcons.Download, stringResource(StringsR.string.common_action_save_to_phone), handlers.saveToPhone))
        add(FloatingAction(BentoIcons.Send, stringResource(StringsR.string.common_action_send_telegram), handlers.sendTelegram))
    }
    return primary to overflow
}

/** Which media sheet is open over a screen. */
sealed interface MediaSheet {
    data class AddToAlbum(val ids: List<String>) : MediaSheet

    data class Move(val assets: List<AssetResponse>) : MediaSheet

    data class Telegram(val assets: List<AssetResponse>) : MediaSheet

    data class Disclose(val kind: Disclosure) : MediaSheet
}

/** Collects [MediaActions] events: undo snackbars, messages, choosers, disclosures. */
@Composable
fun MediaEventsEffect(
    actions: MediaActions,
    snackbar: BentoSnackbarHostState,
    onSheet: (MediaSheet?) -> Unit,
    onTrashed: (List<String>) -> Unit = {}
) {
    val context = LocalContext.current
    val launch = rememberLauncher()
    val undoLabel = stringResource(StringsR.string.common_action_undo)
    val trashed by rememberUpdatedState(onTrashed)
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    LaunchedEffect(actions) {
        actions.events.collect { event ->
            when (event) {
                is MediaEvent.Undo -> scope.launch { if (snackbar.showUndo(event.message.resolve(context), undoLabel)) event.undo.undo() }
                is MediaEvent.Message -> scope.launch { snackbar.show(event.message.resolve(context)) }
                is MediaEvent.Launch -> launch(event)
                is MediaEvent.Trashed -> trashed(event.ids)
                is MediaEvent.Disclose -> onSheet(MediaSheet.Disclose(event.kind))
            }
        }
    }
}

/** Renders the open [MediaSheet] and routes its result to [actions]. */
@Composable
fun MediaSheetHost(sheet: MediaSheet?, actions: MediaActions, onClose: () -> Unit, onDone: () -> Unit = {}) {
    when (sheet) {
        null -> Unit

        is MediaSheet.AddToAlbum -> AddToAlbumSheet(
            onPick = { album ->
                actions.addToAlbum(album.id, album.title, sheet.ids)
                onClose()
                onDone()
            },
            onCreate = { title ->
                actions.createAlbum(title, sheet.ids)
                onClose()
                onDone()
            },
            onDismiss = onClose
        )

        is MediaSheet.Move -> MoveToFolderSheet(
            onMove = { folderId, name ->
                actions.move(sheet.assets, folderId, name)
                onClose()
                onDone()
            },
            onDismiss = onClose
        )

        is MediaSheet.Telegram -> TelegramChatSheet(
            onPick = { chat ->
                actions.sendTelegram(sheet.assets, chat)
                onClose()
                onDone()
            },
            onDismiss = onClose
        )

        is MediaSheet.Disclose -> PlaintextDisclosureSheet(
            kind = sheet.kind,
            onContinue = { hide ->
                actions.confirmDisclosure(sheet.kind, hide)
                onClose()
            },
            onDismiss = {
                actions.cancelDisclosure()
                onClose()
            }
        )
    }
}

/**
 * In-app frame metrics (JankStats) for a screen: janky frames are counted per UI state ("scrolling", "idle") and a
 * one-line summary goes to logcat every 5 s under `BentoJank` (no content, counts only). Macrobenchmark reads the
 * same frames from the system trace.
 */
@Composable
fun TrackJank(screen: String, scrolling: Boolean) {
    val view = LocalView.current
    val holder = remember(view) { PerformanceMetricsState.getHolderForHierarchy(view) }
    LaunchedEffect(scrolling) { holder.state?.putState(screen, if (scrolling) "scrolling" else "idle") }
    DisposableEffect(view) {
        val window = (view.context as? android.app.Activity)?.window
        var frames = 0
        var janky = 0
        var lastLog = System.nanoTime()
        val stats = window?.let { w ->
            runCatching {
                JankStats.createAndTrack(w) { frame ->
                    frames++
                    if (frame.isJank) janky++
                    val now = System.nanoTime()
                    if (now - lastLog > 5_000_000_000L && frames > 0) {
                        Log.i(
                            "BentoJank",
                            "$screen frames=$frames janky=$janky pct=${"%.2f".format(
                                java.util.Locale.ROOT,
                                janky * 100.0 / frames
                            )}"
                        )
                        lastLog = now
                        frames = 0
                        janky = 0
                    }
                }
            }.getOrNull()
        }
        onDispose {
            stats?.isTrackingEnabled = false
            holder.state?.removeState(screen)
        }
    }
}

/** Simple remembered nullable state helper for sheets. */
@Composable
fun rememberSheetState(): androidx.compose.runtime.MutableState<MediaSheet?> = remember { mutableStateOf<MediaSheet?>(null) }
