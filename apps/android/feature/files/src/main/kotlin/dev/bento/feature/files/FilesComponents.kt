package dev.bento.feature.files

import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Text
import androidx.compose.material3.ripple
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.PointerEventType
import androidx.compose.ui.input.pointer.isSecondaryPressed
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil3.ImageLoader
import coil3.compose.rememberAsyncImagePainter
import dev.bento.api.BentoImage
import dev.bento.api.generated.AssetResponse
import dev.bento.api.generated.DriveBreadcrumbResponse
import dev.bento.api.generated.DriveItemResponse
import dev.bento.designsystem.component.BentoChip
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.BentoIconButton
import dev.bento.designsystem.component.BentoIconSize
import dev.bento.designsystem.component.BentoSheetHandle
import dev.bento.designsystem.component.BentoTextAction
import dev.bento.designsystem.component.FileKind
import dev.bento.designsystem.component.KindIcon
import dev.bento.designsystem.component.ListRow
import dev.bento.designsystem.component.ProgressBar
import dev.bento.designsystem.component.SelectionCheck
import dev.bento.designsystem.component.Thumbnail
import dev.bento.designsystem.component.bentoFocusRing
import dev.bento.designsystem.format.BentoFormat
import dev.bento.designsystem.format.pluralCountResource
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoElevation
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.designsystem.theme.bentoShadow
import dev.bento.strings.R as StringsR

/** The loopback-aware Coil loader (`core/api`), provided by the screens; null in previews and screenshots. */
val LocalBentoImageLoader = staticCompositionLocalOf<ImageLoader?> { null }

/** Sheet body with the Bento gutters (title as a heading); also used by screenshots without a window. */
@Composable
fun SheetBody(title: String?, modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, bottom = 24.dp)) {
        if (title != null) {
            Text(
                title,
                color = BentoTheme.colors.ink,
                style = BentoTheme.typography.sectionTitle,
                modifier = Modifier.padding(top = 4.dp, bottom = 12.dp).semantics { heading() }
            )
        }
        content()
    }
}

/** A sheet as it looks open (handle, raised surface, top corners) for screenshots and Compose tests. */
@Composable
fun SheetFrame(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxWidth().then(modifier).clip(BentoShapes.sheet).background(BentoTheme.colors.raised)) {
        BentoSheetHandle()
        content()
    }
}

/** The `ink-muted` line under a name: size · date for files, "12 elementos · date" for folders ("Carpeta" if unknown). */
@Composable
fun itemSupporting(item: DriveItemResponse): String {
    val resources = LocalResources.current
    val date = FileDates.medium(item.updatedAt).orEmpty()
    val count = item.itemCount
    val first = item.asset?.let { BentoFormat.bytes(resources, it.sizeBytes) }
        ?: count?.let { pluralCountResource(StringsR.plurals.files_folder_items, it.coerceAtMost(Int.MAX_VALUE.toLong()).toInt()) }
        ?: stringResource(StringsR.string.files_folder)
    return if (date.isEmpty()) first else stringResource(StringsR.string.files_item_supporting, first, date)
}

/**
 * Honest state of a file (product/android.md §1.4): pinned for offline, on this phone (the original opens offline:
 * cached or still in its backup source), only on this phone, uploading, failed.
 */
enum class ItemBadge { Offline, OnDevice, LocalOnly, Uploading, Failed }

/** Pinned for offline: the backend's `offline_pinned`, or a pin this phone just made (the listing has not reloaded). */
fun isPinned(asset: AssetResponse, pinned: Set<String>): Boolean = asset.offlinePinned || asset.id in pinned

/** [isPinned] for a row; folders are never pinned. */
fun DriveItemResponse.pinnedIn(pinned: Set<String>): Boolean = asset?.let { isPinned(it, pinned) } ?: false

/** The original opens without a connection: pinned, or `locally_available` (cached, never uploaded, in its source). */
fun opensOffline(asset: AssetResponse, pinned: Set<String>): Boolean = isPinned(asset, pinned) || asset.locallyAvailable

