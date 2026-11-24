package dev.bento.designsystem.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.text.selection.LocalTextSelectionColors
import androidx.compose.foundation.text.selection.TextSelectionColors
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import dev.bento.designsystem.generated.BentoColorTokens
import dev.bento.designsystem.generated.BentoShadowTokens
import dev.bento.designsystem.generated.BentoTokens

/** The active palette. Feature code reads colors only through [BentoTheme.colors]. */
public typealias BentoColors = BentoColorTokens

internal val LocalBentoColors = staticCompositionLocalOf { BentoTokens.LightColors }
internal val LocalBentoShadows = staticCompositionLocalOf { BentoTokens.LightShadows }
internal val LocalBentoTypography = staticCompositionLocalOf { BentoTypography.Default }
internal val LocalBentoIsDark = staticCompositionLocalOf { false }
internal val LocalBentoIsMedia = staticCompositionLocalOf { false }

/**
 * Bento's theme: Material 3 for behavior, every color/type/shape slot filled from Bento tokens.
 * Dynamic color is never used (design-system/android.md §1).
 *
 * @param darkTheme follow the system by default; the app passes the user's Automático/Claro/Oscuro choice.
 * @param reducedMotion `null` reads the system setting (animator duration scale 0 / "remove animations").
 */
@Composable
public fun BentoTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    reducedMotion: Boolean? = null,
    content: @Composable () -> Unit,
) {
    val colors = if (darkTheme) BentoTokens.DarkColors else BentoTokens.LightColors
    val shadows = if (darkTheme) BentoTokens.DarkShadows else BentoTokens.LightShadows
    BentoThemeImpl(colors, shadows, darkTheme, media = false, reducedMotion = reducedMotion, content = content)
}

/** The viewer and video player always use the dark `media` scheme, whatever the app theme (brand.md §14). */
@Composable
public fun BentoMediaTheme(reducedMotion: Boolean? = null, content: @Composable () -> Unit) {
    val colors = remember {
        BentoTokens.DarkColors.copy(
            tray = BentoTokens.media,
            surface = BentoTokens.media,
            raised = BentoTokens.mediaRaised,
            subtle = BentoTokens.mediaRaised,
            sunken = BentoTokens.media,
        )
    }
    BentoThemeImpl(colors, BentoTokens.DarkShadows, dark = true, media = true, reducedMotion = reducedMotion, content = content)
}

@Composable
private fun BentoThemeImpl(
    colors: BentoColors,
    shadows: BentoShadowTokens,
    dark: Boolean,
    media: Boolean,
    reducedMotion: Boolean?,
    content: @Composable () -> Unit,
) {
    val scheme = remember(colors, dark) { bentoColorScheme(colors, dark) }
    val systemReduced = rememberSystemReducedMotion()
    val motion = remember(reducedMotion, systemReduced) { BentoMotion(reduced = reducedMotion ?: systemReduced) }
    val selection = remember(colors) { TextSelectionColors(handleColor = colors.accent, backgroundColor = colors.accent.copy(alpha = 0.28f)) }
    MaterialTheme(colorScheme = scheme, typography = BentoTypography.Default.material, shapes = BentoShapes.material) {
        CompositionLocalProvider(
            LocalBentoColors provides colors,
            LocalBentoShadows provides shadows,
            LocalBentoTypography provides BentoTypography.Default,
            LocalBentoIsDark provides dark,
            LocalBentoIsMedia provides media,
            LocalBentoMotion provides motion,
            LocalContentColor provides colors.ink,
            LocalTextSelectionColors provides selection,
            content = content,
        )
    }
}

/** Accessors for the current Bento theme. */
public object BentoTheme {
    public val colors: BentoColors
        @Composable @ReadOnlyComposable get() = LocalBentoColors.current

    public val typography: BentoTypography
        @Composable @ReadOnlyComposable get() = LocalBentoTypography.current

    public val shadows: BentoShadowTokens
        @Composable @ReadOnlyComposable get() = LocalBentoShadows.current

    public val motion: BentoMotion
        @Composable @ReadOnlyComposable get() = LocalBentoMotion.current

    public val isDark: Boolean
        @Composable @ReadOnlyComposable get() = LocalBentoIsDark.current

    /** True inside [BentoMediaTheme]. */
    public val isMedia: Boolean
        @Composable @ReadOnlyComposable get() = LocalBentoIsMedia.current
}

/** Corner radii with the nested rule (outer = inner + gap), brand.md §6 + the mobile control exception. */
public object BentoShapes {
    public val xs: RoundedCornerShape = RoundedCornerShape(BentoTokens.Radius.xs)
    public val sm: RoundedCornerShape = RoundedCornerShape(BentoTokens.Radius.sm)
    public val md: RoundedCornerShape = RoundedCornerShape(BentoTokens.Radius.md)

