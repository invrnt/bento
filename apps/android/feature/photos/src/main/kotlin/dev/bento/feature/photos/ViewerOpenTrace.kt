package dev.bento.feature.photos

import androidx.tracing.Trace

/**
 * Async trace slice `bento.viewer.open`: from the tile tap to the viewer's first frame that shows the photo (the
 * shared thumbnail). Macrobenchmark reads it with `TraceSectionMetric` (budget: first frame <= 100 ms, §13).
 */
object ViewerOpenTrace {
    const val SECTION = "bento.viewer.open"
    private const val COOKIE = 39

    @Volatile private var open = false

    fun begin() {
        if (open) Trace.endAsyncSection(SECTION, COOKIE)
        open = true
        Trace.beginAsyncSection(SECTION, COOKIE)
    }

    fun end() {
        if (!open) return
        open = false
        Trace.endAsyncSection(SECTION, COOKIE)
    }
}
