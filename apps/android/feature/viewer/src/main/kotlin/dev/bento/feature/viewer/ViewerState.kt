package dev.bento.feature.viewer

import androidx.compose.runtime.Immutable

/** Chrome and gesture state of the viewer (product/android.md §4.4). Pure; JVM tested. */
@Immutable
data class ViewerChrome(
    val chromeVisible: Boolean = true,
    val infoOpen: Boolean = false,
    val zoomed: Boolean = false,
    /** Swipe-down progress 0..1 while the finger drags (the photo shrinks, the background fades). */
    val dismissProgress: Float = 0f,
    val dismissed: Boolean = false
) {
    /** Paging is locked while zoomed or dismissing, so pans never flip pages. */
    val pagingEnabled: Boolean get() = !zoomed && dismissProgress == 0f && !dismissed

    /** Swipe gestures (down: dismiss, up: info) only at fit zoom. */
    val verticalGesturesEnabled: Boolean get() = !zoomed && !infoOpen && !dismissed
}

sealed interface ViewerIntent {
    data object Tap : ViewerIntent

    data object SwipeUp : ViewerIntent

    data object CloseInfo : ViewerIntent

    data class Zoom(val zoomed: Boolean) : ViewerIntent

    data class DismissDrag(val progress: Float) : ViewerIntent

    /** Finger lifted: [commit] when past the threshold or flung down. */
    data class DismissRelease(val commit: Boolean) : ViewerIntent

    /** Page changed: zoom resets on the new page. */
    data object PageChanged : ViewerIntent
}

object ViewerReducer {
    /** Distance fraction of the screen height (or a fling) that commits a swipe-down dismiss. */
    const val DISMISS_THRESHOLD = 0.18f

    fun reduce(state: ViewerChrome, intent: ViewerIntent): ViewerChrome = when (intent) {
        ViewerIntent.Tap -> if (state.infoOpen) state.copy(infoOpen = false) else state.copy(chromeVisible = !state.chromeVisible)

        ViewerIntent.SwipeUp -> if (state.verticalGesturesEnabled) state.copy(infoOpen = true, chromeVisible = true) else state

        ViewerIntent.CloseInfo -> state.copy(infoOpen = false)

        is ViewerIntent.Zoom -> state.copy(zoomed = intent.zoomed, chromeVisible = if (intent.zoomed) false else state.chromeVisible)

        is ViewerIntent.DismissDrag -> if (state.verticalGesturesEnabled) {
            state.copy(
                dismissProgress = intent.progress.coerceIn(0f, 1f)
            )
        } else {
            state
        }

        is ViewerIntent.DismissRelease -> if (intent.commit) state.copy(dismissed = true) else state.copy(dismissProgress = 0f)

        ViewerIntent.PageChanged -> state.copy(zoomed = false, dismissProgress = 0f)
    }

    fun shouldCommitDismiss(dragFraction: Float, velocityPxPerSec: Float, flingThreshold: Float = 1_400f): Boolean =
        dragFraction > DISMISS_THRESHOLD || velocityPxPerSec > flingThreshold
}

/** Which image layer is on top: thumbnail (instant, shared element) → preview → original (≤ 40 MP). */
enum class ImageStage { Thumbnail, Preview, Original }

/** Progressive quality for one photo page (pure; JVM tested). */
object ProgressiveQuality {
    const val MAX_ORIGINAL_MEGAPIXELS = 40.0

    fun wantsOriginal(width: Long?, height: Long?, mimeType: String): Boolean {
        val decodable = mimeType.startsWith("image/") && mimeType != "image/gif" && mimeType != "image/svg+xml"
        val megapixels = if (width != null && height != null) width * height / 1_000_000.0 else 0.0
        return decodable && megapixels <= MAX_ORIGINAL_MEGAPIXELS
    }

    /** Top-most stage that has loaded, never going backwards (no flicker). */
    fun stage(previewLoaded: Boolean, originalLoaded: Boolean): ImageStage = when {
        originalLoaded -> ImageStage.Original
        previewLoaded -> ImageStage.Preview
        else -> ImageStage.Thumbnail
    }

    /** "Necesitas conexión para ver el original": the original failed to load but something lower is on screen. */
    fun offline(originalFailed: Boolean, networkError: Boolean, stage: ImageStage): Boolean =
        originalFailed && networkError && stage != ImageStage.Original
}

/** Camera/exposure/location read from the original's EXIF (on the phone; the backend stores none of it). */
@Immutable
data class ExifSummary(
    val camera: String? = null,
    val lens: String? = null,
    val exposure: String? = null,
    val latitude: Double? = null,
    val longitude: Double? = null,
    val takenAt: String? = null
) {
    val hasLocation: Boolean get() = latitude != null && longitude != null

    companion object {
        /** "1/120 s · ƒ/1.8 · ISO 100 · 4,2 mm" from raw EXIF values (each part optional). */
        fun exposureLine(exposureSeconds: Double?, fNumber: Double?, iso: Int?, focalMm: Double?, locale: java.util.Locale): String? {
            val parts = buildList {
                exposureSeconds?.takeIf { it > 0 }?.let { add(shutter(it, locale)) }
                fNumber?.takeIf { it > 0 }?.let { add("ƒ/" + decimal(it, locale)) }
                iso?.takeIf { it > 0 }?.let { add("ISO $it") }
                focalMm?.takeIf { it > 0 }?.let { add(decimal(it, locale) + " mm") }
            }
            return parts.takeIf { it.isNotEmpty() }?.joinToString(" · ")
        }

        fun cameraLine(make: String?, model: String?): String? {
            val m = model?.trim().orEmpty()
            val k = make?.trim().orEmpty()
            return when {
                m.isEmpty() && k.isEmpty() -> null
                k.isEmpty() || m.startsWith(k, ignoreCase = true) -> m.ifEmpty { k }
                else -> "$k $m"
            }
        }

        private fun shutter(seconds: Double, locale: java.util.Locale): String =
            if (seconds >= 1) decimal(seconds, locale) + " s" else "1/" + Math.round(1 / seconds) + " s"

        private fun decimal(value: Double, locale: java.util.Locale): String {
            val format = java.text.NumberFormat.getNumberInstance(locale).apply { maximumFractionDigits = 1 }
            return format.format(value)
        }
    }
}

/** Storage line in the info sheet (product/android.md §4.4). */
enum class StorageLine { Remote, LocalOnly, Uploading, Failed }

fun storageLine(remoteState: String?): StorageLine = when (remoteState) {
    "local_only" -> StorageLine.LocalOnly
    "uploading" -> StorageLine.Uploading
    "failed" -> StorageLine.Failed
    else -> StorageLine.Remote
}
