package dev.bento.feature.photos

import dev.bento.designsystem.trace.InteractionTrace

/**
 * Async trace slice `bento.viewer.open`: from the tile tap to the viewer's first frame that shows the photo (the
 * shared thumbnail). Macrobenchmark reads it with `TraceSectionMetric` (budget: first frame <= 100 ms, §13).
 */
object ViewerOpenTrace {
    const val SECTION = InteractionTrace.VIEWER_OPEN

    fun begin() = InteractionTrace.begin(SECTION)

    fun end() = InteractionTrace.end(SECTION)
}
