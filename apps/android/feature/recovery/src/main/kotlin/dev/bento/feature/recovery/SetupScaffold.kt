package dev.bento.feature.recovery

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.BentoIconButton
import dev.bento.designsystem.component.BentoIconSize
import dev.bento.designsystem.component.BentoLoader
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.strings.R as StringsR

/** Tone of the hero tile above a setup screen's title. */
enum class HeroTone { Accent, Success, Warning, Danger }

/** What sits above the title: an icon tile, the loader, or a custom slot (brand mark, avatar). */
sealed interface Hero {
    data class Icon(val icon: ImageVector, val tone: HeroTone = HeroTone.Accent) : Hero

    data object Loader : Hero

    data class Custom(val content: @Composable () -> Unit) : Hero
}

/**
 * Frame for every onboarding, pairing, recovery and device step: optional back button, hero, title (a TalkBack
 * heading), body, scrollable content, and a bottom action area so primary actions stay in the thumb zone
 * (product/android.md §1.3). Content is centered at ≤ 560 dp on wide windows and reflows at 200 % font. In a
 * compact-height window (a phone on its side) the actions scroll after the content instead, so they never cover it.
 */
@Composable
fun SetupScaffold(
    title: String,
    modifier: Modifier = Modifier,
    body: String? = null,
    hero: Hero? = null,
    onBack: (() -> Unit)? = null,
    backLabel: String = stringResource(StringsR.string.common_action_back),
    actions: (@Composable ColumnScope.() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit = {}
) {
    val c = BentoTheme.colors
    val pinActions = LocalConfiguration.current.screenHeightDp >= COMPACT_HEIGHT_DP
    Column(
        modifier
            .fillMaxSize()
            .background(c.surface)
            .windowInsetsPadding(WindowInsets.safeDrawing)
            .imePadding()
    ) {
        Box(Modifier.fillMaxWidth().height(56.dp).padding(horizontal = 4.dp), contentAlignment = Alignment.CenterStart) {
            if (onBack != null) BentoIconButton(BentoIcons.ArrowLeft, backLabel, onBack)
        }
        Column(
            Modifier
                .weight(1f)
                .fillMaxWidth()
                .verticalScroll(rememberScrollState()),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Column(
                Modifier.widthIn(max = 560.dp).fillMaxWidth().padding(horizontal = 24.dp).padding(bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(0.dp)
            ) {
                if (hero != null) {
                    HeroSlot(hero)
                    Spacer(Modifier.height(20.dp))
                }
                Text(
                    title,
                    color = c.ink,
                    style = BentoTheme.typography.pageTitle,
                    modifier = Modifier.semantics { heading() }
                )
                if (body != null) {
                    Spacer(Modifier.height(8.dp))
                    Text(body, color = c.inkMuted, style = BentoTheme.typography.body)
                }
                Spacer(Modifier.height(24.dp))
                content()
                if (actions != null && !pinActions) {
                    Spacer(Modifier.height(24.dp))
                    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) { actions() }
                }
            }
        }
        if (actions != null && pinActions) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .background(c.surface)
                    .padding(horizontal = 24.dp, vertical = 16.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Column(Modifier.widthIn(max = 560.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) { actions() }
            }
        }
    }
}

/** Window size class boundary for compact height (Material). */
private const val COMPACT_HEIGHT_DP = 480

@Composable
private fun HeroSlot(hero: Hero) {
    val c = BentoTheme.colors
    when (hero) {
        is Hero.Icon -> {
            val (soft, ink) = when (hero.tone) {
                HeroTone.Accent -> c.accentSoft to c.accentInk
                HeroTone.Success -> c.successSoft to c.successInk
                HeroTone.Warning -> c.warningSoft to c.warningInk
                HeroTone.Danger -> c.dangerSoft to c.dangerInk
            }
            Box(Modifier.size(56.dp).clip(BentoShapes.lg).background(soft), contentAlignment = Alignment.Center) {
                BentoIcon(hero.icon, contentDescription = null, tint = ink, size = BentoIconSize.Large)
            }
        }

        Hero.Loader -> BentoLoader(size = 56.dp, contentDescription = null)

        is Hero.Custom -> hero.content()
    }
}
