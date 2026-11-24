package dev.bento.designsystem.specimen

import android.content.res.Configuration
import androidx.compose.foundation.background
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import dev.bento.designsystem.theme.BentoTheme

/** Light, dark, 200 % font, compact and expanded widths (design-system/android.md §9). */
@Preview(name = "Light", widthDp = 411)
@Preview(name = "Dark", widthDp = 411, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Preview(name = "Font 200 %", widthDp = 411, fontScale = 2f)
@Preview(name = "Compact", widthDp = 320)
@Preview(name = "Expanded", widthDp = 840)
public annotation class BentoPreviews

/** Renders one specimen on the `surface` compartment of the current theme. */
@Composable
public fun SpecimenFrame(dark: Boolean = isSystemInDarkTheme(), reducedMotion: Boolean = false, content: @Composable () -> Unit) {
    BentoTheme(darkTheme = dark, reducedMotion = reducedMotion) {
        Box(Modifier.background(BentoTheme.colors.surface)) { content() }
    }
}

@Composable
private fun SpecimenPreview(name: String) {
    SpecimenFrame { BentoSpecimens.first { it.name == name }.content() }
}

@BentoPreviews
@Composable
private fun BrandPreview() = SpecimenPreview("brand")

@BentoPreviews
@Composable
private fun LoaderPreview() = SpecimenPreview("loader")

@BentoPreviews
@Composable
private fun TopBarPreview() = SpecimenPreview("top-bar")

@BentoPreviews
@Composable
private fun StatusAvatarPreview() = SpecimenPreview("status-avatar")

@BentoPreviews
@Composable
private fun NavigationBarPreview() = SpecimenPreview("navigation-bar")

@BentoPreviews
@Composable
private fun NavigationRailPreview() = SpecimenPreview("navigation-rail")

@BentoPreviews
@Composable
private fun ButtonVariantsPreview() = SpecimenPreview("button-variants")

@BentoPreviews
@Composable
private fun ButtonStatesPreview() = SpecimenPreview("button-states")

@BentoPreviews
@Composable
private fun IconButtonPreview() = SpecimenPreview("icon-button")

@BentoPreviews
@Composable
private fun FabPreview() = SpecimenPreview("fab")

@BentoPreviews
@Composable
private fun TextFieldPreview() = SpecimenPreview("text-field")

@BentoPreviews
@Composable
private fun CodeFieldPreview() = SpecimenPreview("code-field")

@BentoPreviews
@Composable
private fun SegmentedPreview() = SpecimenPreview("segmented")

@BentoPreviews
@Composable
private fun ChipsPreview() = SpecimenPreview("chips")

@BentoPreviews
@Composable
private fun SheetPreview() = SpecimenPreview("sheet")

@BentoPreviews
@Composable
private fun DialogPreview() = SpecimenPreview("dialog")

@BentoPreviews
@Composable
private fun CalloutPreview() = SpecimenPreview("callout")

@BentoPreviews
@Composable
private fun AttentionCardPreview() = SpecimenPreview("attention-card")

@BentoPreviews
@Composable
private fun BadgePreview() = SpecimenPreview("badge")

@BentoPreviews
@Composable
private fun ProgressPreview() = SpecimenPreview("progress")

@BentoPreviews
@Composable
private fun EmptyStatePreview() = SpecimenPreview("empty-state")

@BentoPreviews
@Composable
private fun ErrorStatePreview() = SpecimenPreview("error-state")

@BentoPreviews
@Composable
private fun ThumbnailPreview() = SpecimenPreview("thumbnail")

@BentoPreviews
@Composable
private fun FloatingActionBarPreview() = SpecimenPreview("floating-action-bar")

@BentoPreviews
@Composable
private fun SnackbarPreview() = SpecimenPreview("snackbar")

@BentoPreviews
@Composable
private fun SasEmojiPreview() = SpecimenPreview("sas-emoji")

@BentoPreviews
@Composable
private fun QrPreview() = SpecimenPreview("qr")

@BentoPreviews
@Composable
private fun KindIconPreview() = SpecimenPreview("kind-icon")

@BentoPreviews
@Composable
private fun ListRowPreview() = SpecimenPreview("list-row")

@BentoPreviews
@Composable
private fun SectionHeaderPreview() = SpecimenPreview("section-header")

@BentoPreviews
@Composable
private fun SettingsRowPreview() = SpecimenPreview("settings-row")

@BentoPreviews
@Composable
private fun IconsPreview() = SpecimenPreview("icons")

@BentoPreviews
@Composable
private fun TypographyPreview() = SpecimenPreview("typography")

@BentoPreviews
@Composable
private fun PalettePreview() = SpecimenPreview("palette")