fun badgesOf(item: DriveItemResponse, pinned: Set<String>): List<ItemBadge> {
    val asset = item.asset ?: return emptyList()
    val remote = when (asset.remoteState) {
        "local_only" -> ItemBadge.LocalOnly
        "uploading" -> ItemBadge.Uploading
        "failed" -> ItemBadge.Failed
        else -> null
    }
    val offline = isPinned(asset, pinned)
    val onDevice = !offline && asset.locallyAvailable && remote == null
    return listOfNotNull(ItemBadge.Offline.takeIf { offline }, ItemBadge.OnDevice.takeIf { onDevice }, remote)
}

@Composable
private fun badgeLabel(badge: ItemBadge): String = stringResource(
    when (badge) {
        ItemBadge.Offline -> StringsR.string.files_badge_offline
        ItemBadge.OnDevice -> StringsR.string.files_badge_on_device
        ItemBadge.LocalOnly -> StringsR.string.files_badge_local_only
        ItemBadge.Uploading -> StringsR.string.files_badge_uploading
        ItemBadge.Failed -> StringsR.string.files_badge_failed
    }
)

@Composable
private fun BadgeIcons(badges: List<ItemBadge>) {
    val c = BentoTheme.colors
    badges.forEach { badge ->
        val (icon, tint) = when (badge) {
            ItemBadge.Offline -> BentoIcons.Pin to c.accent
            ItemBadge.OnDevice -> BentoIcons.FileDown to c.inkSubtle
            ItemBadge.LocalOnly -> BentoIcons.Smartphone to c.inkSubtle
            ItemBadge.Uploading -> BentoIcons.CloudUpload to c.accent
            ItemBadge.Failed -> BentoIcons.CircleAlert to c.warning
        }
        BentoIcon(icon, contentDescription = null, tint = tint, size = BentoIconSize.Dense)
    }
}

/** Actions a row/tile exposes to touch, keyboard, mouse and TalkBack (custom actions: no gesture required). */
data class ItemCallbacks(
    val onOpen: (DriveItemResponse) -> Unit = {},
    val onSelect: (DriveItemResponse) -> Unit = {},
    val onMenu: (DriveItemResponse) -> Unit = {},
    val onShare: (DriveItemResponse) -> Unit = {},
    val onFavorite: (DriveItemResponse) -> Unit = {},
    val onTrash: (DriveItemResponse) -> Unit = {}
)

@Composable
private fun Modifier.itemSemantics(item: DriveItemResponse, callbacks: ItemCallbacks, badges: List<ItemBadge>): Modifier {
    val open = stringResource(if (item.folder != null) StringsR.string.files_open_folder else StringsR.string.files_open_file)
    val select = stringResource(StringsR.string.common_action_select)
    val share = stringResource(StringsR.string.common_action_share)
    val favorite = stringResource(StringsR.string.common_action_favorite)
    val trash = stringResource(StringsR.string.common_action_delete)
    val badgeText = badges.map { badgeLabel(it) }
    return semantics {
        customActions = buildList {
            add(CustomAccessibilityAction(open) { callbacks.onOpen(item).let { true } })
            add(CustomAccessibilityAction(select) { callbacks.onSelect(item).let { true } })
            if (item.asset != null) {
                add(CustomAccessibilityAction(share) { callbacks.onShare(item).let { true } })
                add(CustomAccessibilityAction(favorite) { callbacks.onFavorite(item).let { true } })
            }
            add(CustomAccessibilityAction(trash) { callbacks.onTrash(item).let { true } })
        }
        if (badgeText.isNotEmpty()) stateDescription = badgeText.joinToString(", ")
    }
}

/** Right-click opens the item menu (mouse, ChromeOS). */
fun Modifier.secondaryClick(onSecondary: () -> Unit): Modifier = pointerInput(Unit) {
    awaitPointerEventScope {
        while (true) {
            val event = awaitPointerEvent(PointerEventPass.Initial)
            if (event.type == PointerEventType.Press && event.buttons.isSecondaryPressed) {
                event.changes.forEach { it.consume() }
                onSecondary()
            }
        }
    }
}

