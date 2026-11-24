package dev.bento.feature.photos

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ripple
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import coil3.ImageLoader
import coil3.compose.AsyncImagePainter
import coil3.compose.rememberAsyncImagePainter
import coil3.request.ImageRequest
import dev.bento.api.BentoImage
import dev.bento.api.generated.AssetResponse
import dev.bento.designsystem.component.BentoFavorite
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.BentoIconSize
import dev.bento.designsystem.component.Thumbnail
import dev.bento.designsystem.component.VideoBadge
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.strings.R as StringsR

/** The app's Coil loader (Bento fetcher + caches). Null in previews/tests without images: tiles show placeholders. */
val LocalBentoImageLoader = staticCompositionLocalOf<ImageLoader?> { null }

/** Upload state shown on tiles (api/android-endpoints.md §5 `remote_state`); no glyph means "safe in your cloud". */
enum class UploadBadge { None, Pending, Failed }

fun uploadBadge(asset: AssetResponse): UploadBadge = when (asset.remoteState) {
    "local_only", "uploading" -> UploadBadge.Pending
    "failed" -> UploadBadge.Failed
    else -> UploadBadge.None
}

/** Actions a tile offers to TalkBack/Switch Access so no gesture is required (product/android.md §12). */
class TileActions(
    val onOpen: () -> Unit,
    val onToggleSelect: () -> Unit,
    val onFavorite: (() -> Unit)?,
    val onShare: (() -> Unit)?,
    val onDelete: (() -> Unit)?
)

object MediaTestTags {
    const val Grid = "photos:grid"
    const val StickyHeader = "photos:sticky-header"
    const val FastScroller = "photos:fast-scroller"
    const val FastScrollerBubble = "photos:fast-scroller-bubble"
    const val SelectionBar = "photos:selection-bar"
    fun tile(id: String) = "photos:tile:$id"
    fun header(key: String) = "photos:header:$key"
}

/** "Foto, 12 de marzo de 2024, favorita, pendiente de respaldo". */
@Composable
fun tileDescription(asset: AssetResponse, date: String, selected: Boolean): String =
    TileLabels.current().describe(asset, date, selected, LocalConfiguration.current.locales[0])

/** Coil painter for a thumbnail at [sizePx]; null until pixels are available (the tile shows its placeholder). */
@Composable
fun rememberThumbnailPainter(asset: AssetResponse, sizePx: Int): androidx.compose.ui.graphics.painter.Painter? {
    val loader = LocalBentoImageLoader.current ?: return null
    val context = LocalContext.current
    val request = remember(asset.id, asset.thumbnailEtag, sizePx) {
        ImageRequest.Builder(context)
            .data(BentoImage.thumbnail(asset.id, asset.thumbnailEtag))
            // Exactly a stored bucket (256/512/1024): the viewer asks for the same key, so its first frame is a memory hit.
            .size(dev.bento.api.ThumbnailSize.atLeast(sizePx).px)
            .build()
    }
    val painter = rememberAsyncImagePainter(request, loader)
    val state by painter.state.collectAsState()
    return painter.takeIf { state is AsyncImagePainter.State.Success }
}

/**
 * A grid tile: square thumbnail, overlays bottom-left (duration, favorite, upload state) on a dark veil for
 * legibility, selection inset and check. Tap opens (or toggles in selection mode); long-press/drag belongs to the grid.
 */
@Composable
fun MediaTile(
    asset: AssetResponse,
    date: String,
    sizePx: Int,
    selected: Boolean,
    selectionMode: Boolean,
    actions: TileActions,
    labels: TileLabels,
    modifier: Modifier = Modifier
) {
    val painter = rememberThumbnailPainter(asset, sizePx)
    val interaction = remember { MutableInteractionSource() }
    Thumbnail(
        painter = painter,
        contentDescription = null,
        selected = selected,
        selectionMode = selectionMode,
        modifier = modifier
            .testTag(MediaTestTags.tile(asset.id))
            .clickable(
                interactionSource = interaction,
                indication = ripple(),
                onClickLabel = if (selectionMode) labels.select else labels.open,
                onClick = if (selectionMode) actions.onToggleSelect else actions.onOpen
            )
            .semantics(mergeDescendants = true) {
                // Built only when semantics are read (TalkBack, tests), never on every bind while flinging.
                contentDescription = labels.describe(asset, date, selected, labels.locale)
                this.selected = selected
                role = Role.Image
                customActions = buildList {
                    if (!selectionMode) add(CustomAccessibilityAction(labels.open) { actions.onOpen().let { true } })
                    add(
                        CustomAccessibilityAction(if (selected) labels.unselect else labels.select) {
                            actions.onToggleSelect().let { true }
                        }
                    )
                    actions.onFavorite?.let {
                        add(CustomAccessibilityAction(if (asset.favorite) labels.unfavorite else labels.favorite) { it().let { true } })
                    }
                    actions.onShare?.let { add(CustomAccessibilityAction(labels.share) { it().let { true } }) }
                    actions.onDelete?.let { add(CustomAccessibilityAction(labels.delete) { it().let { true } }) }
                }
            }
    ) {
        TileOverlays(asset)
    }
}

