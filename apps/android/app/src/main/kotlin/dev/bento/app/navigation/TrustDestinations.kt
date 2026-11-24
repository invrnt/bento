package dev.bento.app.navigation

import androidx.compose.runtime.Composable
import dev.bento.feature.devices.DeviceRemovedScreen
import dev.bento.feature.devices.DevicesScreen
import dev.bento.feature.onboarding.OnboardingScreen
import dev.bento.feature.pairing.JoinScreen

/** Navigation glue for agent 38's destinations: features only expose callbacks, the shell decides where they lead. */
@Composable
internal fun OnboardingDestination(navigator: Navigator, reconnect: Boolean) {
    OnboardingScreen(
        reconnect = reconnect,
        onJoin = { navigator.navigate(Route.Join()) },
        // The account already has a cloud: join it (ask other devices or the recovery kit).
        onExistingVault = {
            if (reconnect) navigator.reset(Route.Photos, Route.Join(choose = true)) else navigator.reset(Route.Join(choose = true))
        },
        onBackupSetup = { navigator.navigate(Route.BackupSetup) },
        onFinished = { navigator.reset(Route.Photos) },
        onExit = { if (!navigator.back()) navigator.reset(Route.Photos) },
        // Removing a device closes its Telegram session first, so the removal is only found after signing in again.
        onRemoved = { navigator.reset(Route.Photos, Route.DeviceRemoved) }
    )
}

@Composable
internal fun JoinDestination(navigator: Navigator, key: Route.Join) {
    JoinScreen(
        code = key.code,
        startAtChoice = key.choose,
        onDone = { navigator.reset(Route.Photos) },
        onCreateVault = { navigator.reset(Route.Onboarding) },
        onExit = { if (!navigator.back()) navigator.reset(Route.Onboarding) }
    )
}

@Composable
internal fun DevicesDestination(navigator: Navigator) {
    DevicesScreen(
        onBack = { navigator.back() },
        onAddDevice = { navigator.navigate(Route.AddDevice) },
        onReviewRequest = { navigator.navigate(Route.PairingRequest(it)) },
        onConnectTelegram = { navigator.navigate(Route.Reconnect) }
    )
}

@Composable
internal fun DeviceRemovedDestination(navigator: Navigator) {
    DeviceRemovedScreen(
        onRejoin = { navigator.navigate(Route.Join()) },
        onUseRecovery = { navigator.navigate(Route.Join(choose = true)) },
        onLater = { navigator.back() }
    )
}