@Composable
fun FileRow(
    item: DriveItemResponse,
    selected: Boolean,
    selecting: Boolean,
    pinned: Set<String>,
    callbacks: ItemCallbacks,
    modifier: Modifier = Modifier
) {
    val badges = badgesOf(item, pinned)
    val options = stringResource(StringsR.string.files_item_options, item.name)
    ListRow(
        headline = item.name,
        supporting = itemSupporting(item),
        modifier = modifier.secondaryClick { callbacks.onMenu(item) }.itemSemantics(item, callbacks, badges),
        leading = {
            Box {
                KindIcon(FileKinds.fileKind(item))
                if (selecting) SelectionCheck(selected, Modifier.align(Alignment.BottomEnd).size(18.dp))
            }
        },
        trailing = {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                BadgeIcons(badges)
                if (item.asset?.favorite == true) dev.bento.designsystem.component.BentoFavorite(true, size = BentoIconSize.Dense)
                if (!selecting) BentoIconButton(BentoIcons.EllipsisVertical, options, { callbacks.onMenu(item) }, dense = true)
            }
        },
        onClick = { callbacks.onOpen(item) },
        onLongClick = { callbacks.onSelect(item) },
        onClickLabel = stringResource(if (item.folder != null) StringsR.string.files_open_folder else StringsR.string.files_open_file),
        selected = selected
    )
}

