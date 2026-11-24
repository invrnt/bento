package dev.bento.designsystem.trace

import android.os.Trace
import java.util.concurrent.ConcurrentHashMap

/**
 * Async trace slices from a user action to the frame that answers it, read by Macrobenchmark's `TraceSectionMetric`
 * (`apps/android/benchmark`, docs/dev/android-performance.md). One open slice per name; costs nothing when tracing is
 * off (the platform checks the tag).
 */
public object InteractionTrace {
    /** Tile tap → viewer's first frame with the shared thumbnail (budget ≤ 100 ms). */
    public const val VIEWER_OPEN: String = "bento.viewer.open"

    /** Folder tap in Archivos → first frame listing that folder's items. */
    public const val FILES_OPEN: String = "bento.files.open"

    /** First key of a query in Buscar → first frame with results. */
    public const val SEARCH_RESULTS: String = "bento.search.results"

    /** `Guardar en Bento` tap → the share sheet's activity paused (budget ≤ 200 ms). */
    public const val SHARE_DISMISS: String = "bento.share.dismiss"

    private val open = ConcurrentHashMap<String, Int>()

    /** Starts [section], ending an earlier one that never finished. */
    public fun begin(section: String) {
        open.remove(section)?.let { Trace.endAsyncSection(section, it) }
        val cookie = section.hashCode()
        open[section] = cookie
        Trace.beginAsyncSection(section, cookie)
    }

    /** Starts [section] only when it is not already open. */
    public fun beginIfIdle(section: String) {
        if (!open.containsKey(section)) begin(section)
    }

    public fun end(section: String) {
        open.remove(section)?.let { Trace.endAsyncSection(section, it) }
    }
}
