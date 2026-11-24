package dev.bento.feature.settings

import android.app.Activity
import android.app.RecoverableSecurityException
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.platform.LocalContext

/**
 * Deletes phone originals through the system (product/android.md §5 "Liberar espacio"): Android 11+ shows the system's
 * own confirmation for the whole batch (`MediaStore.createDeleteRequest`); Android 10 asks per item through
 * `RecoverableSecurityException`. [onResult] gets whether the person approved; the caller then checks what is gone.
 */
@Composable
internal fun rememberMediaDeleteLauncher(onResult: (Boolean) -> Unit): (List<Uri>) -> Unit {
    val context = LocalContext.current
    val result = rememberUpdatedState(onResult)
    val queue = remember { ArrayDeque<Uri>() }
    lateinit var next: () -> Unit
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) { outcome ->
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            result.value(outcome.resultCode == Activity.RESULT_OK)
        } else if (outcome.resultCode == Activity.RESULT_OK) {
            next() // Android 10: the consent covered this item; delete it and go on.
        } else {
            queue.clear()
            result.value(false)
        }
    }
    next = {
        var asked = false
        while (queue.isNotEmpty() && !asked) {
            val uri = queue.first()
            try {
                context.contentResolver.delete(uri, null, null)
                queue.removeFirst()
            } catch (consent: RecoverableSecurityException) {
                asked = true
                launcher.launch(IntentSenderRequest.Builder(consent.userAction.actionIntent.intentSender).build())
            } catch (_: SecurityException) {
                queue.removeFirst()
            }
        }
        if (!asked) result.value(true)
    }
    return { uris ->
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            val sender = MediaStore.createDeleteRequest(context.contentResolver, uris).intentSender
            launcher.launch(IntentSenderRequest.Builder(sender).build())
        } else {
            queue.clear()
            queue.addAll(uris)
            next()
        }
    }
}