@Composable
fun FileTile(
    item: DriveItemResponse,
    selected: Boolean,
    selecting: Boolean,
    pinned: Set<String>,
    callbacks: ItemCallbacks,
    modifier: Modifier = Modifier
) {
    val c = BentoTheme.colors
    val badges = badgesOf(item, pinned)
    val asset = item.asset
    val showThumb =
        asset?.thumbnailUrl != null && FileKinds.fileKind(item).let { it == FileKind.Image || it == FileKind.Video || it == FileKind.Pdf }
    val interaction = remember { MutableInteractionSource() }
    Column(
        modifier
            .clip(BentoShapes.lg)
            .background(if (selected) c.accentSoft else c.raised)
            .secondaryClick { callbacks.onMenu(item) }
            .combinedClickable(interaction, ripple(), role = Role.Button, onLongClick = {
                callbacks.onSelect(item)
            }) { callbacks.onOpen(item) }
            .bentoFocusRing(interaction, BentoShapes.lg)
            .itemSemantics(item, callbacks, badges)
            .semantics(mergeDescendants = true) { if (selected) this.selected = true }
            .padding(8.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        Box(Modifier.fillMaxWidth().aspectRatio(1f).clip(BentoShapes.md).background(c.subtle), contentAlignment = Alignment.Center) {
            val loader = LocalBentoImageLoader.current
            if (showThumb && asset != null && loader != null) {
                Thumbnail(
                    painter = rememberAsyncImagePainter(BentoImage.thumbnail(asset.id, asset.thumbnailEtag), loader),
                    contentDescription = null,
                    selected = selected,
                    selectionMode = selecting
                )
            } else {
                KindIcon(FileKinds.fileKind(item), large = true)
                if (selecting) SelectionCheck(selected, Modifier.align(Alignment.TopStart).padding(6.dp))
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(
                item.name,
                Modifier.weight(1f),
                color = c.ink,
                style = BentoTheme.typography.label,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )
            BadgeIcons(badges)
        }
    }
}

/**
 * Collapsible chip row `Archivos › Trabajo › 2024`: tapping a chip navigates; long-pressing the back affordance shows
 * the whole path as a menu. Deep paths collapse the middle into "…".
 */
@Composable
fun Breadcrumbs(
    crumbs: List<DriveBreadcrumbResponse>,
    onNavigate: (String?) -> Unit,
    modifier: Modifier = Modifier
) {
    val c = BentoTheme.colors
    val root = stringResource(StringsR.string.files_title)
    val all = listOf(DriveBreadcrumbResponse(null, root)) + crumbs
    val pathLabel = stringResource(StringsR.string.files_breadcrumbs, all.joinToString(" › ") { it.name })
    var menu by remember { mutableStateOf(false) }
    val shown = if (all.size > MAX_CRUMBS) listOf(all.first(), null) + all.takeLast(MAX_CRUMBS - 1) else all
    Row(
        modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 4.dp)
            .semantics { contentDescription = pathLabel },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(2.dp)
    ) {
        if (crumbs.isNotEmpty()) {
            Box {
                Box(
                    Modifier.size(48.dp).clip(BentoShapes.full).combinedClickable(
                        onClickLabel = stringResource(StringsR.string.files_up),
                        onLongClickLabel = stringResource(StringsR.string.files_path_menu),
                        onLongClick = { menu = true }
                    ) { onNavigate(all[all.size - 2].folderId) },
                    contentAlignment = Alignment.Center
                ) {
                    BentoIcon(BentoIcons.ArrowLeft, stringResource(StringsR.string.files_up), tint = c.ink)
                }
                DropdownMenu(expanded = menu, onDismissRequest = { menu = false }, containerColor = c.raised) {
                    all.forEach { crumb ->
                        DropdownMenuItem(
                            text = { Text(crumb.name, color = c.ink, style = BentoTheme.typography.body) },
                            leadingIcon = { BentoIcon(BentoIcons.Folder, null, tint = c.kindFolder) },
                            onClick = {
                                menu = false
                                onNavigate(crumb.folderId)
                            }
                        )
                    }
                }
            }
        }
        shown.forEachIndexed { index, crumb ->
            if (index > 0) BentoIcon(BentoIcons.ChevronRight, null, tint = c.inkSubtle, size = BentoIconSize.Dense)
            if (crumb == null) {
                Text(ELLIPSIS, color = c.inkMuted, style = BentoTheme.typography.label, modifier = Modifier.clearAndSetSemantics {})
            } else if (index == shown.lastIndex) {
                Text(
                    crumb.name,
                    color = c.ink,
                    style = BentoTheme.typography.labelStrong,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(horizontal = 8.dp).semantics { heading() }
                )
            } else {
                BentoChip(crumb.name, onClick = { onNavigate(crumb.folderId) })
            }
        }
    }
}

private const val MAX_CRUMBS = 4
private const val ELLIPSIS = "\u2026"

/**
 * Floating progress card above the navigation bar ("Subiendo 3 archivos · 12 MB de 40 MB"); expands to per-file rows
 * with `Pausar`. Hidden when nothing is pending (the avatar ring takes over).
 */
@Composable
fun UploadCard(
    state: UploadsState,
    onPause: () -> Unit,
    onResume: () -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
    initiallyExpanded: Boolean = false
) {
    if (!state.visible) return
    val c = BentoTheme.colors
    val resources = LocalResources.current
    var expanded by remember { mutableStateOf(initiallyExpanded) }
    val title = uploadTitle(state)
    val bytes = stringResource(
        StringsR.string.common_unit_progress_of,
        BentoFormat.bytes(resources, state.doneBytes),
        BentoFormat.bytes(resources, state.totalBytes)
    )
    Column(
        modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp)
            .bentoShadow(BentoElevation.Lg, BentoShapes.lg)
            .clip(BentoShapes.lg)
            .background(c.raised)
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            BentoIcon(if (state.paused) BentoIcons.CirclePause else BentoIcons.CloudUpload, null, tint = c.accent)
            Column(Modifier.weight(1f)) {
                Text(
                    if (state.totalBytes > 0 && state.active) stringResource(StringsR.string.files_upload_summary, title, bytes) else title,
                    color = c.ink,
                    style = BentoTheme.typography.labelStrong
                )
                if (state.paused) {
                    Text(
                        stringResource(StringsR.string.files_upload_paused),
                        color = c.inkMuted,
                        style = BentoTheme.typography.metadata
                    )
                }
            }
            BentoIconButton(
                BentoIcons.ChevronDown,
                stringResource(if (expanded) StringsR.string.files_upload_collapse else StringsR.string.files_upload_expand),
                { expanded = !expanded },
                dense = true,
                selected = expanded
            )
        }
        if (state.active) ProgressBar(state.progress, Modifier.fillMaxWidth())
        if (expanded) UploadRows(state.rows)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
            when {
                state.active && state.paused -> BentoTextAction(stringResource(StringsR.string.files_upload_resume), onResume)
                state.active -> BentoTextAction(stringResource(StringsR.string.files_upload_pause), onPause)
                else -> BentoTextAction(stringResource(StringsR.string.files_upload_dismiss), onDismiss)
            }
        }
    }
}

