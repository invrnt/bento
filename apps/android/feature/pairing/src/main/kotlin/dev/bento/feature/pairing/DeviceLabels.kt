package dev.bento.feature.pairing

import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.strings.R as StringsR

/** Platform names and icons for devices and pairing peers (apps/web `deviceLabels.ts`, plus Android). */
object DeviceLabels {
    fun platformRes(platform: String?): Int = when (platform?.lowercase()) {
        "linux" -> StringsR.string.pairing_platform_linux
        "macos" -> StringsR.string.pairing_platform_macos
        "windows" -> StringsR.string.pairing_platform_windows
        "android" -> StringsR.string.pairing_platform_android
        else -> StringsR.string.pairing_platform_other
    }

    fun icon(platform: String?): ImageVector = when (platform?.lowercase()) {
        "android" -> BentoIcons.Smartphone
        "macos" -> BentoIcons.Laptop
        "linux", "windows" -> BentoIcons.Monitor
        else -> BentoIcons.MonitorSmartphone
    }

    /** "Portátil de Ana · Linux": appends the platform unless the name already ends with it. */
    fun displayName(name: String, platformLabel: String): String {
        val trimmed = name.trim()
        if (trimmed.isEmpty()) return platformLabel
        return if (trimmed.lowercase().endsWith(platformLabel.lowercase())) trimmed else "$trimmed · $platformLabel"
    }

    /** Desktops are "computador" in pairing copy (product/android.md §13a); phones keep "dispositivo". */
    fun isComputer(platform: String?): Boolean = platform?.lowercase() in setOf("linux", "macos", "windows")
}

@Composable
fun platformLabel(platform: String?): String = stringResource(DeviceLabels.platformRes(platform))

@Composable
fun deviceDisplayName(name: String, platform: String?): String = DeviceLabels.displayName(name, platformLabel(platform))
