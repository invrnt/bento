package dev.bento.app.navigation

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import dev.bento.designsystem.component.BentoDialog
import dev.bento.designsystem.component.ErrorState
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.strings.R as StringsR

/**
 * The device key is gone (SEC-11, `DegradedReason.KEY_LOST`): instead of a start loop, explain it and offer
 * "reset this phone" behind a destructive confirmation. [failed] shows after a reset that did not complete.
 */
@Composable
internal fun KeyLostScreen(onReset: () -> Unit, failed: Boolean = false) {
    var confirming by rememberSaveable { mutableStateOf(false) }
    Box(
        Modifier.fillMaxSize().background(BentoTheme.colors.tray).windowInsetsPadding(WindowInsets.safeDrawing).padding(16.dp),
        contentAlignment = Alignment.Center
    ) {
        ErrorState(
            title = stringResource(StringsR.string.shell_key_lost_title),
            body = stringResource(if (failed) StringsR.string.shell_key_lost_failed else StringsR.string.shell_key_lost_body),
            onRetry = { confirming = true },
            retryLabel = stringResource(StringsR.string.shell_key_lost_action)
        )
    }
    if (confirming) {
        BentoDialog(
            title = stringResource(StringsR.string.shell_key_lost_confirm_title),
            consequence = stringResource(StringsR.string.shell_key_lost_confirm_body),
            confirmLabel = stringResource(StringsR.string.shell_key_lost_confirm),
            onConfirm = {
                confirming = false
                onReset()
            },
            onDismissRequest = { confirming = false }
        )
    }
}
