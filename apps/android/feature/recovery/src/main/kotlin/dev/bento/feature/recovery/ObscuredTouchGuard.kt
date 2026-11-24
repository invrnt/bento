package dev.bento.feature.recovery

import android.app.Activity
import android.os.Build
import android.view.View
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView

/**
 * Tapjacking protection (SEC-09) for high-value confirmations: approving a pairing device, removing a device, the
 * recovery kit and recovery entry. While in composition, the hosting view drops touches that arrive while another
 * app's window covers it (`filterTouchesWhenObscured`, all API levels; Android 10/11 do not block them), and on
 * API 31+ the activity hides non-system overlays (`setHideOverlayWindows`; `HIDE_OVERLAY_WINDOWS` is declared in this
 * module's manifest).
 * Inside a sheet or dialog [LocalView] is that window's view, so the guard follows the content it is placed in.
 */
@Composable
fun ObscuredTouchGuard() {
    val view = LocalView.current
    val activity = LocalContext.current.findActivity()
    DisposableEffect(view, activity) {
        TouchFilter.acquire(view)
        activity?.let(OverlayFlag::acquire)
        onDispose {
            TouchFilter.release(view)
            activity?.let(OverlayFlag::release)
        }
    }
}

/** Reference count per key: [apply] (true) on the first acquire, [apply] (false) when the last one leaves. */
internal open class GuardCount<T : Any>(private val apply: (T, Boolean) -> Unit) {
    private val counts = java.util.WeakHashMap<T, Int>()

    fun acquire(target: T) = synchronized(counts) {
        val count = counts[target] ?: 0
        if (count == 0) apply(target, true)
        counts[target] = count + 1
    }

    fun release(target: T) = synchronized(counts) {
        val count = (counts[target] ?: 1) - 1
        if (count <= 0) {
            counts.remove(target)
            apply(target, false)
        } else {
            counts[target] = count
        }
    }
}

internal object TouchFilter : GuardCount<View>({ view, on -> view.filterTouchesWhenObscured = on })

internal object OverlayFlag : GuardCount<Activity>({ activity, hide ->
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        // HIDE_OVERLAY_WINDOWS is a normal permission (this module's manifest); never crash a screen over it.
        runCatching { activity.window.setHideOverlayWindows(hide) }
    }
})
