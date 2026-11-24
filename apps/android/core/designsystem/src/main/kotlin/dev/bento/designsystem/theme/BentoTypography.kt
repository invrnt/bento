package dev.bento.designsystem.theme

import androidx.compose.material3.Typography
import androidx.compose.runtime.Immutable
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import dev.bento.designsystem.R
import dev.bento.designsystem.generated.BentoTokens

/** Geist Variable, instanced at the three brand weights (400 text, 500 controls, 600 titles). */
@OptIn(androidx.compose.ui.text.ExperimentalTextApi::class)
public val GeistFamily: FontFamily = FontFamily(
    listOf(400, 500, 600).map { weight ->
        Font(R.font.geist_variable, FontWeight(weight), variationSettings = FontVariation.Settings(FontVariation.weight(weight)))
    },
)

@OptIn(androidx.compose.ui.text.ExperimentalTextApi::class)
public val GeistMonoFamily: FontFamily = FontFamily(
    listOf(400, 500, 600).map { weight ->
        Font(R.font.geist_mono_variable, FontWeight(weight), variationSettings = FontVariation.Settings(FontVariation.weight(weight)))
    },
)

private const val TABULAR = "tnum"

private fun style(size: Int, line: Int, weight: Int, tracking: Float = 0f, family: FontFamily = GeistFamily, features: String? = null) =
    TextStyle(
        fontFamily = family,
        fontWeight = FontWeight(weight),
        fontSize = size.sp,
        lineHeight = line.sp,
        letterSpacing = tracking.em,
        fontFeatureSettings = features,
        platformStyle = PlatformTextStyle(includeFontPadding = false),
        lineHeightStyle = LineHeightStyle(LineHeightStyle.Alignment.Center, LineHeightStyle.Trim.None),
    )

/**
 * Bento roles with the mobile step-up of design-system/android.md §2: body 15/22, metadata 13/18, labels 14/20,
 * section titles 17/24, month headers 20/28, page titles 24/32, hero numbers 32/38. Nothing below 12 sp.
 */
@Immutable
public data class BentoTypography(
    val hero: TextStyle,
    val pageTitle: TextStyle,
    val monthHeader: TextStyle,
    val sectionTitle: TextStyle,
    val body: TextStyle,
    val bodyStrong: TextStyle,
    val label: TextStyle,
    val labelStrong: TextStyle,
    val metadata: TextStyle,
    val caption: TextStyle,
    val badge: TextStyle,
    /** Codes, sizes and IDs: Geist Mono with tabular figures. */
    val mono: TextStyle,
    val monoLarge: TextStyle,
    /** Tabular figures for counters, sizes and progress in Geist. */
    val numeric: TextStyle,
) {
    /** The 15 baseline Material roles (the expressive "emphasized" roles are not public in Material 3 1.4). */
    internal val material: Typography by lazy {
        Typography(
            displayLarge = hero,
            displayMedium = hero,
            displaySmall = hero,
            headlineLarge = pageTitle,
            headlineMedium = pageTitle,
            headlineSmall = pageTitle,
            titleLarge = monthHeader,
            titleMedium = sectionTitle,
            titleSmall = labelStrong,
            bodyLarge = body,
            bodyMedium = label,
            bodySmall = metadata,
            labelLarge = labelStrong,
            labelMedium = metadata.copy(fontWeight = FontWeight.Medium),
            labelSmall = caption.copy(fontWeight = FontWeight.Medium),
        )
    }

    public companion object {
        private val tight = BentoTokens.Text.trackingTight
        private val tighter = BentoTokens.Text.trackingTighter

        public val Default: BentoTypography = BentoTypography(
            hero = style(32, 38, 600, tighter, features = TABULAR),
            pageTitle = style(24, 32, 600, tighter),
            monthHeader = style(20, 28, 600, tight),
            sectionTitle = style(17, 24, 600, tight),
            body = style(15, 22, 400),
            bodyStrong = style(15, 22, 600),
            label = style(14, 20, 500),
            labelStrong = style(14, 20, 600),
            metadata = style(13, 18, 400),
            caption = style(12, 16, 400),
            badge = style(12, 16, 500),
            mono = style(14, 20, 500, family = GeistMonoFamily, features = TABULAR),
            monoLarge = style(20, 28, 500, tracking = 0.04f, family = GeistMonoFamily, features = TABULAR),
            numeric = style(13, 18, 500, features = TABULAR),
        )
    }
}
