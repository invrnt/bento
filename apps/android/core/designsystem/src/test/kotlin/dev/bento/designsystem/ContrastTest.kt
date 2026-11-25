package dev.bento.designsystem

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import dev.bento.designsystem.generated.BentoTokens
import dev.bento.designsystem.theme.BentoColors
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** brand.md §13: text ≥ 4.5:1 in both themes (every *-ink / *-soft pair included); UI components ≥ 3:1. */
class ContrastTest {
    private fun ratio(a: Color, b: Color): Double {
        val la = a.luminance() + 0.05
        val lb = b.luminance() + 0.05
        return maxOf(la, lb) / minOf(la, lb).toDouble()
    }

    private data class Pair3(val fg: String, val bg: String, val fgColor: Color, val bgColor: Color)

    private fun textPairs(c: BentoColors, light: Boolean): List<Pair3> = buildList {
        val surfaces = listOf("tray" to c.tray, "surface" to c.surface, "raised" to c.raised, "subtle" to c.subtle, "sunken" to c.sunken)
        for ((fg, color) in listOf("ink" to c.ink, "ink-muted" to c.inkMuted)) {
            for ((bg, bgColor) in surfaces) add(Pair3(fg, bg, color, bgColor))
            add(Pair3(fg, "accent-soft", color, c.accentSoft))
        }
        for ((bg, bgColor) in surfaces) add(Pair3("accent-ink", bg, c.accentInk, bgColor))
        add(Pair3("danger-ink", "raised", c.dangerInk, c.raised))
        add(Pair3("danger-ink", "surface", c.dangerInk, c.surface))
        add(Pair3("accent-ink", "accent-soft", c.accentInk, c.accentSoft))
        add(Pair3("success-ink", "success-soft", c.successInk, c.successSoft))
        add(Pair3("warning-ink", "warning-soft", c.warningInk, c.warningSoft))
        add(Pair3("danger-ink", "danger-soft", c.dangerInk, c.dangerSoft))
        add(Pair3("shu-ink", "shu-soft", c.shuInk, c.shuSoft))
        add(Pair3("ink", "danger-soft", c.ink, c.dangerSoft))
        add(Pair3("ink-muted", "danger-soft", c.inkMuted, c.dangerSoft))
        add(Pair3("ink", "warning-soft", c.ink, c.warningSoft))
        add(Pair3("ink-muted", "warning-soft", c.inkMuted, c.warningSoft))
        add(Pair3("on-accent", "accent", c.onAccent, c.accent))
        add(Pair3("on-danger", "danger", c.onDanger, c.danger))
        if (light) {
            // Pressed fills use the hover tokens only in light mode (see buttonColors).
            add(Pair3("on-accent", "accent-hover", c.onAccent, c.accentHover))
            add(Pair3("on-danger", "danger-hover", c.onDanger, c.dangerHover))
        }
        add(Pair3("ink-inverse", "tooltip", c.inkInverse, c.tooltip))
        add(Pair3("white", "media", c.white, BentoTokens.media))
        add(Pair3("white", "media-raised", c.white, BentoTokens.mediaRaised))
    }

    private fun uiPairs(c: BentoColors): List<Pair3> = buildList {
        for ((bg, bgColor) in listOf("tray" to c.tray, "surface" to c.surface, "raised" to c.raised)) {
            add(Pair3("accent", bg, c.accent, bgColor))
            add(Pair3("focus", bg, c.focus, bgColor))
            add(Pair3("ink-subtle (icons)", bg, c.inkSubtle, bgColor))
        }
        add(Pair3("ink-subtle (icons)", "sunken", c.inkSubtle, c.sunken))
        add(Pair3("accent-ink (nav icon)", "accent-soft", c.accentInk, c.accentSoft))
        val kinds = listOf(
            "folder" to (c.kindFolder to c.kindFolderSoft), "pdf" to (c.kindPdf to c.kindPdfSoft), "doc" to (c.kindDoc to c.kindDocSoft),
            "sheet" to (c.kindSheet to c.kindSheetSoft), "slides" to (c.kindSlides to c.kindSlidesSoft),
            "image" to (c.kindImage to c.kindImageSoft),
            "video" to (c.kindVideo to c.kindVideoSoft), "audio" to (c.kindAudio to c.kindAudioSoft),
            "archive" to (c.kindArchive to c.kindArchiveSoft), "text" to (c.kindText to c.kindTextSoft)
        )
        for ((name, pair) in kinds) add(Pair3("kind-$name", "kind-$name-soft", pair.first, pair.second))
    }

    /**
     * Known brand-token failures, reported for brand.md to resolve (agent 37 handoff). Listed explicitly so a new
     * regression still fails and a fixed token makes this test ask for the entry to be removed.
     */
    private val knownUiFailures = setOf("light:kind-folder/kind-folder-soft")

    @Test
    fun textPairsMeetAa() {
        val failures = (
            textPairs(BentoTokens.LightColors, light = true).map { "light" to it } +
                textPairs(BentoTokens.DarkColors, light = false).map { "dark" to it }
            )
            .filter { (_, p) -> ratio(p.fgColor, p.bgColor) < 4.5 }
            .map { (theme, p) -> "$theme:${p.fg}/${p.bg} = ${"%.2f".format(ratio(p.fgColor, p.bgColor))}" }
        assertEquals("Text pairs below 4.5:1", emptyList<String>(), failures)
    }

    @Test
    fun uiPairsMeetThreeToOne() {
        val results = (uiPairs(BentoTokens.LightColors).map { "light" to it } + uiPairs(BentoTokens.DarkColors).map { "dark" to it })
        val failing = results.filter { (_, p) -> ratio(p.fgColor, p.bgColor) < 3.0 }.map { (t, p) -> "$t:${p.fg}/${p.bg}" }.toSet()
        assertEquals("UI pairs below 3:1 (besides the reported brand issues)", knownUiFailures, failing)
    }

    @Test
    fun inkSubtleIsNeverUsedAsTextOnAndroid() {
        // ink-subtle is 3.6–4.3:1 in light mode, so primitives use it only for icons and strokes (handoff notes).
        val offenders = java.io.File("src/main/kotlin").walkTopDown().filter { it.extension == "kt" }.flatMap { file ->
            file.readLines().mapIndexedNotNull { i, line ->
                val textColor = Regex("""(Text\(.*color = c\.inkSubtle|style = .*color = c\.inkSubtle)""")
                if (textColor.containsMatchIn(line)) "${file.name}:${i + 1}" else null
            }
        }.toList()
        assertTrue("ink-subtle used as a text color: $offenders", offenders.isEmpty())
    }
}
