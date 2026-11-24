package dev.bento.feature.recovery

import android.content.ClipData
import android.content.ClipDescription
import android.content.ClipboardManager
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PersistableBundle

/**
 * Clipboard writes of codes (product/android.md §10): marked sensitive (hidden from the Android 13+ clipboard
 * preview) and cleared after [CLEAR_AFTER_MS] if the clip is still ours.
 */
object SensitiveClipboard {
    const val CLEAR_AFTER_MS: Long = 60_000
    private const val LABEL = "bento-code"
    private const val EXTRA_IS_SENSITIVE = "android.content.extra.IS_SENSITIVE"
    private val handler by lazy { Handler(Looper.getMainLooper()) }

    /** Returns false when the system refused the write. */
    fun copy(context: Context, text: String, clearAfterMs: Long = CLEAR_AFTER_MS): Boolean {
        val manager = context.getSystemService(ClipboardManager::class.java) ?: return false
        val token = "$LABEL:${System.nanoTime()}"
        val clip = ClipData.newPlainText(token, text).apply {
            description.extras = PersistableBundle().apply {
                putBoolean(if (Build.VERSION.SDK_INT >= 33) ClipDescription.EXTRA_IS_SENSITIVE else EXTRA_IS_SENSITIVE, true)
            }
        }
        return runCatching {
            manager.setPrimaryClip(clip)
            handler.postDelayed({ clearIfOurs(manager, token) }, clearAfterMs)
        }.isSuccess
    }

    internal fun clearIfOurs(manager: ClipboardManager, token: String) {
        val current = runCatching { manager.primaryClipDescription?.label?.toString() }.getOrNull()
        if (current == token) runCatching { manager.clearPrimaryClip() }
    }

    /** Plain text currently on the clipboard (reading it shows the system's paste notice on Android 12+). */
    fun readText(context: Context): String? {
        val manager = context.getSystemService(ClipboardManager::class.java)
        val description = manager?.takeIf { it.hasPrimaryClip() }?.primaryClipDescription
        val isText = description != null &&
            (description.hasMimeType(ClipDescription.MIMETYPE_TEXT_PLAIN) || description.hasMimeType(ClipDescription.MIMETYPE_TEXT_HTML))
        if (!isText) return null
        return runCatching { manager?.primaryClip?.getItemAt(0)?.coerceToText(context)?.toString() }.getOrNull()
            ?.takeIf { it.length <= MAX_READ }
    }

    private const val MAX_READ = 512
}
