package dev.bento.feature.files

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.input.TextFieldState
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import dev.bento.api.generated.DriveItemResponse
import dev.bento.api.generated.TelegramChatResponse
import dev.bento.designsystem.component.BentoAnnounce
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.BentoTextField
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.FileKind
import dev.bento.designsystem.component.KindIcon
import dev.bento.designsystem.component.ListRow
import dev.bento.designsystem.component.LoadingState
import dev.bento.designsystem.component.SectionHeader
import dev.bento.designsystem.component.SegmentOption
import dev.bento.designsystem.component.SegmentedButtons
import dev.bento.designsystem.component.SettingsRow
import dev.bento.designsystem.component.SwitchRow
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.strings.R as StringsR
import kotlinx.coroutines.flow.debounce

/** `+ Nuevo`: upload files, photos/videos (system picker, no permission), a folder tree, scan, new folder. */
@Composable
fun NewSheetBody(
    folderName: String,
    scanAvailable: Boolean,
    onUploadFiles: () -> Unit,
    onUploadMedia: () -> Unit,
    onUploadFolder: () -> Unit,
    onScan: () -> Unit,
    onNewFolder: () -> Unit
) {
    SheetBody(stringResource(StringsR.string.files_new_title, folderName)) {
        SettingsRow(stringResource(StringsR.string.files_new_upload_files), onUploadFiles, icon = BentoIcons.Upload, showChevron = false)
        SettingsRow(stringResource(StringsR.string.files_new_upload_media), onUploadMedia, icon = BentoIcons.ImagePlus, showChevron = false)
        SettingsRow(
            stringResource(StringsR.string.files_new_upload_folder),
            onUploadFolder,
            summary = stringResource(StringsR.string.files_new_upload_folder_hint),
            icon = BentoIcons.FolderUp,
            showChevron = false
        )
        if (scanAvailable) {
            SettingsRow(
                stringResource(StringsR.string.files_new_scan),
                onScan,
                summary = stringResource(StringsR.string.files_new_scan_hint),
                icon = BentoIcons.ScanLine,
                showChevron = false
            )
        }
        SettingsRow(stringResource(StringsR.string.files_new_folder), onNewFolder, icon = BentoIcons.FolderPlus, showChevron = false)
    }
}

/** Inline name field (keyboard opens) with `Crear`. */
@Composable
fun NameSheetBody(
    title: String,
    label: String,
    confirm: String,
    field: TextFieldState,
    error: UiText?,
    busy: Boolean,
    onConfirm: () -> Unit,
    autoFocus: Boolean = true
) {
    val focus = remember { FocusRequester() }
    if (autoFocus) LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }
    SheetBody(title) {
        BentoTextField(
            state = field,
            label = label,
            error = error?.text(),
            modifier = Modifier.focusRequester(focus),
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
            onKeyboardAction = { onConfirm() }
        )
        BentoButton(
            confirm,
            onConfirm,
            Modifier.fillMaxWidth().padding(top = 16.dp),
            variant = BentoButtonVariant.Primary,
            loading = busy
        )
    }
}

/** Sort sheet: field + direction; remembered per folder. */
@Composable
fun SortSheetBody(sort: FolderSort, onChange: (FolderSort) -> Unit) {
    SheetBody(stringResource(StringsR.string.files_sort_title)) {
        SortField.entries.forEach { field ->
            ListRow(
                headline = stringResource(sortLabel(field)),
                leading = {
                    BentoIcon(
                        if (sort.field == field) BentoIcons.Check else BentoIcons.ArrowUpDown,
                        null,
                        tint = if (sort.field == field) BentoTheme.colors.accent else BentoTheme.colors.inkSubtle
                    )
                },
                onClick = { onChange(sort.copy(field = field)) },
                selected = sort.field == field
            )
        }
        SegmentedButtons(
            options = listOf(
                SegmentOption(false, stringResource(StringsR.string.files_sort_ascending)),
                SegmentOption(true, stringResource(StringsR.string.files_sort_descending))
            ),
            selected = sort.descending,
            onSelect = { onChange(sort.copy(descending = it)) },
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp)
        )
        Text(
            stringResource(StringsR.string.files_sort_remembered),
            color = BentoTheme.colors.inkMuted,
            style = BentoTheme.typography.metadata,
            modifier = Modifier.padding(top = 12.dp)
        )
    }
}