private const val MAX_ROWS = 50

@Composable
private fun UploadRows(rows: List<UploadRow>) {
    val c = BentoTheme.colors
    val resources = LocalResources.current
    Column(Modifier.heightIn(max = 240.dp).padding(top = 4.dp)) {
        rows.takeLast(MAX_ROWS).forEach { row ->
            Row(Modifier.padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(row.name, color = c.ink, style = BentoTheme.typography.label, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(
                        stringResource(rowStatus(row.status)),
                        color = if (row.status == UploadStatus.Failed) c.dangerInk else c.inkMuted,
                        style = BentoTheme.typography.metadata
                    )
                }
                row.sizeBytes?.let { Text(BentoFormat.bytes(resources, it), color = c.inkSubtle, style = BentoTheme.typography.metadata) }
            }
        }
    }
}

@Composable
private fun uploadTitle(state: UploadsState): String = when {
    state.active -> pluralCountResource(StringsR.plurals.files_upload_title, state.pendingCount)
    state.failedCount > 0 -> pluralCountResource(StringsR.plurals.files_upload_failed, state.failedCount)
    else -> state.rows.count { it.status != UploadStatus.Failed }.let { pluralCountResource(StringsR.plurals.files_upload_done, it) }
}

private fun rowStatus(status: UploadStatus): Int = when (status) {
    UploadStatus.Queued -> StringsR.string.files_upload_row_queued
    UploadStatus.Copying -> StringsR.string.files_upload_row_copying
    UploadStatus.Done -> StringsR.string.files_upload_row_done
    UploadStatus.Duplicate -> StringsR.string.files_upload_row_duplicate
    UploadStatus.Failed -> StringsR.string.files_upload_row_failed
}

/** Mini player for audio files (play/pause, position, close). */
@Composable
fun AudioMiniPlayer(state: AudioState, onToggle: () -> Unit, onClose: () -> Unit, modifier: Modifier = Modifier) {
    if (!state.visible) return
    val c = BentoTheme.colors
    Row(
        modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp)
            .bentoShadow(BentoElevation.Lg, BentoShapes.lg)
            .clip(BentoShapes.lg)
            .background(c.raised)
            .padding(start = 12.dp, end = 4.dp, top = 6.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        KindIcon(FileKind.Audio)
        Column(Modifier.weight(1f)) {
            Text(state.title, color = c.ink, style = BentoTheme.typography.labelStrong, maxLines = 1, overflow = TextOverflow.Ellipsis)
            val line = if (state.failed) {
                stringResource(StringsR.string.files_audio_failed, state.title)
            } else {
                stringResource(StringsR.string.files_audio_position, clock(state.positionMs), clock(state.durationMs))
            }
            Text(line, color = if (state.failed) c.dangerInk else c.inkMuted, style = BentoTheme.typography.metadata, maxLines = 1)
            if (state.durationMs > 0) {
                ProgressBar(state.positionMs.toFloat() / state.durationMs, Modifier.fillMaxWidth().padding(top = 4.dp), height = 3.dp)
            }
        }
        BentoIconButton(
            if (state.playing) BentoIcons.Pause else BentoIcons.Play,
            stringResource(if (state.playing) StringsR.string.files_audio_pause else StringsR.string.files_audio_play),
            onToggle
        )
        BentoIconButton(BentoIcons.X, stringResource(StringsR.string.files_audio_close), onClose, dense = true)
    }
}

fun clock(ms: Long): String {
    val total = (ms / 1000).coerceAtLeast(0)
    val hours = total / 3600
    val minutes = (total % 3600) / 60
    val seconds = total % 60
    return if (hours > 0) "%d:%02d:%02d".format(hours, minutes, seconds) else "%d:%02d".format(minutes, seconds)
}