    /** Fields and buttons at 48 dp on phones. */
    public val control: RoundedCornerShape = RoundedCornerShape(BentoTokens.Radius.controlMobile)
    public val lg: RoundedCornerShape = RoundedCornerShape(BentoTokens.Radius.lg)
    public val xl: RoundedCornerShape = RoundedCornerShape(BentoTokens.Radius.xl)
    public val hero: RoundedCornerShape = RoundedCornerShape(BentoTokens.Radius.xxl)
    public val sheet: RoundedCornerShape = RoundedCornerShape(topStart = BentoTokens.Radius.xl, topEnd = BentoTokens.Radius.xl)
    public val full: RoundedCornerShape = RoundedCornerShape(percent = 50)

    internal val material: Shapes = Shapes(
        extraSmall = xs,
        small = sm,
        medium = control,
        large = lg,
        extraLarge = xl,
        largeIncreased = RoundedCornerShape(BentoTokens.Radius.xl),
        extraLargeIncreased = hero,
        extraExtraLarge = hero,
    )
}

/** Maps Bento roles onto every Material 3 slot (design-system/android.md §1 table). */
internal fun bentoColorScheme(c: BentoColors, dark: Boolean): ColorScheme {
    // Tertiary and secondary are deliberately neutral: shu is never a Material role.
    val build = if (dark) ::darkScheme else ::lightScheme
    return build(c)
}

private fun lightScheme(c: BentoColors): ColorScheme = lightColorScheme(
    primary = c.accent,
    onPrimary = c.onAccent,
    primaryContainer = c.accentSoft,
    onPrimaryContainer = c.accentInk,
    inversePrimary = BentoTokens.DarkColors.accentInk,
    secondary = c.inkMuted,
    onSecondary = c.raised,
    secondaryContainer = c.accentSoft,
    onSecondaryContainer = c.accentInk,
    tertiary = c.inkMuted,
    onTertiary = c.raised,
    tertiaryContainer = c.sunken,
    onTertiaryContainer = c.ink,
    background = c.tray,
    onBackground = c.ink,
    surface = c.surface,
    onSurface = c.ink,
    surfaceVariant = c.subtle,
    onSurfaceVariant = c.inkMuted,
    surfaceTint = Color.Transparent,
    inverseSurface = c.tooltip,
    inverseOnSurface = c.inkInverse,
    error = c.danger,
    onError = c.onDanger,
    errorContainer = c.dangerSoft,
    onErrorContainer = c.dangerInk,
    outline = c.lineStrong,
    outlineVariant = c.line,
    scrim = c.scrim,
    surfaceBright = c.raised,
    surfaceContainer = c.subtle,
    surfaceContainerHigh = c.raised,
    surfaceContainerHighest = c.raised,
    surfaceContainerLow = c.surface,
    surfaceContainerLowest = c.raised,
    surfaceDim = c.sunken,
    primaryFixed = c.accentSoft,
    primaryFixedDim = c.accentSoftHover,
    onPrimaryFixed = c.accentInk,
    onPrimaryFixedVariant = c.accentInk,
    secondaryFixed = c.subtle,
    secondaryFixedDim = c.sunken,
    onSecondaryFixed = c.ink,
    onSecondaryFixedVariant = c.inkMuted,
    tertiaryFixed = c.subtle,
    tertiaryFixedDim = c.sunken,
    onTertiaryFixed = c.ink,
    onTertiaryFixedVariant = c.inkMuted,
)

private fun darkScheme(c: BentoColors): ColorScheme = darkColorScheme(
    primary = c.accent,
    onPrimary = c.onAccent,
    primaryContainer = c.accentSoft,
    onPrimaryContainer = c.accentInk,
    inversePrimary = BentoTokens.LightColors.accentInk,
    secondary = c.inkMuted,
    onSecondary = c.raised,
    secondaryContainer = c.accentSoft,
    onSecondaryContainer = c.accentInk,
    tertiary = c.inkMuted,
    onTertiary = c.raised,
    tertiaryContainer = c.sunken,
    onTertiaryContainer = c.ink,
    background = c.tray,
    onBackground = c.ink,
    surface = c.surface,
    onSurface = c.ink,
    surfaceVariant = c.subtle,
    onSurfaceVariant = c.inkMuted,
    surfaceTint = Color.Transparent,
    inverseSurface = c.tooltip,
    inverseOnSurface = c.inkInverse,
    error = c.danger,
    onError = c.onDanger,
    errorContainer = c.dangerSoft,
    onErrorContainer = c.dangerInk,
    outline = c.lineStrong,
    outlineVariant = c.line,
    scrim = c.scrim,
    surfaceBright = c.raised,
    surfaceContainer = c.subtle,
    surfaceContainerHigh = c.raised,
    surfaceContainerHighest = c.raised,
    surfaceContainerLow = c.surface,
    surfaceContainerLowest = c.raised,
    surfaceDim = c.sunken,
    primaryFixed = c.accentSoft,
    primaryFixedDim = c.accentSoftHover,
    onPrimaryFixed = c.accentInk,
    onPrimaryFixedVariant = c.accentInk,
    secondaryFixed = c.subtle,
    secondaryFixedDim = c.sunken,
    onSecondaryFixed = c.ink,
    onSecondaryFixedVariant = c.inkMuted,
    tertiaryFixed = c.subtle,
    tertiaryFixedDim = c.sunken,
    onTertiaryFixed = c.ink,
    onTertiaryFixedVariant = c.inkMuted,
)
