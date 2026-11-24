package dev.bento.designsystem

import androidx.compose.animation.core.TweenSpec
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import dev.bento.designsystem.generated.BentoTokens
import dev.bento.designsystem.theme.BentoMotion
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTypography
import dev.bento.designsystem.theme.GeistFamily
import dev.bento.designsystem.theme.GeistMonoFamily
import dev.bento.designsystem.theme.bentoColorScheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ThemeTest {
    /** Every Color slot of a ColorScheme, read through its public getters (value classes compile to long). */
    private fun slots(scheme: ColorScheme): Map<String, Color> =
        ColorScheme::class.java.methods
            .filter { it.parameterCount == 0 && it.returnType == Long::class.javaPrimitiveType && it.name.startsWith("get") }
            .associate { it.name.removePrefix("get").substringBefore('-') to Color((it.invoke(scheme) as Long).toULong()) }

    @Test
    fun everyMaterialSlotIsABentoToken() {
        for ((dark, tokens, baseline) in listOf(
            Triple(false, BentoTokens.LightColors, lightColorScheme()),
            Triple(true, BentoTokens.DarkColors, darkColorScheme()),
        )) {
            val scheme = slots(bentoColorScheme(tokens, dark))
            // A slot may coincide with the baseline only when the Bento token itself has that value (e.g. white).
            val defaults = slots(baseline)
            val same = scheme.filter { (name, color) -> defaults.getValue(name) == color }
            assertTrue("slots equal to the Material baseline must be plain white/black tokens: $same", same.values.all { it == Color.White || it == Color.Black })
            assertTrue("ColorScheme exposes its slots (${scheme.size})", scheme.size >= 48)
            val allowed = tokens.javaClass.declaredFields.filter { it.type == Long::class.javaPrimitiveType }.map {
                it.isAccessible = true
                Color((it.getLong(tokens)).toULong())
            }.toSet() + BentoTokens.LightColors.accentInk + BentoTokens.DarkColors.accentInk + Color.Transparent
            for ((name, color) in scheme) {
                assertTrue("$name (${if (dark) "dark" else "light"}) is not a Bento token: $color", color in allowed)
            }
        }
    }

    @Test
    fun roleMappingFollowsTheAndroidTable() {
        val c = BentoTokens.LightColors
        val s = bentoColorScheme(c, dark = false)
        assertEquals(c.tray, s.background)
        assertEquals(c.surface, s.surface)
        assertEquals(c.raised, s.surfaceContainerLowest)
        assertEquals(c.subtle, s.surfaceContainer)
        assertEquals(c.raised, s.surfaceContainerHigh)
        assertEquals(c.sunken, s.surfaceDim)
        assertEquals(c.accent, s.primary)
        assertEquals(c.onAccent, s.onPrimary)
        assertEquals(c.accentSoft, s.primaryContainer)
        assertEquals(c.accentInk, s.onPrimaryContainer)
        assertEquals(c.lineStrong, s.outline)
        assertEquals(c.line, s.outlineVariant)
        assertEquals(c.ink, s.onSurface)
        assertEquals(c.inkMuted, s.onSurfaceVariant)
        assertEquals(c.danger, s.error)
        assertEquals(c.dangerSoft, s.errorContainer)
        assertEquals(c.dangerInk, s.onErrorContainer)
        assertNotEquals("shu is never a Material role", c.shu, s.tertiary)
        assertEquals("no tonal elevation tint", Color.Transparent, s.surfaceTint)
    }

    @Test
    fun typographyUsesGeistAndTheMobileScale() {
        val t = BentoTypography.Default
        val styles: List<TextStyle> = listOf(t.hero, t.pageTitle, t.monthHeader, t.sectionTitle, t.body, t.bodyStrong, t.label, t.labelStrong, t.metadata, t.caption, t.badge, t.numeric)
        styles.forEach { assertEquals(GeistFamily, it.fontFamily) }
        assertEquals(GeistMonoFamily, t.mono.fontFamily)
        styles.forEach { assertTrue("no text below 12 sp", it.fontSize.value >= 12f) }
        assertEquals(15f, t.body.fontSize.value)
        assertEquals(22f, t.body.lineHeight.value)
        assertEquals(13f, t.metadata.fontSize.value)
        assertEquals(18f, t.metadata.lineHeight.value)
        assertEquals(17f, t.sectionTitle.fontSize.value)
        assertEquals(20f, t.monthHeader.fontSize.value)
        assertEquals(24f, t.pageTitle.fontSize.value)
        assertEquals(32f, t.hero.fontSize.value)
        assertEquals("tnum", t.hero.fontFeatureSettings)
        assertEquals("tnum", t.mono.fontFeatureSettings)
        val weights = (styles + t.mono).map { it.fontWeight!!.weight }.toSet()
        assertTrue("weights 400/500/600 only: $weights", weights.all { it in setOf(400, 500, 600) })
    }

    @Test
    fun shapesFollowTheNestedRadii() {
        assertEquals(BentoTokens.Radius.controlMobile, 12f.let { androidx.compose.ui.unit.Dp(it) })
        assertEquals(BentoTokens.Radius.lg, androidx.compose.ui.unit.Dp(14f))
        assertEquals(BentoTokens.Radius.xl, androidx.compose.ui.unit.Dp(18f))
        assertTrue(BentoShapes.sheet.bottomStart.toString().contains("0"))
    }

    @Test
    fun reducedMotionTurnsTransformsIntoShortFades() {
        val normal = BentoMotion(reduced = false)
        val reduced = BentoMotion(reduced = true)
        assertEquals(260, (normal.layer<Float>() as TweenSpec).durationMillis)
        assertEquals(180, (normal.state<Float>() as TweenSpec).durationMillis)
        assertEquals(120, (reduced.layer<Float>() as TweenSpec).durationMillis)
        assertEquals(120, (reduced.state<Float>() as TweenSpec).durationMillis)
        assertTrue("follow() is a spring normally", normal.follow<Float>() !is TweenSpec)
        assertEquals(120, (reduced.follow<Float>() as TweenSpec).durationMillis)
        assertEquals(reduced.fadeIn, reduced.slideUpIn)
        assertEquals(reduced.fadeIn, reduced.popIn)
    }
}