fun sortLabel(field: SortField): Int = when (field) {
    SortField.Name -> StringsR.string.files_sort_name
    SortField.Modified -> StringsR.string.files_sort_modified
    SortField.Size -> StringsR.string.files_sort_size
    SortField.Type -> StringsR.string.files_sort_type
}

/** Item menu entries (product/android.md §4.5), in order. */
enum class MenuAction { Open, Share, Download, Offline, Move, Rename, Favorite, Telegram, Details, Delete }

fun menuActions(item: DriveItemResponse): List<MenuAction> = if (item.asset == null) {
    listOf(MenuAction.Open, MenuAction.Move, MenuAction.Rename, MenuAction.Details, MenuAction.Delete)
} else {
    listOf(
        MenuAction.Share,
        MenuAction.Download,
        MenuAction.Offline,
        MenuAction.Move,
        MenuAction.Rename,
        MenuAction.Favorite,
        MenuAction.Telegram,
        MenuAction.Details,
        MenuAction.Delete
    )
}

@Composable
fun ItemMenuBody(item: DriveItemResponse, pinned: Boolean, onAction: (MenuAction) -> Unit) {
    SheetBody(null) {
        ListRow(
            headline = item.name,
            supporting = itemSupporting(item),
            leading = { KindIcon(FileKinds.fileKind(item)) }
        )
        menuActions(item).forEach { action ->
            val (label, icon) = menuEntry(action, item, pinned)
            val danger = action == MenuAction.Delete
            ListRow(
                headline = label,
                leading = { BentoIcon(icon, null, tint = if (danger) BentoTheme.colors.danger else BentoTheme.colors.inkMuted) },
                onClick = { onAction(action) }
            )
        }
    }
}

/** Label and icon of one menu entry (exhaustive table). */
@Suppress("CyclomaticComplexMethod")
@Composable
private fun menuEntry(action: MenuAction, item: DriveItemResponse, pinned: Boolean): Pair<String, ImageVector> = when (action) {
    MenuAction.Open -> stringResource(StringsR.string.files_open_folder) to BentoIcons.FolderClosed

    MenuAction.Share -> stringResource(StringsR.string.common_action_share) to BentoIcons.Share2

    MenuAction.Download -> stringResource(StringsR.string.common_action_download) to BentoIcons.Download

    MenuAction.Offline -> if (pinned) {
        stringResource(StringsR.string.files_menu_offline_remove) to BentoIcons.PinOff
    } else {
        stringResource(StringsR.string.files_menu_offline) to BentoIcons.Pin
    }

    MenuAction.Move -> stringResource(StringsR.string.common_action_move) to BentoIcons.FolderInput

    MenuAction.Rename -> stringResource(StringsR.string.common_action_rename) to BentoIcons.PencilLine

    MenuAction.Favorite -> if (item.asset?.favorite == true) {
        stringResource(StringsR.string.files_menu_unfavorite) to BentoIcons.Heart
    } else {
        stringResource(StringsR.string.common_action_favorite) to BentoIcons.Heart
    }

    MenuAction.Telegram -> stringResource(StringsR.string.common_action_send_telegram) to BentoIcons.Send

    MenuAction.Details -> stringResource(StringsR.string.files_menu_details) to BentoIcons.Info

    MenuAction.Delete -> stringResource(StringsR.string.common_action_delete) to BentoIcons.Trash2
}

