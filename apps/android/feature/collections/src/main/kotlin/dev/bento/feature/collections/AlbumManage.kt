package dev.bento.feature.collections

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoDialog
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.BentoIconButton
import dev.bento.designsystem.component.BentoSheet
import dev.bento.designsystem.component.BentoTextField
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.strings.R as StringsR

/** Album detail overflow: `Cambiar nombre` and `Eliminar álbum` (the cover is picked from the selection bar). */
@Composable
fun AlbumMenu(onRename: () -> Unit, onDelete: () -> Unit) {
    val c = BentoTheme.colors
    var open by remember { mutableStateOf(false) }
    Box {
        BentoIconButton(
            BentoIcons.EllipsisVertical,
            stringResource(StringsR.string.collections_album_options),
            { open = true },
            modifier = Modifier.testTag(CollectionsTestTags.AlbumMenu)
        )
        DropdownMenu(expanded = open, onDismissRequest = { open = false }, shape = BentoShapes.lg, containerColor = c.raised) {
            @Composable
            fun item(icon: ImageVector, label: String, danger: Boolean = false, onClick: () -> Unit) = DropdownMenuItem(
                text = { Text(label, color = if (danger) c.dangerInk else c.ink, style = BentoTheme.typography.body) },
                leadingIcon = { BentoIcon(icon, null, tint = if (danger) c.dangerInk else c.ink) },
                onClick = {
                    open = false
                    onClick()
                },
                modifier = Modifier.heightIn(min = 48.dp)
            )
            item(BentoIcons.PencilLine, stringResource(StringsR.string.collections_album_rename), onClick = onRename)
            item(BentoIcons.Trash2, stringResource(StringsR.string.collections_album_delete), danger = true, onClick = onDelete)
        }
    }
}

/** Cambiar nombre: the field opens with the current title; the new name reaches every device. */
@Composable
fun AlbumRenameSheet(current: String, busy: Boolean, onSave: (String) -> Unit, onDismiss: () -> Unit) {
    BentoSheet(onDismissRequest = onDismiss, title = stringResource(StringsR.string.collections_album_rename)) {
        AlbumRenameBody(current, busy, onSave)
    }
}

@Composable
internal fun AlbumRenameBody(current: String, busy: Boolean, onSave: (String) -> Unit) {
    val name = rememberTextFieldState(current)
    var error by remember { mutableStateOf<String?>(null) }
    val missing = stringResource(StringsR.string.collections_create_name_error)
    BentoTextField(
        state = name,
        label = stringResource(StringsR.string.collections_create_title),
        error = error,
        modifier = Modifier.fillMaxWidth()
    )
    BentoButton(
        stringResource(StringsR.string.common_action_save),
        {
            val title = name.text.toString().trim()
            if (title.isEmpty()) error = missing else onSave(title)
        },
        variant = BentoButtonVariant.Primary,
        loading = busy,
        modifier = Modifier.fillMaxWidth().padding(top = 12.dp)
    )
}

/** Eliminar álbum: says that the photos stay; only the album goes, on every device. */
@Composable
fun AlbumDeleteDialog(title: String, onConfirm: () -> Unit, onDismiss: () -> Unit) {
    BentoDialog(
        title = stringResource(StringsR.string.collections_album_delete_title, title),
        consequence = stringResource(StringsR.string.collections_album_delete_body),
        confirmLabel = stringResource(StringsR.string.collections_album_delete),
        onConfirm = onConfirm,
        onDismissRequest = onDismiss
    )
}
