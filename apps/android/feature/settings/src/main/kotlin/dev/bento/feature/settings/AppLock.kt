package dev.bento.feature.settings

import android.app.Activity
import android.app.KeyguardManager
import android.content.Context
import android.hardware.biometrics.BiometricManager
import android.hardware.biometrics.BiometricPrompt
import android.os.Build
import android.os.CancellationSignal
import android.view.WindowManager
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * App lock timing (product/android.md §9-§10; pure, JVM tested). The lock gates the UI only: the engine and background
 * sync keep running while locked (keys are not bound to biometrics, architecture/android-runtime.md §5).
 *
 * - Cold start with the lock on → locked.
 * - Leaving the screen records the time; coming back locks when [LockTimeout] has passed (`Inmediatamente` = always).
 */
class AppLockState(initiallyLocked: Boolean = false, private val clock: () -> Long = System::currentTimeMillis) {
    // Locked before the first frame on a cold start, so library content never flashes before the prompt.
    private val _locked = MutableStateFlow(initiallyLocked)
    val locked: StateFlow<Boolean> = _locked.asStateFlow()
    private var leftAt: Long? = null
    private var started = false

    @Synchronized
    fun onForeground(prefs: LocalPrefs) {
        val away = leftAt
        val shouldLock = prefs.lockEnabled && (!started || (away != null && clock() - away >= prefs.lockTimeout.millis))
        started = true
        leftAt = null
        if (shouldLock) _locked.value = true
        if (!prefs.lockEnabled) _locked.value = false
    }

    @Synchronized
    fun onBackground() {
        leftAt = clock()
    }

    fun unlock() {
        _locked.value = false
    }

    /** Turning the lock on from Ajustes does not lock the person out of the screen they are on. */
    fun enabledNow() {
        started = true
    }
}

/** Platform BiometricPrompt with the device credential (PIN/pattern/password) as fallback; minSdk 29 needs no AndroidX. */
object DeviceAuth {
    fun available(context: Context): Boolean = context.getSystemService(KeyguardManager::class.java)?.isDeviceSecure == true

    @Suppress("DEPRECATION")
    fun prompt(activity: Activity, title: String, subtitle: String, onResult: (Boolean) -> Unit) {
        val builder = BiometricPrompt.Builder(activity).setTitle(title).setSubtitle(subtitle)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            builder.setAllowedAuthenticators(
                BiometricManager.Authenticators.BIOMETRIC_WEAK or BiometricManager.Authenticators.DEVICE_CREDENTIAL
            )
        } else {
            builder.setDeviceCredentialAllowed(true)
        }
        val callback = object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult?) = onResult(true)

            override fun onAuthenticationError(errorCode: Int, errString: CharSequence?) = onResult(false)
        }
        runCatching { builder.build().authenticate(CancellationSignal(), activity.mainExecutor, callback) }.onFailure { onResult(false) }
    }
}

/**
 * Hides the app's content in recents (product/android.md §9 "Ocultar contenido en apps recientes", on with the lock).
 * Android 13+: `setRecentsScreenshotEnabled(false)`; older versions have no such API, so `FLAG_SECURE` is used
 * (which also blocks screenshots while it is on).
 */
object RecentsPrivacy {
    fun apply(activity: Activity, hide: Boolean) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            activity.setRecentsScreenshotEnabled(!hide)
        } else if (hide) {
            activity.window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        }
    }

    fun shouldHide(prefs: LocalPrefs): Boolean = prefs.lockEnabled && prefs.hideInRecents
}
