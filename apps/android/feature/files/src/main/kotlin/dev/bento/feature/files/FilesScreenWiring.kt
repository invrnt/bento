package dev.bento.feature.files

import android.app.Activity
import android.content.Context
import android.content.res.Resources
import androidx.activity.compose.LocalActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalResources
import com.google.mlkit.vision.documentscanner.GmsDocumentScanningResult
import dev.bento.api.generated.DriveItemResponse
import dev.bento.designsystem.component.BentoSnackbarHostState
import dev.bento.designsystem.component.BentoSnackbarTone
import dev.bento.strings.R as StringsR
import java.time.LocalDateTime
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/** Where Archivos leads outside itself (the shell decides). */
class FilesNavigation(
    val onOpenViewer: (String) -> Unit,
    val onOpenDocument: (String) -> Unit,
    val onSearch: (folderId: String?, folderName: String?) -> Unit
)

/** System pickers and documents Archivos launches (SAF, photo picker, document tree, scanner, create document). */
class FilesLaunchers internal constructor(
    private val launchFiles: () -> Unit,
    private val launchMedia: () -> Unit,
    private val launchTree: () -> Unit,
    private val launchScan: () -> Unit,
    private val launchCreate: (DriveItemResponse) -> Unit
) {
    fun pickFiles() = launchFiles()

    fun pickMedia() = launchMedia()

    fun pickTree() = launchTree()

    fun scan() = launchScan()

    fun createDocument(item: DriveItemResponse) = launchCreate(item)
}

@Composable
internal fun rememberFilesLaunchers(viewModel: FilesViewModel, contentFiles: ContentFiles?): FilesLaunchers {
    val context = LocalContext.current
    val activity = LocalActivity.current
    val resources = LocalResources.current
    val pending = remember { arrayOfNulls<DriveItemResponse>(1) }
    val pickFiles = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        viewModel.upload(uris.map { PickedContent(it.toString()) })
    }
    val pickMedia = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia()) { uris ->
        viewModel.upload(uris.map { PickedContent(it.toString()) })
    }
    val pickTree = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) viewModel.uploadTree(uri.toString())
    }
    val scan = rememberLauncherForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) { result ->
        val pdf = GmsDocumentScanningResult.fromActivityResultIntent(result.data)?.pdf
        if (result.resultCode == Activity.RESULT_OK && pdf != null) {
            viewModel.uploadScan(
                pdf.uri.toString(),
                DisplayNames.scan(resources.getString(StringsR.string.files_scan_prefix), LocalDateTime.now())
            )
        }
    }
    val create = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("*/*")) { uri ->
        val item = pending[0]
        pending[0] = null
        if (uri != null && item != null && contentFiles != null) {
            viewModel.saveTo(item) { assetId, progress -> contentFiles.saveTo(context.contentResolver, uri, assetId, progress) }
        }
    }
    return remember(viewModel, contentFiles, activity) {
        FilesLaunchers(
            launchFiles = { runCatching { pickFiles.launch(arrayOf("*/*")) } },
            launchMedia = {
                runCatching { pickMedia.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageAndVideo)) }
            },
            launchTree = { runCatching { pickTree.launch(null) } },
            launchScan = {
                viewModel.dismissSheet()
                if (activity == null) {
                    viewModel.message(UiText.of(StringsR.string.files_scan_unavailable))
                } else {
                    scanner().getStartScanIntent(activity)
                        .addOnSuccessListener { sender -> scan.launch(IntentSenderRequest.Builder(sender).build()) }
                        .addOnFailureListener { viewModel.message(UiText.of(StringsR.string.files_scan_unavailable)) }
                }
            },
            launchCreate = { item ->
                pending[0] = item
                runCatching { create.launch(DisplayNames.file(item.name)) }
            }
        )
    }
}

