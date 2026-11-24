package dev.bento.app.navigation

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.navigation3.runtime.EntryProviderScope
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.devices.DeviceReviewScreen
import dev.bento.feature.pairing.HostPairingScreen
import dev.bento.feature.pairing.PairingRequestScreen
import dev.bento.feature.recovery.RecoveryManageScreen
import dev.bento.strings.R as StringsR

/**
 * Screen registration: one `entry<Route.X> { … }` line per destination. Entries marked PLACEHOLDER wait for their
 * feature agent (Stage 21) to replace the line with the real screen.
 */
fun EntryProviderScope<Route>.bentoEntries(navigator: Navigator) {
    entry<Route.Photos> { Placeholder("Fotos") }
    entry<Route.Files> { key -> Placeholder("Archivos ${key.folderId.orEmpty()}") }
    entry<Route.Collections> { Placeholder("Colecciones") }
    entry<Route.Search> { Placeholder("Buscar") }
    entry<Route.Viewer> { key -> Placeholder("Visor ${key.assetId}") }
    entry<Route.Album> { key -> Placeholder("Álbum ${key.albumId}") }
    entry<Route.Trash> { Placeholder("Papelera") }
    entry<Route.Activity> { Placeholder("Actividad") }
    entry<Route.Settings> { Placeholder("Ajustes") }
    // PLACEHOLDER (agent 41 replaces it with the phone-backup setup); onboarding continues when it returns.
    entry<Route.BackupSetup> { BackupSetupPlaceholder(onContinue = { navigator.back() }) }
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

/** PLACEHOLDER for `Route.BackupSetup` (agent 41): lets onboarding continue until the real screen lands. */
@Composable
private fun BackupSetupPlaceholder(onContinue: () -> Unit) {
    Column(
        Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically)
    ) {
        Text(
            text = stringResource(StringsR.string.shell_placeholder_destination, "Respaldo"),
            color = BentoTheme.colors.inkMuted,
            style = BentoTheme.typography.sectionTitle
        )
        BentoButton(stringResource(StringsR.string.common_action_continue), onContinue, variant = BentoButtonVariant.Primary)
    }
}
