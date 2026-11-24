package dev.bento.app.tempdesign

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/**
 * TEMPORARY, debug-quality theme (agent 36) so the shell runs before core/designsystem exists.
 * The orchestrator replaces every use with `BentoTheme` from agent 37 at merge and deletes this package
 * (and the themes_temp.xml window themes). No dynamic color, by design.
 */
@Composable
fun TempBentoTheme(dark: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    val colors = if (dark) {
        darkColorScheme(primary = Color(0xFFE8A866), background = Color(0xFF1A1917), surface = Color(0xFF1A1917))
    } else {
        lightColorScheme(primary = Color(0xFF9A5B1E), background = Color(0xFFFAF8F5), surface = Color(0xFFFAF8F5))
    }
    MaterialTheme(colorScheme = colors, content = content)
}
