package dev.bento.app.navigation

import android.content.Intent
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext
import androidx.core.net.toUri
import dev.bento.app.BuildConfig
import dev.bento.feature.activity.AccountAvatar
import dev.bento.feature.activity.ActivityNavigation
import dev.bento.feature.activity.ActivityScreen
import dev.bento.feature.settings.SettingsNavigation
import dev.bento.feature.settings.SettingsScreen
import dev.bento.feature.settings.SettingsSection
import dev.bento.feature.settings.StallDetector

/** Navigation glue for agent 41's destinations: features expose callbacks, the shell decides where they lead. */
@Composable
internal fun activityNavigation(navigator: Navigator): ActivityNavigation {
    val context = LocalContext.current
    return ActivityNavigation(
        onDevices = { navigator.navigate(Route.Devices) },
        onTrash = { navigator.navigate(Route.Trash) },
        onSettings = { navigator.navigate(Route.Settings()) },
        onBackupSettings = { navigator.navigate(Route.Settings(SettingsSection.Backup.name)) },
        onRecovery = { navigator.navigate(Route.Recovery) },
        onReconnect = { navigator.navigate(Route.Reconnect) },
        onDeviceReview = { navigator.navigate(Route.DeviceReview(it)) },
        onDeviceRemoved = { navigator.navigate(Route.DeviceRemoved) },
        onStallHelp = {
            context.startActivity(
                Intent(
                    Intent.ACTION_VIEW,
                    StallDetector.helpUrl(android.os.Build.MANUFACTURER).toUri()
                ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
        }
    )
}

/** The status avatar every top bar shows (opens the Cuenta y actividad sheet). */
@Composable
internal fun AccountAvatarFor(navigator: Navigator) = AccountAvatar(activityNavigation(navigator))

@Composable
internal fun ActivityDestination(navigator: Navigator) {
    ActivityScreen(onBack = { navigator.back() }, navigation = activityNavigation(navigator))
}

@Composable
internal fun SettingsDestination(navigator: Navigator, key: Route.Settings) {
    SettingsScreen(
        navigation = SettingsNavigation(
            onBack = { navigator.back() },
            onDevices = { navigator.navigate(Route.Devices) },
            onRecovery = { navigator.navigate(Route.Recovery) },
            onReconnect = { navigator.navigate(Route.Reconnect) },
            // Importar de Telegram lives in Colecciones (agent 39).
            onImportTelegram = { navigator.navigate(Route.Collections) },
            onSignedOut = { navigator.reset(Route.Photos, Route.Reconnect) }
        ),
        initialSection = key.section?.let { runCatching { SettingsSection.valueOf(it) }.getOrNull() },
        siteUrl = BuildConfig.SITE_URL
    )
}

/** Where a notification tap, a launcher shortcut or the Quick Settings tile's long-press lands. */
internal fun routeFor(target: dev.bento.background.OpenTarget): Route = when (target) {
    dev.bento.background.OpenTarget.Activity -> Route.Activity
    dev.bento.background.OpenTarget.Backup -> Route.Settings(SettingsSection.Backup.name)
    dev.bento.background.OpenTarget.Storage -> Route.Settings(SettingsSection.Storage.name)
    dev.bento.background.OpenTarget.Recovery -> Route.Recovery
    dev.bento.background.OpenTarget.Reconnect -> Route.Reconnect
    dev.bento.background.OpenTarget.Devices -> Route.Devices
    dev.bento.background.OpenTarget.DeviceRemoved -> Route.DeviceRemoved
    dev.bento.background.OpenTarget.Search -> Route.Search()
    dev.bento.background.OpenTarget.AddDevice -> Route.AddDevice
    is dev.bento.background.OpenTarget.PairingRequest -> Route.PairingRequest(target.requestId)
    is dev.bento.background.OpenTarget.DeviceReview -> Route.DeviceReview(target.deviceId)
}