@Composable
private fun androidx.compose.foundation.layout.BoxScope.TileOverlays(asset: AssetResponse) {
    val badge = uploadBadge(asset)
    val video = MediaFormat.isVideo(asset)
    if (!video && !asset.favorite && badge == UploadBadge.None) return
    val c = BentoTheme.colors
    Row(
        Modifier.align(Alignment.BottomStart).padding(6.dp).clearAndSetSemantics {},
        horizontalArrangement = Arrangement.spacedBy(4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        if (video) VideoBadge(asset.durationMs?.let(MediaFormat::duration))
        if (asset.favorite) {
            androidx.compose.foundation.layout.Box(Modifier.clip(BentoShapesCircle).background(c.black.copy(alpha = 0.5f)).padding(3.dp)) {
                BentoFavorite(true, size = BentoIconSize.Dense, onMedia = true)
            }
        }
        if (badge != UploadBadge.None) {
            androidx.compose.foundation.layout.Box(
                Modifier
                    .clip(BentoShapesCircle)
                    .background(c.black.copy(alpha = 0.5f))
                    .padding(3.dp)
            ) {
                BentoIcon(
                    if (badge == UploadBadge.Pending) BentoIcons.CloudUpload else BentoIcons.CloudOff,
                    null,
                    tint = c.white,
                    size = BentoIconSize.Dense
                )
            }
        }
    }
}

private val BentoShapesCircle = androidx.compose.foundation.shape.CircleShape

/** Localized labels for tile actions, resolved once per composition. */
class TileLabels(
    val locale: java.util.Locale,
    private val photo: String,
    private val video: String,
    private val videoWithDuration: String,
    private val favoriteState: String,
    private val pending: String,
    private val uploading: String,
    private val failed: String,
    private val selectedState: String,
    val open: String,
    val select: String,
    val unselect: String,
    val favorite: String,
    val unfavorite: String,
    val share: String,
    val delete: String
) {
    fun describe(asset: AssetResponse, date: String, selected: Boolean, locale: java.util.Locale): String = buildList {
        add(
            when {
                !MediaFormat.isVideo(asset) -> photo
                asset.durationMs != null -> videoWithDuration.format(MediaFormat.duration(asset.durationMs!!))
                else -> video
            }
        )
        add(MediaFormat.longDate(date, locale))
        if (asset.favorite) add(favoriteState)
        when (asset.remoteState) {
            "local_only" -> add(pending)
            "uploading" -> add(uploading)
            "failed" -> add(failed)
        }
        if (selected) add(selectedState)
    }.joinToString(", ")

    companion object {
        @Composable
        fun current(): TileLabels = TileLabels(
            locale = LocalConfiguration.current.locales[0],
            photo = stringResource(StringsR.string.photos_tile_photo),
            video = stringResource(StringsR.string.photos_tile_video_plain),
            videoWithDuration = stringResource(StringsR.string.photos_tile_video, "%1\$s"),
            favoriteState = stringResource(StringsR.string.photos_tile_favorite),
            pending = stringResource(StringsR.string.photos_tile_pending),
            uploading = stringResource(StringsR.string.photos_tile_uploading),
            failed = stringResource(StringsR.string.photos_tile_failed),
            selectedState = stringResource(StringsR.string.photos_tile_selected),
            open = stringResource(StringsR.string.photos_action_open),
            select = stringResource(StringsR.string.common_action_select),
            unselect = stringResource(StringsR.string.photos_action_unselect),
            favorite = stringResource(StringsR.string.photos_action_favorite_add),
            unfavorite = stringResource(StringsR.string.photos_action_favorite_remove),
            share = stringResource(StringsR.string.common_action_share),
            delete = stringResource(StringsR.string.common_action_delete)
        )
    }
}
