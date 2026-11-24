package dev.bento.feature.share

import android.content.Intent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil3.compose.rememberAsyncImagePainter
import dev.bento.api.generated.AlbumResponse
import dev.bento.designsystem.component.BentoAnnounce
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonSize
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.BentoSheet
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.KindIcon
import dev.bento.designsystem.component.ListRow
import dev.bento.designsystem.component.LoadingState
import dev.bento.designsystem.component.SettingsRow
import dev.bento.designsystem.component.Thumbnail
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.files.FileKinds
import dev.bento.feature.files.FolderBrowserState
import dev.bento.feature.files.FolderPickerBody
import dev.bento.feature.files.LocalBentoImageLoader
import dev.bento.feature.files.SheetBody
import dev.bento.feature.files.Sizes
import dev.bento.feature.files.di.FilesEntryPoint
import dev.bento.strings.R as StringsR
import dev.bento.designsystem.trace.InteractionTrace

data class ShareActions(
    val onSave: () -> Unit = {},
    val onClose: () -> Unit = {},
    val onPicker: (SharePicker?) -> Unit = {},
    val onAlbum: (AlbumResponse?) -> Unit = {}
)

/**
 * The share-target sheet over the sending app (translucent `ShareActivity`). [onFinish] is called right after
 * `Guardar en Bento` hands the streams over (the copy continues in background) or when the sheet is dismissed.
 */
@Composable
fun ShareSheetHost(intent: Intent?, onFinish: () -> Unit, viewModel: ShareViewModel = hiltViewModel()) {
    val context = LocalContext.current
    val root = stringResource(StringsR.string.files_title)
    val noteFallback = stringResource(StringsR.string.share_note_fallback)
    val payload = remember(intent) { ShareIntents.parse(intent) }
    LaunchedEffect(payload) { viewModel.start(payload, root, noteFallback) }
    val state by viewModel.state.collectAsStateWithLifecycle()
    val browser by viewModel.folderBrowser.state.collectAsStateWithLifecycle()
    val loader = remember(context) { runCatching { FilesEntryPoint.get(context).imageLoader() }.getOrNull() }
    val actions = ShareActions(
        onSave = {
            InteractionTrace.begin(InteractionTrace.SHARE_DISMISS)
            if (viewModel.save()) onFinish() else InteractionTrace.end(InteractionTrace.SHARE_DISMISS)
        },
        onClose = onFinish,
        onPicker = viewModel::showPicker,
        onAlbum = viewModel::setAlbum
    )
    CompositionLocalProvider(LocalBentoImageLoader provides loader) {
        BentoSheet(onDismissRequest = { if (state.picker != null) viewModel.showPicker(null) else onFinish() }) {
            ShareSheetBody(
                state = state,
                browser = browser,
                actions = actions,
                onOpenFolder = viewModel.folderBrowser::open,
                onUp = viewModel.folderBrowser::up,
                onSearchFolders = viewModel.folderBrowser::search,
                onCreateFolder = viewModel.folderBrowser::create,
                onPickFolder = viewModel::setDestination
            )
        }
    }
}

@Composable
fun ShareSheetBody(
    state: ShareState,
    browser: FolderBrowserState,
    actions: ShareActions,
    onOpenFolder: (String?) -> Unit = {},
    onUp: () -> Unit = {},
    onSearchFolders: (String) -> Unit = {},
    onCreateFolder: (String) -> Unit = {},
    onPickFolder: (dev.bento.feature.files.Destination) -> Unit = {}
) {
    when (state.picker) {
        SharePicker.Folder -> FolderPickerBody(
            title = stringResource(StringsR.string.share_destination),
            confirmLabel = stringResource(StringsR.string.share_pick_folder),
            state = browser,
            onOpen = onOpenFolder,
            onUp = onUp,
            onSearch = onSearchFolders,
            onCreate = onCreateFolder,
            onConfirm = onPickFolder
        )

        SharePicker.Album -> AlbumPickerBody(state, actions)

        null -> ShareMainBody(state, actions)
    }
}

