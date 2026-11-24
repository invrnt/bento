package dev.bento.feature.settings

import android.app.Activity
import android.content.Context
import android.content.res.Configuration
import android.os.Build
import androidx.compose.foundation.background
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BrandMark
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.recovery.findActivity
import dev.bento.strings.R as StringsR
import java.util.Locale

/** Whether the app renders dark for the person's Tema choice. */
@Composable
fun darkThemeFor(choice: ThemeChoice): Boolean = when (choice) {
    ThemeChoice.System -> isSystemInDarkTheme()
    ThemeChoice.Light -> false
    ThemeChoice.Dark -> true
}

/**
 * App lock gate around the whole UI (product/android.md §9-§10). While locked only the lock screen is composed, so no
 * library content renders; the engine and background sync keep running. Also applies "Ocultar contenido en apps
 * recientes" to the hosting activity.
 */
@Composable
fun AppLockGate(local: LocalSettings, lock: AppLockState, content: @Composable () -> Unit) {
    val prefs by local.prefs.collectAsStateWithLifecycle(local.current())
    val locked by lock.locked.collectAsStateWithLifecycle()
    val activity = LocalContext.current.findActivity()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val currentPrefs by androidx.compose.runtime.rememberUpdatedState(prefs)
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> lock.onForeground(currentPrefs)

                // A rotation is not leaving the app.
                Lifecycle.Event.ON_STOP -> if (activity?.isChangingConfigurations != true) lock.onBackground()

                else -> Unit
            }
        }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer) }
    }
    LaunchedEffect(prefs.lockEnabled, prefs.hideInRecents, activity) {
        activity?.let { RecentsPrivacy.apply(it, RecentsPrivacy.shouldHide(prefs)) }
        if (!prefs.lockEnabled) lock.unlock()
    }
    if (locked && prefs.lockEnabled) {
        LockScreen(onUnlock = { activity?.let { unlock(it, lock) } })
        LaunchedEffect(Unit) { activity?.let { unlock(it, lock) } }
    } else {
        content()
    }
}

private fun unlock(activity: Activity, lock: AppLockState) {
    DeviceAuth.prompt(
        activity,
        activity.getString(StringsR.string.settings_lock_prompt_title),
        activity.getString(StringsR.string.settings_lock_prompt_unlock)
    ) { ok -> if (ok) lock.unlock() }
}

@Composable
fun LockScreen(onUnlock: () -> Unit, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize().background(BentoTheme.colors.tray).safeDrawingPadding(), contentAlignment = Alignment.Center) {
        Column(
            Modifier.padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            BrandMark(size = 72.dp)
            Text(
                stringResource(StringsR.string.settings_lock_locked_title),
                color = BentoTheme.colors.ink,
                style = BentoTheme.typography.pageTitle,
                textAlign = TextAlign.Center,
                modifier = Modifier.semantics { heading() }
            )
            Text(
                stringResource(StringsR.string.settings_lock_locked_body),
                color = BentoTheme.colors.inkMuted,
                style = BentoTheme.typography.body,
                textAlign = TextAlign.Center
            )
            BentoButton(
                stringResource(StringsR.string.settings_lock_unlock),
                onUnlock,
                variant = BentoButtonVariant.Primary,
                leadingIcon = BentoIcons.Fingerprint
            )
        }
    }
}

/**
 * In-app language on Android 12 and older (13+ uses the system per-app language, product/android.md §2): the activity
 * wraps its base context with the chosen locale.
 */
object AppLanguage {
    fun wrap(base: Context, tag: String): Context {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU || tag.isBlank()) return base
        val locale = Locale.forLanguageTag(tag)
        val config = Configuration(base.resources.configuration).apply { setLocale(locale) }
        return base.createConfigurationContext(config)
    }
}
