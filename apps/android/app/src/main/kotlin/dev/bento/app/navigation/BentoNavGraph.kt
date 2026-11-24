package dev.bento.app.navigation

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.navigation3.runtime.EntryProviderScope
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.devices.DeviceReviewScreen
import dev.bento.feature.files.DocumentScreen
import dev.bento.feature.pairing.HostPairingScreen
import dev.bento.feature.pairing.PairingRequestScreen
import dev.bento.feature.recovery.RecoveryManageScreen
import dev.bento.feature.settings.BackupSetupScreen
import dev.bento.strings.R as StringsR

/**
 * Screen registration: one `entry<Route.X> { … }` line per destination. Entries marked PLACEHOLDER wait for their
 * feature agent (Stage 21) to replace the line with the real screen.
 */
fun EntryProviderScope<Route>.bentoEntries(navigator: Navigator) {
    entry<Route.Photos> { Placeholder("Fotos") }
    entry<Route.Files> { key -> FilesDestination(navigator, key) }
    entry<Route.Collections> { Placeholder("Colecciones") }
    entry<Route.Search> { key -> SearchDestination(navigator, key) }
    entry<Route.Document> { key -> DocumentScreen(key.assetId, onBack = { navigator.back() }) }
    entry<Route.Viewer> { key -> Placeholder("Visor ${key.assetId}") }
    entry<Route.Album> { key -> Placeholder("Álbum ${key.albumId}") }
    entry<Route.Trash> { Placeholder("Papelera") }
    // Cuenta y actividad, Ajustes and the phone-backup setup (agent 41): wrappers in SettingsDestinations.kt.
    entry<Route.Activity> { ActivityDestination(navigator) }
    entry<Route.Settings> { key -> SettingsDestination(navigator, key) }
    entry<Route.BackupSetup> { BackupSetupScreen(onDone = { navigator.back() }) }
    // Onboarding, pairing, recovery and devices (agent 38): wrappers in TrustDestinations.kt.
    entry<Route.Onboarding> { OnboardingDestination(navigator, reconnect = false) }
    entry<Route.Reconnect> { OnboardingDestination(navigator, reconnect = true) }
    entry<Route.Join> { key -> JoinDestination(navigator, key) }
    entry<Route.Recovery> { RecoveryManageScreen(onBack = { navigator.back() }) }
    entry<Route.Devices> { DevicesDestination(navigator) }
    entry<Route.AddDevice> { HostPairingScreen(onClose = { navigator.back() }) }
    entry<Route.PairingRequest> { key -> PairingRequestScreen(key.requestId, onClose = { navigator.back() }) }
    entry<Route.DeviceReview> { key -> DeviceReviewScreen(key.deviceId, onClose = { navigator.back() }) }
    entry<Route.DeviceRemoved> { DeviceRemovedDestination(navigator) }
}

/** Placeholder until the destination's feature agent (Stage 21) lands; [name] is a developer label. */
@Composable
fun Placeholder(name: String) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(
            text = stringResource(StringsR.string.shell_placeholder_destination, name),
            color = BentoTheme.colors.inkMuted,
            style = BentoTheme.typography.sectionTitle,
            modifier = Modifier.semantics { heading() }
        )
    }
}
