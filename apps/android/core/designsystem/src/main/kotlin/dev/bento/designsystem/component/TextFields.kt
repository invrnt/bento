package dev.bento.designsystem.component

import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.BasicSecureTextField
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.input.InputTransformation
import androidx.compose.foundation.text.input.KeyboardActionHandler
import androidx.compose.foundation.text.input.OutputTransformation
import androidx.compose.foundation.text.input.TextFieldBuffer
import androidx.compose.foundation.text.input.TextFieldDecorator
import androidx.compose.foundation.text.input.TextFieldLineLimits
import androidx.compose.foundation.text.input.TextFieldState
import androidx.compose.foundation.text.input.TextObfuscationMode
import androidx.compose.foundation.text.input.insert
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.error
import androidx.compose.ui.semantics.hideFromAccessibility
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoHaptic
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.designsystem.theme.bentoHaptics
import kotlinx.coroutines.flow.distinctUntilChanged
import dev.bento.strings.R as StringsR

@Composable
private fun FieldFrame(
    label: String,
    hideLabel: Boolean,
    hint: String?,
    error: String?,
    enabled: Boolean,
    modifier: Modifier,
    field: @Composable () -> Unit,
) {
    val c = BentoTheme.colors
    Column(modifier.alpha(if (enabled) 1f else DISABLED_ALPHA), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        // The field node carries label, hint and error for TalkBack; the visible copies are not read twice.
        if (!hideLabel) Text(label, color = c.ink, style = BentoTheme.typography.label, modifier = Modifier.semantics { hideFromAccessibility() })
        field()
        when {
            error != null -> Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                BentoIcon(BentoIcons.CircleAlert, contentDescription = null, tint = c.dangerInk, size = BentoIconSize.Dense, modifier = Modifier.padding(top = 1.dp))
                Text(error, color = c.dangerInk, style = BentoTheme.typography.metadata, modifier = Modifier.semantics { hideFromAccessibility() })
            }
            hint != null -> Text(hint, color = c.inkMuted, style = BentoTheme.typography.metadata, modifier = Modifier.semantics { hideFromAccessibility() })
        }
    }
}

@Composable
private fun fieldBorder(focused: Boolean, error: Boolean): Pair<Color, Dp> {
    val c = BentoTheme.colors
    val target = when {
        error -> c.danger
        focused -> c.focus
        else -> c.line
    }
    val color by animateColorAsState(target, BentoTheme.motion.color(), label = "field-border")
    return color to if (focused) 2.dp else 1.dp
}

