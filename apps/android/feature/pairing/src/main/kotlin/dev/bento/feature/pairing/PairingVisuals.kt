package dev.bento.feature.pairing

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import dev.bento.api.generated.PairingVaultResponse
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.ProgressRing
import dev.bento.designsystem.component.SasEmojiRow
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.recovery.TrustDates
import dev.bento.strings.R as StringsR

/** The four SAS emojis; TalkBack reads one sentence with every emoji (the system speaks their names). */
@Composable
fun PairingSas(emojis: List<String>, modifier: Modifier = Modifier) {
    SasEmojiRow(emojis, modifier.padding(vertical = 8.dp))
}

/** A polite live status line with a small ring ("Esperando la confirmación…"). */
@Composable
fun StatusLine(text: String, modifier: Modifier = Modifier) {
    Row(
        modifier.fillMaxWidth().semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterHorizontally)
    ) {
        ProgressRing(progress = null, size = 18.dp)
        Text(text, color = BentoTheme.colors.inkMuted, style = BentoTheme.typography.label)
    }
}

/** What a Sync-channel guest shows next to the emojis: the cloud's creation date and the host's device count. */
@Composable
fun VaultSummary(vault: PairingVaultResponse?, modifier: Modifier = Modifier) {
    if (vault == null) return
    val c = BentoTheme.colors
    val created = TrustDates.long(vault.createdAt)
    Column(
        modifier
            .fillMaxWidth()
            .clip(BentoShapes.lg)
            .background(c.subtle)
            .border(1.dp, c.line, BentoShapes.lg)
            .padding(16.dp)
            .semantics(mergeDescendants = true) {},
        verticalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            BentoIcon(BentoIcons.Cloud, contentDescription = null, tint = c.accentInk)
            Text(stringResource(StringsR.string.pairing_vault_label), color = c.ink, style = BentoTheme.typography.labelStrong)
        }
        if (created !=
            null
        ) {
            Text(stringResource(StringsR.string.pairing_vault_created, created), color = c.inkMuted, style = BentoTheme.typography.body)
        }
        vault.devicesCount?.toInt()?.let { count ->
            Text(
                pluralStringResource(StringsR.plurals.pairing_vault_devices, count, count),
                color = c.inkMuted,
                style = BentoTheme.typography.body
            )
        }
    }
}
