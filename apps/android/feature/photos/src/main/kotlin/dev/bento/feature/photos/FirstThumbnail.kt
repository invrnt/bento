package dev.bento.feature.photos

import androidx.compose.runtime.mutableStateOf
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Time to full display (§13 "cold start → cached Fotos grid with thumbnails"): Fotos reports drawn once the first
 * tile shows pixels. Tiles only write the state (once), so they never recompose because of it.
 */
internal object FirstThumbnail {
    private val marked = AtomicBoolean(false)
    val shown = mutableStateOf(false)

    fun markShown() {
        if (!marked.getAndSet(true)) shown.value = true
    }
}