@Composable
private fun ShareMainBody(state: ShareState, actions: ShareActions) {
    val c = BentoTheme.colors
    val resources = LocalResources.current
    SheetBody(stringResource(StringsR.string.share_title)) {
        if (state.loading) {
            LoadingState(Modifier.fillMaxWidth().padding(24.dp), label = stringResource(StringsR.string.share_loading))
            return@SheetBody
        }
        if (state.count == 0) {
            Callout(
                tone = CalloutTone.Warning,
                body = stringResource(StringsR.string.share_nothing),
                icon = BentoIcons.TriangleAlert,
                announce = BentoAnnounce.Polite
            )
            BentoButton(stringResource(StringsR.string.share_close), actions.onClose, Modifier.fillMaxWidth().padding(top = 16.dp))
            return@SheetBody
        }
        ThumbnailStrip(state)
        val files = pluralStringResource(StringsR.plurals.common_count_files, state.count, state.count)
        Text(
            stringResource(StringsR.string.share_summary, files, Sizes.format(resources, state.totalBytes)),
            color = c.ink,
            style = BentoTheme.typography.bodyStrong,
            modifier = Modifier.padding(top = 12.dp)
        )
        state.noteName?.let {
            Text(stringResource(StringsR.string.share_note, it), color = c.inkMuted, style = BentoTheme.typography.metadata)
        }
        if (state.unreadable.isNotEmpty()) {
            Callout(
                Modifier.padding(top = 12.dp),
                tone = CalloutTone.Warning,
                title = stringResource(StringsR.string.share_unreadable_title),
                body = pluralStringResource(StringsR.plurals.share_unreadable, state.unreadable.size, state.unreadable.size) +
                    "\n" + state.unreadable.joinToString(", ") { it.name },
                icon = BentoIcons.TriangleAlert
            )
        }
        SettingsRow(
            title = stringResource(StringsR.string.share_destination),
            onClick = { actions.onPicker(SharePicker.Folder) },
            value = state.destination.name,
            icon = BentoIcons.FolderClosed,
            modifier = Modifier.padding(top = 8.dp).semantics {
                contentDescription = resources.getString(StringsR.string.share_destination_change, state.destination.name)
            }
        )
        if (state.canAddToAlbum) {
            SettingsRow(
                title = stringResource(StringsR.string.share_album),
                onClick = { actions.onPicker(SharePicker.Album) },
                value = state.album?.title ?: stringResource(StringsR.string.share_album_none),
                icon = BentoIcons.SquareLibrary
            )
        }
        Row(
            Modifier.padding(top = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            BentoIcon(BentoIcons.Lock, null, tint = c.inkSubtle)
            Text(stringResource(StringsR.string.share_encrypted), color = c.inkMuted, style = BentoTheme.typography.metadata)
        }
        BentoButton(
            stringResource(StringsR.string.share_save),
            actions.onSave,
            Modifier.fillMaxWidth().padding(top = 16.dp),
            variant = BentoButtonVariant.Primary,
            size = BentoButtonSize.Large,
            enabled = state.canSave
        )
    }
}

@Composable
private fun ThumbnailStrip(state: ShareState) {
    val loader = LocalBentoImageLoader.current
    val shown = state.readable.take(MAX_THUMBS)
    val extra = state.readable.size - shown.size
    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        items(shown, key = { it.uri }) { item ->
            val label = stringResource(StringsR.string.share_thumbnail, item.name)
            Box(Modifier.size(72.dp).clip(BentoShapes.md).background(BentoTheme.colors.subtle), contentAlignment = Alignment.Center) {
                if (item.media && loader != null) {
                    Thumbnail(rememberAsyncImagePainter(item.uri.toUri(), loader), label, Modifier.fillMaxSize())
                } else {
                    KindIcon(FileKinds.fileKind(item.mimeType, item.name), contentDescription = label)
                }
            }
        }
        if (state.note !=
            null
        ) {
            item {
                Box(Modifier.size(72.dp).clip(BentoShapes.md).background(BentoTheme.colors.subtle), Alignment.Center) {
                    KindIcon(dev.bento.designsystem.component.FileKind.Text)
                }
            }
        }
        if (extra > 0) {
            item {
                Box(Modifier.size(72.dp).clip(BentoShapes.md).background(BentoTheme.colors.subtle), contentAlignment = Alignment.Center) {
                    Text(
                        stringResource(StringsR.string.share_more, extra),
                        color = BentoTheme.colors.inkMuted,
                        style = BentoTheme.typography.labelStrong
                    )
                }
            }
        }
    }
}

private const val MAX_THUMBS = 8

@Composable
private fun AlbumPickerBody(state: ShareState, actions: ShareActions) {
    SheetBody(stringResource(StringsR.string.share_album_title)) {
        if (state.albumsLoading) {
            LoadingState(Modifier.fillMaxWidth().padding(16.dp))
            return@SheetBody
        }
        LazyColumn(Modifier.heightIn(max = 420.dp)) {
            item {
                ListRow(
                    headline = stringResource(StringsR.string.share_album_none),
                    leading = { BentoIcon(if (state.album == null) BentoIcons.Check else BentoIcons.X, null) },
                    onClick = { actions.onAlbum(null) },
                    selected = state.album == null
                )
            }
            items(state.albums, key = { it.id }) { album ->
                ListRow(
                    headline = album.title,
                    leading = { BentoIcon(if (state.album?.id == album.id) BentoIcons.Check else BentoIcons.SquareLibrary, null) },
                    onClick = { actions.onAlbum(album) },
                    selected = state.album?.id == album.id
                )
            }
        }
        if (state.albums.isEmpty()) {
            Text(stringResource(StringsR.string.share_album_empty), color = BentoTheme.colors.inkMuted, style = BentoTheme.typography.body)
        }
    }
}