/**
 * Move sheet: recent destinations on top, folder browser with search and `Nueva carpeta` inline, `Mover aquí` as the
 * primary action. Also the destination picker of the share sheet and the search folder filter ([confirmLabel]).
 */
@Composable
fun FolderPickerBody(
    title: String,
    confirmLabel: String,
    state: FolderBrowserState,
    onOpen: (String?) -> Unit,
    onUp: () -> Unit,
    onSearch: (String) -> Unit,
    onCreate: (String) -> Unit,
    onConfirm: (Destination) -> Unit,
    modifier: Modifier = Modifier
) {
    val root = stringResource(StringsR.string.files_title)
    val query = rememberTextFieldState(state.query)
    val newName = rememberTextFieldState()
    var creating by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(query) { snapshotFlow { query.text.toString() }.debounce(0).collect { if (it != state.query) onSearch(it) } }
    SheetBody(title, modifier) {
        BentoTextField(
            query,
            stringResource(StringsR.string.files_move_search),
            leadingIcon = BentoIcons.Search,
            hideLabel = true,
            placeholder = stringResource(StringsR.string.files_move_search)
        )
        FolderPickerList(state, root, onOpen, onUp)
        if (creating) {
            NameSheetInline(newName, state, onCreate = { onCreate(newName.text.toString()) })
        } else {
            BentoButton(
                stringResource(StringsR.string.files_new_folder),
                { creating = true },
                Modifier.fillMaxWidth().padding(top = 8.dp),
                variant = BentoButtonVariant.Ghost,
                leadingIcon = BentoIcons.FolderPlus
            )
        }
        BentoButton(
            confirmLabel,
            { onConfirm(Destination(state.folderId, state.currentName ?: root)) },
            Modifier.fillMaxWidth().padding(top = 8.dp),
            variant = BentoButtonVariant.Primary,
            enabled = state.canChooseHere && !state.loading
        )
    }
}

@Composable
private fun FolderPickerList(state: FolderBrowserState, root: String, onOpen: (String?) -> Unit, onUp: () -> Unit) {
    val c = BentoTheme.colors
    LazyColumn(Modifier.fillMaxWidth().heightIn(max = 380.dp).padding(top = 8.dp)) {
        if (state.query.isNotBlank()) {
            items(state.results, key = { "r:${it.id}" }) { folder ->
                FolderPickRow(folder.name, blocked = folder.id in state.blocked) { onOpen(folder.id) }
            }
        } else {
            val recent = state.recent.filter { it.id != state.folderId }.take(3)
            if (recent.isNotEmpty() && state.crumbs.isEmpty()) {
                item { SectionHeader(stringResource(StringsR.string.files_move_recent)) }
                items(recent, key = { "recent:${it.id}" }) { destination ->
                    FolderPickRow(destination.name, blocked = destination.id in state.blocked, icon = BentoIcons.History) {
                        onOpen(destination.id)
                    }
                }
            }
            item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (state.crumbs.isNotEmpty()) {
                        dev.bento.designsystem.component.BentoIconButton(
                            BentoIcons.ArrowLeft,
                            stringResource(StringsR.string.files_up),
                            onUp
                        )
                    }
                    SectionHeader(state.currentName ?: root, Modifier.weight(1f))
                }
            }
            when {
                state.loading -> item { LoadingState(Modifier.padding(16.dp)) }

                state.failed -> item {
                    Text(stringResource(StringsR.string.files_load_failed), color = c.inkMuted, style = BentoTheme.typography.metadata)
                }

                state.folders.isEmpty() -> item {
                    Text(
                        stringResource(StringsR.string.files_move_no_folders),
                        color = c.inkMuted,
                        style = BentoTheme.typography.metadata,
                        modifier = Modifier.padding(16.dp)
                    )
                }

                else -> items(state.folders, key = { it.id }) { folder ->
                    FolderPickRow(folder.name, blocked = folder.id in state.blocked) { onOpen(folder.id) }
                }
            }
        }
    }
}

