package dev.bento.feature.viewer

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.testTagsAsResourceId
import androidx.compose.ui.unit.dp
import dev.bento.api.generated.AssetResponse
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoChip
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.BentoIconButton
import dev.bento.designsystem.component.BentoSheet
import dev.bento.designsystem.component.BentoTextField
import dev.bento.designsystem.component.ListRow
import dev.bento.designsystem.component.SegmentOption
import dev.bento.designsystem.component.SegmentedButtons
import dev.bento.designsystem.format.BentoFormat
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.photos.MediaFormat
import dev.bento.strings.R as StringsR
import java.util.Locale

/** Callbacks of the info sheet/pane. */
class InfoCallbacks(
    val onRename: () -> Unit,
    val onOpenFolder: (String) -> Unit,
    val onOpenMaps: (Double, Double) -> Unit,
    val onOpenActivity: () -> Unit
)

/**
 * Info (product/android.md §4.4): date and time, filename (editable), size and dimensions, camera/lens/exposure from
 * EXIF, location with `Abrir en Mapas`, folder path (tap navigates), albums, and the storage line.
 */
@Suppress("LongMethod", "CyclomaticComplexMethod")
@Composable
fun ViewerInfoContent(asset: AssetResponse, info: ViewerInfo?, callbacks: InfoCallbacks, modifier: Modifier = Modifier) {
    val c = BentoTheme.colors
    val locale = LocalConfiguration.current.locales[0]
    val context = LocalContext.current
    // The sheet is its own window: expose tags as resource ids here too (UiAutomator journeys).
    Column(modifier.fillMaxWidth().semantics { testTagsAsResourceId = true }.testTag(ViewerTestTags.Info)) {
        Row(Modifier.fillMaxWidth().padding(bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(
                asset.filename,
                color = c.ink,
                style = BentoTheme.typography.sectionTitle,
                modifier = Modifier.weight(1f).semantics { heading() }
            )
            BentoIconButton(BentoIcons.PencilLine, stringResource(StringsR.string.viewer_info_edit_name), callbacks.onRename)
        }
        ListRow(
            headline = MediaFormat.dateTime(asset.takenAt ?: asset.createdAt, locale),
            supporting = stringResource(StringsR.string.viewer_info_taken),
            leading = { BentoIcon(BentoIcons.Info, null, tint = c.inkMuted) }
        )
        ListRow(
            headline = sizeLine(asset, context, locale),
            supporting = stringResource(StringsR.string.viewer_info_size),
            leading = { BentoIcon(if (MediaFormat.isVideo(asset)) BentoIcons.FileVideo else BentoIcons.FileImage, null, tint = c.inkMuted) }
        )
        val exif = info?.exif
        if (exif?.camera != null || exif?.exposure != null) {
            ListRow(
                headline = listOfNotNull(exif.camera, exif.lens).joinToString(" · ").ifEmpty { exif.exposure.orEmpty() },
                supporting =
                    exif.exposure?.takeIf {
                        exif.camera != null || exif.lens != null
                    } ?: stringResource(StringsR.string.viewer_info_camera),
                leading = { BentoIcon(BentoIcons.Camera, null, tint = c.inkMuted) }
            )
        }
        if (exif?.hasLocation == true) {
            val lat = exif.latitude!!
            val lng = exif.longitude!!
            ListRow(
                headline = "%.5f, %.5f".format(Locale.ROOT, lat, lng),
                supporting = stringResource(StringsR.string.viewer_info_location),
                leading = { BentoIcon(BentoIcons.MapPin, null, tint = c.inkMuted) },
                trailing = {
                    BentoButton(
                        stringResource(StringsR.string.viewer_info_open_maps),
                        { callbacks.onOpenMaps(lat, lng) },
                        variant = BentoButtonVariant.Ghost,
                        trailingIcon = BentoIcons.ExternalLink
                    )
                }
            )
        }
        val folderId = asset.folderId
        if (folderId != null) {
            ListRow(
                headline = info?.folderPath ?: stringResource(StringsR.string.viewer_info_folder),
                supporting = stringResource(StringsR.string.viewer_info_folder),
                leading = { BentoIcon(BentoIcons.FolderClosed, null, tint = c.inkMuted) },
                trailing = { BentoIcon(BentoIcons.ChevronRight, null, tint = c.inkSubtle) },
                onClick = { callbacks.onOpenFolder(folderId) },
                onClickLabel = stringResource(StringsR.string.viewer_info_folder_open)
            )
        }
        if (!info?.albums.isNullOrEmpty()) {
            Text(
                stringResource(StringsR.string.viewer_info_albums),
                color = c.inkMuted,
                style = BentoTheme.typography.label,
                modifier = Modifier.padding(start = 16.dp, top = 8.dp)
            )
            Row(
                Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                info.albums.forEach { album -> BentoChip(album.title, onClick = {}, leadingIcon = BentoIcons.SquareLibrary) }
            }
        }
        val storage = storageLine(asset.remoteState)
        ListRow(
            headline = stringResource(
                when (storage) {
                    StorageLine.Remote -> StringsR.string.viewer_storage_remote
                    StorageLine.LocalOnly -> StringsR.string.viewer_storage_local
                    StorageLine.Uploading -> StringsR.string.viewer_storage_uploading
                    StorageLine.Failed -> StringsR.string.viewer_storage_failed
                }
            ),
            supporting = stringResource(StringsR.string.viewer_info_storage),
            leading = {
                BentoIcon(
                    when (storage) {
                        StorageLine.Remote -> BentoIcons.Lock
                        StorageLine.LocalOnly -> BentoIcons.Smartphone
                        StorageLine.Uploading -> BentoIcons.CloudUpload
                        StorageLine.Failed -> BentoIcons.CloudOff
                    },
                    null,
                    tint = if (storage == StorageLine.Failed) c.dangerInk else c.inkMuted
                )
            },
            onClick = if (storage == StorageLine.Failed) callbacks.onOpenActivity else null,
            onClickLabel = if (storage == StorageLine.Failed) stringResource(StringsR.string.viewer_open_activity) else null
        )
        val availability = availabilityOf(asset, info?.pinned)
        ListRow(
            headline = stringResource(
                when (availability) {
                    Availability.Pinned -> StringsR.string.viewer_availability_pinned
                    Availability.OnDevice -> StringsR.string.viewer_availability_on_device
                    Availability.NeedsConnection -> StringsR.string.viewer_availability_online
                }
            ),
            supporting = stringResource(StringsR.string.viewer_info_offline),
            leading = {
                BentoIcon(
                    when (availability) {
                        Availability.Pinned -> BentoIcons.Pin
                        Availability.OnDevice -> BentoIcons.FileDown
                        Availability.NeedsConnection -> BentoIcons.Cloud
                    },
                    null,
                    tint = if (availability == Availability.Pinned) c.accent else c.inkMuted
                )
            },
            modifier = Modifier.testTag(ViewerTestTags.Availability)
        )
    }
}

private fun sizeLine(asset: AssetResponse, context: android.content.Context, locale: Locale): String {
    val parts = mutableListOf(BentoFormat.bytes(context.resources, asset.sizeBytes, locale))
    val w = asset.width ?: 0
    val h = asset.height ?: 0
    if (w > 0 && h > 0) {
        val mp = java.text.NumberFormat.getNumberInstance(locale).apply { maximumFractionDigits = 1 }.format(w * h / 1_000_000.0)
        parts += context.getString(StringsR.string.viewer_info_dimensions, w.toString(), h.toString(), mp)
    }
    asset.durationMs?.let { parts += context.getString(StringsR.string.viewer_info_duration, MediaFormat.duration(it)) }
    return parts.joinToString(" · ")
}

@Composable
fun ViewerInfoSheet(asset: AssetResponse, info: ViewerInfo?, callbacks: InfoCallbacks, onDismiss: () -> Unit) {
    BentoSheet(onDismissRequest = onDismiss, title = stringResource(StringsR.string.viewer_info)) {
        ViewerInfoContent(asset, info, callbacks, Modifier.verticalScroll(rememberScrollState()))
    }
}

/** Renombrar: the name field opens with the current name; `Guardar` keeps the extension the person typed. */
@Composable
fun RenameSheet(current: String, onSave: (String) -> Unit, onDismiss: () -> Unit) {
    val state = rememberTextFieldState(current)
    var error by remember { mutableStateOf<String?>(null) }
    val missing = stringResource(StringsR.string.collections_create_name_error)
    BentoSheet(onDismissRequest = onDismiss, title = stringResource(StringsR.string.viewer_rename_title)) {
        BentoTextField(
            state = state,
            label = stringResource(StringsR.string.viewer_info_name),
            error = error,
            modifier = Modifier.fillMaxWidth()
        )
        BentoButton(
            stringResource(StringsR.string.common_action_save),
            {
                val name = state.text.toString().trim()
                if (name.isEmpty()) error = missing else onSave(name)
            },
            variant = BentoButtonVariant.Primary,
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp)
        )
    }
}

@Composable
fun SpeedSheet(current: Float, onSelect: (Float) -> Unit, onDismiss: () -> Unit) {
    val normal = stringResource(StringsR.string.viewer_speed_normal)
    BentoSheet(onDismissRequest = onDismiss, title = stringResource(StringsR.string.viewer_action_speed)) {
        SegmentedButtons(
            options = listOf(0.5f, 1f, 1.5f, 2f).map {
                SegmentOption(
                    it,
                    if (it ==
                        1f
                    ) {
                        normal
                    } else {
                        "${it.toString().removeSuffix(".0")}×"
                    }
                )
            },
            selected = current,
            onSelect = onSelect,
            modifier = Modifier.fillMaxWidth().padding(bottom = 16.dp)
        )
    }
}
