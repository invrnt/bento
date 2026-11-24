package dev.bento.feature.viewer

import androidx.compose.animation.AnimatedVisibilityScope
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import coil3.compose.AsyncImagePainter
import coil3.compose.rememberAsyncImagePainter
import coil3.network.HttpException
import coil3.request.ImageRequest
import coil3.request.crossfade
import dev.bento.api.BentoImage
import dev.bento.api.ThumbnailSize
import dev.bento.api.generated.AssetResponse
import dev.bento.designsystem.component.bentoMediaKey
import dev.bento.designsystem.component.bentoSharedMedia
import dev.bento.feature.photos.LocalBentoImageLoader
import java.io.IOException
import me.saket.telephoto.zoomable.ZoomSpec
import me.saket.telephoto.zoomable.coil3.ZoomableAsyncImage
import me.saket.telephoto.zoomable.rememberZoomableImageState
import me.saket.telephoto.zoomable.rememberZoomableState

/** Fitted aspect ratio of an asset (square until the backend knows its size). */
fun aspectOf(asset: AssetResponse): Float {
    val w = asset.width ?: return 1f
    val h = asset.height ?: return 1f
    return if (w > 0 && h > 0) w.toFloat() / h else 1f
}

/** The tile's thumbnail at the grid's bucket (memory hit → the viewer's first frame is instant). */
@Composable
fun rememberPosterPainter(asset: AssetResponse): androidx.compose.ui.graphics.painter.Painter? {
    val loader = LocalBentoImageLoader.current ?: return null
    val context = LocalContext.current
    val request = remember(asset.id, asset.thumbnailEtag) {
        ImageRequest.Builder(context).data(BentoImage.thumbnail(asset.id, asset.thumbnailEtag)).size(ThumbnailSize.MEDIUM.px).build()
    }
    val painter = rememberAsyncImagePainter(request, loader)
    val state by painter.state.collectAsState()
    return painter.takeIf { state is AsyncImagePainter.State.Success }
}

/**
 * The shared element: a box with the photo's aspect ratio, cropped like the tile, so the transform from the square
 * tile "uncrops" into the full photo (and back on dismiss).
 */
@Composable
fun SharedPoster(asset: AssetResponse, animatedScope: AnimatedVisibilityScope?, shared: Boolean, modifier: Modifier = Modifier) {
    val poster = rememberPosterPainter(asset)
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Box(
            Modifier
                .aspectRatio(aspectOf(asset))
                .bentoSharedMedia(bentoMediaKey(asset.id), animatedScope, visible = shared)
        ) {
            if (poster !=
                null
            ) {
                Image(poster, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            }
        }
    }
}

/** Per-page load signals for [ProgressiveQuality] and the offline notice. */
class PhotoLoadSignals(val stage: ImageStage, val offline: Boolean)

/**
 * A photo page: shared poster (thumbnail) → preview → original (≤ 40 MP, subsampled by Telephoto), crossfaded without
 * flicker. Telephoto handles pinch, double-tap and one-finger (double-tap-and-drag) zoom; it is hidden while the
 * shared transform runs so only one image is ever visible.
 */
// Three stacked layers with their load flags; splitting them would scatter the progressive-quality state.
@Suppress("LongParameterList", "CyclomaticComplexMethod")
@Composable
fun PhotoPage(
    asset: AssetResponse,
    animatedScope: AnimatedVisibilityScope?,
    sharedActive: Boolean,
    contentDescription: String,
    onTap: () -> Unit,
    onZoomChanged: (Boolean) -> Unit,
    onSignals: (PhotoLoadSignals) -> Unit,
    modifier: Modifier = Modifier
) {
    val loader = LocalBentoImageLoader.current
    val context = LocalContext.current
    val transitioning = animatedScope?.transition?.let { it.isRunning || it.currentState != it.targetState } ?: false
    val wantsOriginal = ProgressiveQuality.wantsOriginal(asset.width, asset.height, asset.mimeType)
    var previewLoaded by remember(asset.id) { mutableStateOf(false) }
    var originalLoaded by remember(asset.id) { mutableStateOf(false) }
    var originalFailed by remember(asset.id) { mutableStateOf(false) }
    var networkError by remember(asset.id) { mutableStateOf(false) }
    val signals by rememberUpdatedState(onSignals)

    Box(modifier.fillMaxSize().testTag(ViewerTestTags.page(asset.id))) {
        SharedPoster(asset, animatedScope, sharedActive)

        if (loader != null) {
            // Preview layer (the step between the thumbnail and the original).
            val previewRequest = remember(asset.id) { ImageRequest.Builder(context).data(BentoImage.preview(asset.id)).build() }
            val preview = rememberAsyncImagePainter(previewRequest, loader)
            val previewState by preview.state.collectAsState()
            LaunchedEffect(previewState) { if (previewState is AsyncImagePainter.State.Success) previewLoaded = true }
            val previewAlpha by animateFloatAsState(if (previewLoaded && !originalLoaded) 1f else 0f, label = "preview")
            if (!transitioning && previewLoaded && !originalLoaded) {
                Box(Modifier.fillMaxSize().graphicsLayer { alpha = previewAlpha }, contentAlignment = Alignment.Center) {
                    Image(
                        preview,
                        contentDescription = null,
                        contentScale = ContentScale.Fit,
                        modifier = Modifier.aspectRatio(aspectOf(asset))
                    )
                }
            }

            // Zoomable top layer: the original (or the preview for > 40 MP / formats the decoder cannot tile).
            val zoomable = rememberZoomableImageState(rememberZoomableState(zoomSpec = ZoomSpec(maxZoomFactor = 8f)))
            LaunchedEffect(zoomable) {
                snapshotFlow { (zoomable.zoomableState.zoomFraction ?: 0f) > 0.01f }.collect { onZoomChanged(it) }
            }
            val request = remember(asset.id, wantsOriginal) {
                ImageRequest.Builder(context)
                    .data(if (wantsOriginal) BentoImage.original(asset.id, asset.thumbnailEtag) else BentoImage.preview(asset.id))
                    .crossfade(180)
                    .listener(
                        onSuccess = { _, _ -> originalLoaded = true },
                        onError = { _, result ->
                            originalFailed = true
                            val error = result.throwable
                            networkError = error is IOException || (error is HttpException && error.response.code in 500..504)
                        }
                    )
                    .build()
            }
            ZoomableAsyncImage(
                model = request,
                contentDescription = contentDescription,
                imageLoader = loader,
                state = zoomable,
                contentScale = ContentScale.Fit,
                onClick = { onTap() },
                modifier = Modifier.fillMaxSize().graphicsLayer { alpha = if (transitioning) 0f else 1f }
            )
        }
    }
    val stage = ProgressiveQuality.stage(previewLoaded, originalLoaded)
    LaunchedEffect(stage, originalFailed, networkError) {
        signals(PhotoLoadSignals(stage, ProgressiveQuality.offline(originalFailed, networkError, stage)))
    }
}