@Composable
private fun fieldDecorator(
    minHeight: Dp,
    focused: Boolean,
    error: Boolean,
    leadingIcon: ImageVector?,
    placeholder: String?,
    showPlaceholder: Boolean,
    placeholderStyle: TextStyle,
    trailing: (@Composable () -> Unit)?,
): TextFieldDecorator {
    val c = BentoTheme.colors
    val (borderColor, borderWidth) = fieldBorder(focused, error)
    return TextFieldDecorator { inner ->
        Row(
            Modifier
                .fillMaxWidth()
                .heightIn(min = minHeight)
                .clip(BentoShapes.control)
                .background(c.raised)
                .border(borderWidth, borderColor, BentoShapes.control)
                .padding(start = if (leadingIcon != null) 12.dp else 14.dp, end = if (trailing != null) 2.dp else 14.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (leadingIcon != null) BentoIcon(leadingIcon, contentDescription = null, tint = c.inkSubtle)
            Box(Modifier.weight(1f).padding(vertical = 14.dp)) {
                if (showPlaceholder && placeholder != null) {
                    Text(placeholder, style = placeholderStyle, maxLines = 1, modifier = Modifier.semantics { hideFromAccessibility() })
                }
                inner()
            }
            trailing?.invoke()
        }
    }
}

/**
 * Text field with a label that is always present (visible unless [hideLabel], which keeps it for TalkBack only),
 * optional [hint] and [error]. [secure] masks the value (`BasicSecureTextField`), uses a password keyboard and adds a
 * show/hide toggle.
 */
@Composable
public fun BentoTextField(
    state: TextFieldState,
    label: String,
    modifier: Modifier = Modifier,
    hint: String? = null,
    error: String? = null,
    placeholder: String? = null,
    secure: Boolean = false,
    hideLabel: Boolean = false,
    enabled: Boolean = true,
    singleLine: Boolean = true,
    leadingIcon: ImageVector? = null,
    trailing: (@Composable () -> Unit)? = null,
    keyboardOptions: KeyboardOptions = KeyboardOptions.Default,
    onKeyboardAction: KeyboardActionHandler? = null,
    inputTransformation: InputTransformation? = null,
) {
    val c = BentoTheme.colors
    val interaction = remember { MutableInteractionSource() }
    val focused by interaction.collectIsFocusedAsState()
    var revealed by rememberSaveable { mutableStateOf(false) }
    val textStyle = BentoTheme.typography.body.copy(color = c.ink)
    val description = listOfNotNull(label, hint.takeIf { error == null }).joinToString(". ")
    val semantics = Modifier
        .fillMaxWidth()
        .semantics {
            contentDescription = description
            if (error != null) error(error)
        }
    val revealToggle: (@Composable () -> Unit)? = if (!secure) trailing else {
        {
            BentoIconButton(
                icon = if (revealed) BentoIcons.EyeOff else BentoIcons.Eye,
                contentDescription = stringResource(if (revealed) StringsR.string.ds_password_hide else StringsR.string.ds_password_show),
                onClick = { revealed = !revealed },
                dense = true,
            )
            trailing?.invoke()
        }
    }
    val decorator = fieldDecorator(
        minHeight = 52.dp,
        focused = focused,
        error = error != null,
        leadingIcon = leadingIcon,
        placeholder = placeholder,
        showPlaceholder = state.text.isEmpty(),
        placeholderStyle = textStyle.copy(color = c.inkSubtle),
        trailing = revealToggle,
    )

    FieldFrame(label, hideLabel, hint, error, enabled, modifier) {
        if (secure) {
            BasicSecureTextField(
                state = state,
                modifier = semantics,
                enabled = enabled,
                inputTransformation = inputTransformation,
                textStyle = textStyle,
                keyboardOptions = keyboardOptions.copy(keyboardType = KeyboardType.Password, autoCorrectEnabled = false),
                onKeyboardAction = onKeyboardAction,
                interactionSource = interaction,
                cursorBrush = SolidColor(c.accent),
                decorator = decorator,
                textObfuscationMode = if (revealed) TextObfuscationMode.Visible else TextObfuscationMode.RevealLastTyped,
            )
        } else {
            BasicTextField(
                state = state,
                modifier = semantics,
                enabled = enabled,
                inputTransformation = inputTransformation,
                textStyle = textStyle,
                keyboardOptions = keyboardOptions,
                onKeyboardAction = onKeyboardAction,
                lineLimits = if (singleLine) TextFieldLineLimits.SingleLine else TextFieldLineLimits.MultiLine(),
                interactionSource = interaction,
                cursorBrush = SolidColor(c.accent),
                decorator = decorator,
            )
        }
    }
}

/** Normalizes every edit to Crockford characters (accepting pasted codes and links) and caps the length. */
internal class CrockfordInputTransformation(private val length: Int) : InputTransformation {
    override fun TextFieldBuffer.transformInput() {
        val text = asCharSequence().toString()
        val (code, cursor) = CrockfordCode.normalizeEdit(text, selection.end, length)
        if (code != text) {
            replace(0, this.length, code)
            selection = TextRange(cursor)
        }
    }
}

/** Shows a dash between groups; the state keeps only code characters, so the cursor maps automatically. */
internal class GroupedCodeOutputTransformation(private val groupSize: Int) : OutputTransformation {
    override fun TextFieldBuffer.transformOutput() {
        val groups = (length - 1) / groupSize
        for (group in groups downTo 1) insert(group * groupSize, "-")
    }
}

/**
 * Grouped Crockford input with auto-dash and paste of codes or `bento://join` / `https://…/join#…c=` links.
 * [state] holds normalized characters without dashes (`I/L→1`, `O→0`). Reaching [length] calls [onComplete] once per
 * completion. A new [error] plays the `REJECT` haptic.
 */
@Composable
public fun CodeField(
    state: TextFieldState,
    label: String,
    modifier: Modifier = Modifier,
    length: Int = CrockfordCode.PAIRING_LENGTH,
    groupSize: Int = CrockfordCode.GROUP_SIZE,
    hint: String? = null,
    error: String? = null,
    enabled: Boolean = true,
    imeAction: ImeAction = ImeAction.Done,
    onKeyboardAction: KeyboardActionHandler? = null,
    onComplete: (String) -> Unit = {},
) {
    val c = BentoTheme.colors
    val haptics = bentoHaptics()
    val interaction = remember { MutableInteractionSource() }
    val focused by interaction.collectIsFocusedAsState()
    val style = BentoTheme.typography.monoLarge.copy(color = c.ink)
    val count = state.text.length
    val progress = stringResource(StringsR.string.ds_code_progress, count, length)
    val complete = stringResource(StringsR.string.ds_code_complete)
    val placeholder = remember(length, groupSize) { CrockfordCode.format("X".repeat(length), groupSize) }
    val input = remember(length) { CrockfordInputTransformation(length) }
    val output = remember(groupSize) { GroupedCodeOutputTransformation(groupSize) }
    val currentOnComplete by rememberUpdatedState(onComplete)

    LaunchedEffect(error) { if (error != null) haptics.perform(BentoHaptic.Reject) }
    LaunchedEffect(state, length) {
        snapshotFlow { state.text.toString() }
            .distinctUntilChanged()
            .collect { if (it.length == length) currentOnComplete(it) }
    }

    FieldFrame(label, hideLabel = false, hint = hint, error = error, enabled = enabled, modifier = modifier) {
        BasicTextField(
            state = state,
            modifier = Modifier
                .fillMaxWidth()
                .semantics {
                    contentDescription = label
                    stateDescription = if (count == length) complete else progress
                    if (error != null) error(error)
                },
            enabled = enabled,
            inputTransformation = input,
            outputTransformation = output,
            textStyle = style,
            keyboardOptions = KeyboardOptions(
                capitalization = KeyboardCapitalization.Characters,
                autoCorrectEnabled = false,
                keyboardType = KeyboardType.Ascii,
                imeAction = imeAction,
            ),
            onKeyboardAction = onKeyboardAction,
            lineLimits = TextFieldLineLimits.SingleLine,
            interactionSource = interaction,
            cursorBrush = SolidColor(c.accent),
            decorator = fieldDecorator(
                minHeight = 56.dp,
                focused = focused,
                error = error != null,
                leadingIcon = null,
                placeholder = placeholder,
                showPlaceholder = count == 0,
                placeholderStyle = style.copy(color = c.inkSubtle),
                trailing = null,
            ),
        )
    }
}
