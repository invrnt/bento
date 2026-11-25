package dev.bento.feature.recovery

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.view.WindowManager
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.platform.LocalContext

/**
 * Sets `FLAG_SECURE` on the hosting window while this is in composition (product/android.md §10: recovery kit,
 * recovery code entry, pairing code/QR, 2FA password). Reference-counted so nested secure screens never clear the
 * flag early.
 */
@Composable
fun SecureWindow() {
    val activity = LocalContext.current.findActivity() ?: return
    DisposableEffect(activity) {
        SecureFlag.acquire(activity)
        onDispose { SecureFlag.release(activity) }
    }
}

internal object SecureFlag {
    private val counts = java.util.WeakHashMap<Activity, Int>()

    fun acquire(activity: Activity) = synchronized(counts) {
        val count = counts[activity] ?: 0
        if (count == 0) activity.window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        counts[activity] = count + 1
    }

    fun release(activity: Activity) = synchronized(counts) {
        val count = (counts[activity] ?: 1) - 1
        if (count <= 0) {
            counts.remove(activity)
            activity.window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
        } else {
            counts[activity] = count
        }
    }
}

fun Context.findActivity(): Activity? {
    var current: Context? = this
    while (current is ContextWrapper) {
        if (current is Activity) return current
        current = current.baseContext
    }
    return null
}