@Composable
private fun NameSheetInline(field: TextFieldState, state: FolderBrowserState, onCreate: () -> Unit) {
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }
    Row(
        Modifier.fillMaxWidth().padding(top = 8.dp),
        verticalAlignment = Alignment.Bottom,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        BentoTextField(
            field,
            stringResource(StringsR.string.files_new_folder_label),
            Modifier.weight(1f).focusRequester(focus),
            error = state.createError?.text(),
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
            onKeyboardAction = { onCreate() }
        )
        BentoButton(stringResource(StringsR.string.files_new_folder_create), onCreate, loading = state.creating)
    }
}

@Composable
private fun FolderPickRow(
    name: String,
    blocked: Boolean,
    icon: androidx.compose.ui.graphics.vector.ImageVector? = null,
    onOpen: () -> Unit
) {
    ListRow(
        headline = name,
        leading = { if (icon != null) BentoIcon(icon, null, tint = BentoTheme.colors.inkSubtle) else KindIcon(FileKind.Folder) },
        trailing = { BentoIcon(BentoIcons.ChevronRight, null, tint = BentoTheme.colors.inkSubtle) },
        onClick = onOpen,
        onClickLabel = stringResource(StringsR.string.files_move_open, name),
        enabled = !blocked
    )
}

@Composable
fun DetailsSheetBody(item: DriveItemResponse, location: String?, pinned: Boolean) {
    val resources = LocalResources.current
    val asset = item.asset
    SheetBody(stringResource(StringsR.string.files_details_title)) {
        ListRow(headline = item.name, leading = { KindIcon(FileKinds.fileKind(item)) })
        val kindLabel = stringResource(kindLabel(FileKinds.fileKind(item)))
        Detail(stringResource(StringsR.string.files_details_kind), asset?.mimeType?.let { "$kindLabel · $it" } ?: kindLabel)
        asset?.let { Detail(stringResource(StringsR.string.files_details_size), Sizes.format(resources, it.sizeBytes)) }
        FileDates.medium(item.updatedAt)?.let { Detail(stringResource(StringsR.string.files_details_modified), it) }
        asset?.takenAt?.let { FileDates.medium(it) }?.let { Detail(stringResource(StringsR.string.files_details_taken), it) }
        location?.let { Detail(stringResource(StringsR.string.files_details_location), it) }
        if (asset != null) {
            val state = when (asset.remoteState) {
                "local_only" -> StringsR.string.files_state_local_only
                "uploading" -> StringsR.string.files_state_uploading
                "failed" -> StringsR.string.files_state_failed
                else -> StringsR.string.files_state_remote
            }
            Detail(stringResource(StringsR.string.files_details_state), stringResource(state))
            Detail(
                stringResource(StringsR.string.files_details_offline),
                stringResource(if (pinned) StringsR.string.files_state_offline_on else StringsR.string.files_state_offline_off)
            )
        }
    }
}

@Composable
private fun Detail(label: String, value: String) {
    Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Text(label, color = BentoTheme.colors.inkMuted, style = BentoTheme.typography.metadata)
        Text(value, color = BentoTheme.colors.ink, style = BentoTheme.typography.body)
    }
}

fun kindLabel(kind: FileKind): Int = when (kind) {
    FileKind.Folder -> StringsR.string.ds_kind_folder
    FileKind.Pdf -> StringsR.string.ds_kind_pdf
    FileKind.Doc -> StringsR.string.ds_kind_doc
    FileKind.Sheet -> StringsR.string.ds_kind_sheet
    FileKind.Slides -> StringsR.string.ds_kind_slides
    FileKind.Image -> StringsR.string.ds_kind_image
    FileKind.Video -> StringsR.string.ds_kind_video
    FileKind.Audio -> StringsR.string.ds_kind_audio
    FileKind.Archive -> StringsR.string.ds_kind_archive
    FileKind.Text -> StringsR.string.ds_kind_text
}

