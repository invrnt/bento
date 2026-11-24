package dev.bento.feature.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsBottomHeight
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import dev.bento.designsystem.component.BentoIconButton
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.strings.R as StringsR

/**
 * A settings page: back button + title (a heading), then a scrolling column of sections. [onBack] null hides the back
 * button (the detail pane of the list-detail layout). Content stays readable on wide windows (max 720 dp).
 */
@Composable
fun SettingsPage(
    title: String,
    onBack: (() -> Unit)?,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit
) {
    Column(modifier.fillMaxSize().background(BentoTheme.colors.tray)) {
        Row(
            Modifier.fillMaxWidth().heightIn(min = 56.dp).padding(start = if (onBack != null) 4.dp else 16.dp, end = 16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            if (onBack != null) BentoIconButton(BentoIcons.ArrowLeft, stringResource(StringsR.string.common_action_back), onBack)
            Text(
                title,
                color = BentoTheme.colors.ink,
                style = BentoTheme.typography.pageTitle,
                modifier = Modifier.padding(start = if (onBack != null) 4.dp else 0.dp).semantics { heading() }
            )
        }
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Column(
                Modifier.widthIn(max = 720.dp).fillMaxWidth().padding(bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                content()
            }
            Spacer(Modifier.windowInsetsBottomHeight(WindowInsets.navigationBars))
        }
    }
}

/** A compartment of related rows (`raised`, 14 dp radius) with an optional section title above it. */
@Composable
fun SettingsGroup(modifier: Modifier = Modifier, title: String? = null, content: @Composable ColumnScope.() -> Unit) {
    Column(modifier.fillMaxWidth()) {
        if (title != null) {
            dev.bento.designsystem.component.SectionHeader(title)
        }
        Column(
            Modifier
                .padding(horizontal = 16.dp)
                .fillMaxWidth()
                .background(BentoTheme.colors.raised, BentoShapes.lg)
                .padding(vertical = 4.dp),
            content = content
        )
    }
}

/** Plain explanatory text under a group (privacy, consequences). */
@Composable
fun SettingsNote(text: String, modifier: Modifier = Modifier) {
    Text(
        text,
        color = BentoTheme.colors.inkMuted,
        style = BentoTheme.typography.metadata,
        modifier = modifier.fillMaxWidth().padding(horizontal = 32.dp, vertical = 4.dp)
    )
}

@Composable
internal fun SectionSpacer() = Spacer(Modifier.height(8.dp))