/** Performs the ViewModel's one-shot effects with Android APIs. */
@Composable
internal fun FilesEffects(
    viewModel: FilesViewModel,
    snackbar: BentoSnackbarHostState,
    launchers: FilesLaunchers,
    navigation: FilesNavigation
) {
    val context = LocalContext.current
    val resources = LocalResources.current
    val scope = rememberCoroutineScope()
    val contentFiles =
        remember(context) { runCatching { dev.bento.feature.files.di.FilesEntryPoint.get(context).contentFiles() }.getOrNull() }
    LaunchedEffect(viewModel) {
        viewModel.effect.collect { effect ->
            when (effect) {
                is FilesEffect.Message -> scope.showMessage(snackbar, resources, effect.message)

                is FilesEffect.OpenViewer -> navigation.onOpenViewer(effect.assetId)

                is FilesEffect.OpenDocument -> navigation.onOpenDocument(effect.assetId)

                is FilesEffect.OpenWith -> if (!startExternal(context, viewIntent(context, effect.file, effect.mimeType))) {
                    viewModel.message(UiText.of(StringsR.string.files_open_with_none))
                }

                is FilesEffect.Share -> startExternal(context, shareIntent(context, effect.files))

                is FilesEffect.CreateDocument -> launchers.createDocument(effect.item)

                is FilesEffect.SaveToDownloads -> saveToDownloads(context, viewModel, contentFiles, effect.items)

                is FilesEffect.Search -> navigation.onSearch(effect.folderId, effect.folderName)
            }
        }
    }
}

private fun CoroutineScope.showMessage(snackbar: BentoSnackbarHostState, resources: Resources, message: FilesMessage) = launch {
    val text = message.text.resolve(resources)
    val undo = message.undo
    if (undo != null) {
        if (snackbar.showUndo(text, resources.getString(StringsR.string.common_action_undo))) undo.undo()
    } else {
        snackbar.show(text, tone = if (message.danger) BentoSnackbarTone.Danger else BentoSnackbarTone.Neutral)
    }
}

private fun saveToDownloads(context: Context, viewModel: FilesViewModel, contentFiles: ContentFiles?, items: List<DriveItemResponse>) {
    if (contentFiles == null) return
    items.forEach { item ->
        val target = downloadsTarget(context, item) ?: return@forEach
        viewModel.saveTo(item) { assetId, progress -> contentFiles.saveTo(context.contentResolver, target, assetId, progress) }
    }
}

/** Wires every Archivos action to the ViewModel. */
internal fun filesActions(viewModel: FilesViewModel, onSearch: () -> Unit) = FilesActions(
    onOpen = viewModel::open,
    onSelect = viewModel::toggleSelection,
    onMenu = { viewModel.showSheet(FilesSheet.ItemMenu(it)) },
    onShare = viewModel::share,
    onFavorite = { viewModel.setFavorite(it, it.asset?.favorite != true) },
    onTrash = viewModel::trash,
    onMove = { viewModel.showSheet(FilesSheet.Move(it)) },
    onDownload = viewModel::download,
    onPin = viewModel::setPinned,
    onNavigate = viewModel::navigateTo,
    onRetry = { viewModel.load() },
    onNew = { viewModel.showSheet(FilesSheet.New) },
    onSort = { viewModel.showSheet(FilesSheet.Sort) },
    onToggleLayout = viewModel::toggleLayout,
    onSearch = onSearch,
    onSearchHere = viewModel::searchHere,
    onSelectAll = viewModel::selectAll,
    onClearSelection = viewModel::clearSelection,
    onToggleTree = viewModel::toggleExpanded,
    onDrop = viewModel::upload,
    onPauseUploads = viewModel.uploads::pause,
    onResumeUploads = viewModel.uploads::resume,
    onDismissUploads = viewModel.uploads::clearFinished,
    onToggleAudio = viewModel.audio::toggle,
    onCloseAudio = viewModel.audio::close,
    onCancelPreparing = viewModel::cancelPreparing
)