/** `Enviar por Telegram…`: chat picker; the plaintext line is always shown (product/android.md §10). */
@Composable
fun TelegramSheetBody(picker: TelegramPicker, onQuery: (String) -> Unit, onPick: (TelegramChatResponse) -> Unit) {
    val query = rememberTextFieldState()
    LaunchedEffect(query) { snapshotFlow { query.text.toString() }.debounce(250).collect { onQuery(it) } }
    SheetBody(stringResource(StringsR.string.files_telegram_title)) {
        Callout(tone = CalloutTone.Warning, body = stringResource(StringsR.string.common_plaintext_telegram), icon = BentoIcons.Send)
        BentoTextField(
            query,
            stringResource(StringsR.string.files_telegram_search),
            Modifier.padding(top = 12.dp),
            leadingIcon = BentoIcons.Search,
            hideLabel = true,
            placeholder = stringResource(StringsR.string.files_telegram_search)
        )
        when {
            picker.loading -> LoadingState(Modifier.padding(16.dp))

            picker.failed -> Text(
                stringResource(StringsR.string.files_telegram_unavailable),
                color = BentoTheme.colors.inkMuted,
                style = BentoTheme.typography.body,
                modifier = Modifier.padding(16.dp)
            )

            picker.chats.isEmpty() -> Text(
                stringResource(StringsR.string.files_telegram_empty),
                color = BentoTheme.colors.inkMuted,
                style = BentoTheme.typography.body,
                modifier = Modifier.padding(16.dp)
            )

            else -> LazyColumn(Modifier.heightIn(max = 360.dp)) {
                items(picker.chats, key = { it.id }) { chat ->
                    ListRow(headline = chat.title, leading = { BentoIcon(BentoIcons.User, null) }, onClick = { onPick(chat) })
                }
            }
        }
    }
}

/** Plaintext notice before `Abrir con…`, `Compartir` or `Descargar al teléfono` (first time per action type). */
@Composable
fun DisclosureSheetBody(kind: Disclosure, onContinue: (dontShowAgain: Boolean) -> Unit, onCancel: () -> Unit) {
    var dontShow by rememberSaveable { mutableStateOf(false) }
    val body = when (kind) {
        Disclosure.Share -> StringsR.string.common_plaintext_share
        Disclosure.OpenWith -> StringsR.string.common_plaintext_open_with
        Disclosure.SaveToPhone -> StringsR.string.common_plaintext_save_to_phone
    }
    SheetBody(stringResource(StringsR.string.files_disclosure_title)) {
        Callout(tone = CalloutTone.Warning, body = stringResource(body), icon = BentoIcons.Lock, announce = BentoAnnounce.Polite)
        SwitchRow(stringResource(StringsR.string.common_plaintext_dont_show_again), dontShow, {
            dontShow = it
        }, Modifier.padding(top = 8.dp))
        BentoButton(
            stringResource(StringsR.string.files_disclosure_continue),
            { onContinue(dontShow) },
            Modifier.fillMaxWidth().padding(top = 12.dp),
            variant = BentoButtonVariant.Primary
        )
        BentoButton(
            stringResource(StringsR.string.common_action_cancel),
            onCancel,
            Modifier.fillMaxWidth().padding(top = 8.dp),
            variant = BentoButtonVariant.Ghost
        )
    }
}

/** Offline and not pinned (journey 8). */
@Composable
fun OfflineSheetBody(item: DriveItemResponse, onClose: () -> Unit) {
    SheetBody(stringResource(StringsR.string.files_offline_title)) {
        Callout(
            tone = CalloutTone.Neutral,
            body = stringResource(StringsR.string.files_offline_body, item.name),
            icon = BentoIcons.CloudOff,
            announce = BentoAnnounce.Polite
        )
        BentoButton(stringResource(StringsR.string.common_action_close), onClose, Modifier.fillMaxWidth().padding(top = 16.dp))
    }
}
