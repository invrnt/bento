package dev.bento.feature.onboarding

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.telephony.TelephonyManager
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.input.InputTransformation
import androidx.compose.foundation.text.input.TextFieldState
import androidx.compose.foundation.text.input.maxLength
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.foundation.text.input.setTextAndPlaceCursorAtEnd
import androidx.compose.foundation.text.input.then
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.bento.api.generated.TelegramAccountResponse
import dev.bento.designsystem.component.BentoAnnounce
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonSize
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoChip
import dev.bento.designsystem.component.BentoLoader
import dev.bento.designsystem.component.BentoSheet
import dev.bento.designsystem.component.BentoTextField
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.ListRow
import dev.bento.designsystem.component.QrView
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.recovery.Hero
import dev.bento.feature.recovery.SecureWindow
import dev.bento.feature.recovery.SensitiveClipboard
import dev.bento.feature.recovery.SetupScaffold
import dev.bento.feature.recovery.toMatrix
import dev.bento.strings.R as StringsR

/** Copy that changes with where the sign-in is used (first run, join without the other device, reconnect). */
data class SignInCopy(val title: Int = StringsR.string.onboarding_signin_title, val body: Int = StringsR.string.onboarding_signin_body)

/**
 * Conecta tu Telegram (product/android.md §4.1 step 2): `Continuar con Telegram` (login-token link opened in the
 * Telegram app on this phone), `Usar mi número de teléfono` (country, number, code with paste chip and auto-submit,
 * resend countdown, 2FA), `Mostrar código QR` for another phone. Calls [onAuthorized] once.
 */
@Composable
fun TelegramSignInScreen(
    onAuthorized: (TelegramAccountResponse) -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
    copy: SignInCopy = SignInCopy(),
    viewModel: TelegramSignInViewModel = hiltViewModel()
) {
    val context = LocalContext.current
    val state by viewModel.state.collectAsStateWithLifecycle()
    val authorized by rememberUpdatedState(onAuthorized)
    val telegramApp = remember { TelegramApp.canOpenLogin(context) }
    var clipboardCode by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) {
        val telephony = context.getSystemService(TelephonyManager::class.java)
        viewModel.start(telephony?.simCountryIso, telephony?.networkCountryIso)
    }
    LaunchedEffect(viewModel) {
        viewModel.effect.collect { effect ->
            when (effect) {
                is SignInEffect.OpenTelegramLogin -> if (!TelegramApp.openLogin(context, effect.url)) viewModel.telegramAppMissing()
            }
        }
    }
    LaunchedEffect(state.authorized) { state.authorized?.let(authorized) }
    LifecycleResumeEffect(state.view) {
        viewModel.onResume()
        clipboardCode = if (state.view == SignInView.Code) SensitiveClipboard.readText(context)?.let(::telegramCodeIn) else null
        onPauseOrDispose {}
    }
    BackHandler { if (!viewModel.back()) onBack() }

    TelegramSignInContent(
        state = state,
        telegramAppInstalled = telegramApp,
        copy = copy,
        clipboardCode = clipboardCode,
        actions = SignInActions(
            onContinueWithTelegram = viewModel::continueWithTelegram,
            onUsePhone = viewModel::usePhone,
            onShowQr = viewModel::showQr,
            onPickCountry = viewModel::selectCountry,
            onNationalChange = viewModel::editNational,
            onSubmitPhone = viewModel::submitPhone,
            onSubmitCode = viewModel::submitCode,
            onResend = viewModel::resendCode,
            onChangeNumber = viewModel::changeNumber,
            onSubmitPassword = viewModel::submitPassword,
            onOpenTelegram = { TelegramApp.open(context) },
            onForgotPassword = { TelegramApp.openPasswordHelp(context) },
            onEdited = viewModel::clearProblem,
            onBack = { if (!viewModel.back()) onBack() }
        ),
        modifier = modifier
    )
}

/** Callbacks of the stateless sign-in content (tests drive these directly). */
data class SignInActions(
    val onContinueWithTelegram: () -> Unit = {},
    val onUsePhone: () -> Unit = {},
    val onShowQr: () -> Unit = {},
    val onPickCountry: (Country) -> Unit = {},
    val onNationalChange: (String) -> Unit = {},
    val onSubmitPhone: () -> Unit = {},
    val onSubmitCode: (String) -> Unit = {},
    val onResend: () -> Unit = {},
    val onChangeNumber: () -> Unit = {},
    val onSubmitPassword: (String) -> Unit = {},
    val onOpenTelegram: () -> Unit = {},
    val onForgotPassword: () -> Unit = {},
    val onEdited: () -> Unit = {},
    val onBack: () -> Unit = {}
)

@Composable
fun TelegramSignInContent(
    state: SignInState,
    telegramAppInstalled: Boolean,
    actions: SignInActions,
    modifier: Modifier = Modifier,
    copy: SignInCopy = SignInCopy(),
    clipboardCode: String? = null
) {
    when (state.view) {
        SignInView.Options -> OptionsStep(state, telegramAppInstalled, copy, actions, modifier)
        SignInView.Phone -> PhoneStep(state, actions, modifier)
        SignInView.Code -> CodeStep(state, clipboardCode, actions, modifier)
        SignInView.Password -> PasswordStep(state, actions, modifier)
        SignInView.Qr -> QrStep(state, actions, modifier)
    }
}

@Composable
private fun OptionsStep(state: SignInState, telegramApp: Boolean, copy: SignInCopy, actions: SignInActions, modifier: Modifier) {
    SetupScaffold(
        title = stringResource(copy.title),
        body = stringResource(copy.body),
        hero = Hero.Icon(BentoIcons.Send),
        onBack = actions.onBack,
        modifier = modifier,
        actions = {
            if (telegramApp) {
                BentoButton(
                    stringResource(StringsR.string.common_telegram_continue),
                    actions.onContinueWithTelegram,
                    Modifier.fillMaxWidth(),
                    variant = BentoButtonVariant.Primary,
                    size = BentoButtonSize.Large,
                    loading = state.busy && !state.awaitingTelegramApp
                )
            }
            BentoButton(
                stringResource(StringsR.string.onboarding_signin_use_phone),
                actions.onUsePhone,
                Modifier.fillMaxWidth(),
                variant = if (telegramApp) BentoButtonVariant.Secondary else BentoButtonVariant.Primary,
                size = BentoButtonSize.Large
            )
            BentoButton(
                stringResource(StringsR.string.onboarding_signin_show_qr),
                actions.onShowQr,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Ghost
            )
        }
    ) {
        if (state.awaitingTelegramApp) {
            WaitingLine(stringResource(StringsR.string.onboarding_signin_waiting_telegram))
            Spacer(Modifier.height(12.dp))
            BentoButton(
                stringResource(StringsR.string.onboarding_signin_reopen_telegram),
                actions.onContinueWithTelegram,
                leadingIcon = BentoIcons.ExternalLink
            )
        } else if (telegramApp) {
            Text(
                stringResource(StringsR.string.onboarding_signin_telegram_note),
                color = BentoTheme.colors.inkMuted,
                style = BentoTheme.typography.body
            )
        } else {
            Callout(tone = CalloutTone.Neutral, body = stringResource(StringsR.string.onboarding_signin_no_telegram_app))
        }
        ProblemCallout(state)
        Spacer(Modifier.height(24.dp))
        Text(
            stringResource(StringsR.string.common_telegram_api_notice),
            color = BentoTheme.colors.inkMuted,
            style = BentoTheme.typography.metadata
        )
    }
}

@Composable
private fun PhoneStep(state: SignInState, actions: SignInActions, modifier: Modifier, number: TextFieldState = rememberTextFieldState()) {
    var picking by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(number) { snapshotFlow { number.text.toString() }.collect(actions.onNationalChange) }
    LaunchedEffect(state.national) {
        val formatted = PhoneNumbers.formatNational(state.national)
        if (number.text.toString() != formatted) number.setTextAndPlaceCursorAtEnd(formatted)
    }
    SetupScaffold(
        title = stringResource(StringsR.string.onboarding_phone_title),
        body = stringResource(StringsR.string.onboarding_phone_body),
        hero = Hero.Icon(BentoIcons.Smartphone),
        onBack = actions.onBack,
        modifier = modifier,
        actions = {
            BentoButton(
                stringResource(StringsR.string.onboarding_phone_submit),
                actions.onSubmitPhone,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Primary,
                size = BentoButtonSize.Large,
                enabled = state.national.length >= PHONE_MIN && state.floodWaitSeconds == null,
                loading = state.busy
            )
        }
    ) {
        ListRow(
            headline = state.country.name(),
            supporting = stringResource(StringsR.string.onboarding_phone_country_code, state.country.dialCode),
            leading = { Text(state.country.flag, style = BentoTheme.typography.sectionTitle) },
            trailing = {
                dev.bento.designsystem.component.BentoIcon(
                    BentoIcons.ChevronDown,
                    contentDescription = null,
                    tint = BentoTheme.colors.inkMuted
                )
            },
            onClick = { picking = true },
            onClickLabel = stringResource(StringsR.string.onboarding_phone_country_change)
        )
        Spacer(Modifier.height(12.dp))
        BentoTextField(
            state = number,
            label = stringResource(StringsR.string.onboarding_phone_label),
            hint = stringResource(StringsR.string.onboarding_phone_hint, "+${state.country.dialCode}"),
            error = if (state.problem ==
                SignInProblem.PhoneInvalid
            ) {
                stringResource(StringsR.string.onboarding_error_phone_invalid)
            } else {
                null
            },
            placeholder = stringResource(StringsR.string.onboarding_phone_placeholder),
            leadingIcon = null,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone, imeAction = ImeAction.Send),
            onKeyboardAction = { actions.onSubmitPhone() },
            inputTransformation = InputTransformation.maxLength(PHONE_FIELD_MAX)
        )
        ProblemCallout(state, except = setOf(SignInProblem.PhoneInvalid))
    }
    if (picking) {
        CountrySheet(
            onPick = {
                actions.onPickCountry(it)
                picking = false
            },
            onDismiss = { picking = false }
        )
    }
}

@Composable
private fun CountrySheet(onPick: (Country) -> Unit, onDismiss: () -> Unit, query: TextFieldState = rememberTextFieldState()) {
    BentoSheet(onDismissRequest = onDismiss, title = stringResource(StringsR.string.onboarding_phone_country_title)) {
        Column(Modifier.padding(horizontal = 16.dp)) {
            BentoTextField(
                state = query,
                label = stringResource(StringsR.string.onboarding_phone_country_search),
                hideLabel = true,
                placeholder = stringResource(StringsR.string.onboarding_phone_country_search),
                leadingIcon = BentoIcons.Search
            )
            val countries = remember(query.text) { PhoneNumbers.search(query.text.toString()) }
            LazyColumn(Modifier.fillMaxWidth().height(420.dp).padding(top = 8.dp)) {
                items(countries, key = { it.iso }) { country ->
                    ListRow(
                        headline = country.name(),
                        supporting = "+${country.dialCode}",
                        leading = { Text(country.flag, style = BentoTheme.typography.sectionTitle) },
                        onClick = { onPick(country) }
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun CodeStep(
    state: SignInState,
    clipboardCode: String?,
    actions: SignInActions,
    modifier: Modifier,
    code: TextFieldState = rememberTextFieldState()
) {
    SecureWindow() // the Telegram login code (SEC-08)
    LaunchedEffect(code) {
        snapshotFlow { code.text.toString() }.collect {
            actions.onEdited()
            if (it.length == TelegramSignInViewModel.CODE_LENGTH) actions.onSubmitCode(it)
        }
    }
    LaunchedEffect(state.problem) { if (state.problem == SignInProblem.CodeInvalid) code.setTextAndPlaceCursorAtEnd("") }
    val phone = "+${state.country.dialCode} ${PhoneNumbers.formatNational(state.national)}"
    SetupScaffold(
        title = stringResource(StringsR.string.onboarding_code_title),
        body = stringResource(StringsR.string.onboarding_code_body, phone),
        hero = Hero.Icon(BentoIcons.Send),
        onBack = actions.onBack,
        modifier = modifier,
        actions = {
            BentoButton(
                stringResource(StringsR.string.onboarding_code_open_telegram),
                actions.onOpenTelegram,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Secondary,
                size = BentoButtonSize.Large,
                leadingIcon = BentoIcons.ExternalLink
            )
            // Wraps instead of squeezing: at 200 % font "Reenviar en 0:42" would otherwise break mid-word.
            FlowRow(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                BentoButton(
                    stringResource(StringsR.string.onboarding_code_change_number),
                    actions.onChangeNumber,
                    variant = BentoButtonVariant.Ghost
                )
                BentoButton(
                    text = if (state.resendSeconds > 0) {
                        stringResource(StringsR.string.onboarding_code_resend_in, formatSeconds(state.resendSeconds.toLong()))
                    } else {
                        stringResource(StringsR.string.onboarding_code_resend)
                    },
                    onClick = actions.onResend,
                    variant = BentoButtonVariant.Ghost,
                    enabled = state.resendSeconds == 0 && !state.busy
                )
            }
        }
    ) {
        BentoTextField(
            state = code,
            label = stringResource(StringsR.string.onboarding_code_label),
            hint = stringResource(StringsR.string.onboarding_code_hint),
            error = if (state.problem == SignInProblem.CodeInvalid) stringResource(StringsR.string.onboarding_error_code_invalid) else null,
            enabled = !state.busy,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword, imeAction = ImeAction.Done),
            onKeyboardAction = { actions.onSubmitCode(code.text.toString()) },
            inputTransformation = DigitsOnly.then(InputTransformation.maxLength(CODE_FIELD_MAX))
        )
        if (clipboardCode != null && code.text.isEmpty()) {
            Spacer(Modifier.height(12.dp))
            BentoChip(
                label = stringResource(StringsR.string.onboarding_code_paste, clipboardCode),
                onClick = {
                    code.setTextAndPlaceCursorAtEnd(clipboardCode)
                    if (clipboardCode.length != TelegramSignInViewModel.CODE_LENGTH) actions.onSubmitCode(clipboardCode)
                },
                leadingIcon = BentoIcons.ClipboardPaste
            )
        }
        if (state.busy) {
            Spacer(Modifier.height(16.dp))
            WaitingLine(stringResource(StringsR.string.onboarding_code_checking))
        }
        ProblemCallout(state, except = setOf(SignInProblem.CodeInvalid))
    }
}

@Composable
private fun PasswordStep(
    state: SignInState,
    actions: SignInActions,
    modifier: Modifier,
    password: TextFieldState = rememberTextFieldState()
) {
    SecureWindow()
    LaunchedEffect(password) { snapshotFlow { password.text.toString() }.collect { actions.onEdited() } }
    val hint = state.status?.passwordHint?.takeIf { it.isNotBlank() }
    SetupScaffold(
        title = stringResource(StringsR.string.onboarding_password_title),
        body = stringResource(StringsR.string.onboarding_password_body),
        hero = Hero.Icon(BentoIcons.KeyRound),
        onBack = actions.onBack,
        modifier = modifier,
        actions = {
            BentoButton(
                stringResource(StringsR.string.onboarding_password_submit),
                { actions.onSubmitPassword(password.text.toString()) },
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Primary,
                size = BentoButtonSize.Large,
                enabled = password.text.isNotEmpty() && state.floodWaitSeconds == null,
                loading = state.busy
            )
            BentoButton(
                stringResource(StringsR.string.onboarding_password_forgot),
                actions.onForgotPassword,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Ghost,
                trailingIcon = BentoIcons.ExternalLink
            )
        }
    ) {
        if (hint != null) {
            Text(
                stringResource(StringsR.string.onboarding_password_hint, hint),
                color = BentoTheme.colors.inkMuted,
                style = BentoTheme.typography.body,
                modifier = Modifier.padding(bottom = 12.dp)
            )
        }
        BentoTextField(
            state = password,
            label = stringResource(StringsR.string.onboarding_password_label),
            error = if (state.problem ==
                SignInProblem.PasswordInvalid
            ) {
                stringResource(StringsR.string.onboarding_error_password_invalid)
            } else {
                null
            },
            secure = true,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
            onKeyboardAction = { actions.onSubmitPassword(password.text.toString()) }
        )
        ProblemCallout(state, except = setOf(SignInProblem.PasswordInvalid))
    }
}

@Composable
private fun QrStep(state: SignInState, actions: SignInActions, modifier: Modifier) {
    val qr = state.status?.qr
    SetupScaffold(
        title = stringResource(StringsR.string.onboarding_qr_title),
        body = stringResource(StringsR.string.onboarding_qr_body),
        onBack = actions.onBack,
        modifier = modifier,
        actions = {
            BentoButton(
                stringResource(StringsR.string.onboarding_signin_use_phone),
                actions.onUsePhone,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Secondary
            )
        }
    ) {
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
            if (qr != null) {
                QrView(qr.toMatrix(), Modifier.fillMaxWidth(0.8f), contentDescription = stringResource(StringsR.string.onboarding_qr_label))
            } else {
                BentoLoader(size = 48.dp, contentDescription = stringResource(StringsR.string.onboarding_qr_loading))
            }
        }
        Spacer(Modifier.height(20.dp))
        listOf(
            StringsR.string.onboarding_qr_step1,
            StringsR.string.onboarding_qr_step2,
            StringsR.string.onboarding_qr_step3
        ).forEachIndexed {
                index,
                step
            ->
            Row(Modifier.padding(vertical = 6.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("${index + 1}.", color = BentoTheme.colors.accentInk, style = BentoTheme.typography.labelStrong)
                Text(stringResource(step), color = BentoTheme.colors.ink, style = BentoTheme.typography.body)
            }
        }
        Spacer(Modifier.height(8.dp))
        WaitingLine(stringResource(StringsR.string.onboarding_qr_waiting))
        ProblemCallout(state)
    }
}

@Composable
internal fun WaitingLine(text: String) {
    Row(
        Modifier.semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        dev.bento.designsystem.component.ProgressRing(progress = null, size = 20.dp)
        Text(text, color = BentoTheme.colors.inkMuted, style = BentoTheme.typography.label)
    }
}

/** The one problem line under a step; field-level problems are shown on their field instead. */
@Composable
private fun ProblemCallout(state: SignInState, except: Set<SignInProblem> = emptySet()) {
    val problem = state.problem ?: return
    if (problem in except) return
    Spacer(Modifier.height(16.dp))
    val wait = state.floodWaitSeconds
    when (problem) {
        SignInProblem.FloodWait -> Callout(
            tone = CalloutTone.Warning,
            title = stringResource(StringsR.string.onboarding_error_flood_title),
            body = if (wait !=
                null
            ) {
                stringResource(StringsR.string.onboarding_error_flood_body, formatWait(wait))
            } else {
                stringResource(StringsR.string.onboarding_error_flood_ready)
            },
            icon = BentoIcons.Timer,
            announce = BentoAnnounce.Polite
        )

        else -> Callout(
            tone = if (problem == SignInProblem.TelegramAppMissing) CalloutTone.Neutral else CalloutTone.Danger,
            body = stringResource(problemText(problem)),
            announce = BentoAnnounce.Assertive
        )
    }
}

internal fun problemText(problem: SignInProblem): Int = when (problem) {
    SignInProblem.CodeInvalid -> StringsR.string.onboarding_error_code_invalid
    SignInProblem.Expired -> StringsR.string.onboarding_error_expired
    SignInProblem.PasswordInvalid -> StringsR.string.onboarding_error_password_invalid
    SignInProblem.PhoneInvalid -> StringsR.string.onboarding_error_phone_invalid
    SignInProblem.Network -> StringsR.string.onboarding_error_network
    SignInProblem.NotAvailable -> StringsR.string.onboarding_error_not_available
    SignInProblem.TelegramAppMissing -> StringsR.string.onboarding_error_telegram_app_missing
    SignInProblem.FloodWait, SignInProblem.Generic -> StringsR.string.onboarding_error_generic
}

/** "3 min" / "45 s" for flood waits (plural-aware). */
@Composable
internal fun formatWait(seconds: Long): String = if (seconds >= 60) {
    val minutes = ((seconds + 59) / 60).toInt()
    pluralStringResource(StringsR.plurals.common_duration_minutes, minutes, minutes)
} else {
    pluralStringResource(StringsR.plurals.common_duration_seconds, seconds.toInt(), seconds.toInt())
}

internal fun formatSeconds(seconds: Long): String = "%d:%02d".format(seconds / 60, seconds % 60)

/** A 5-6 digit Telegram code in clipboard text ("Código de inicio de sesión: 12345"), or null. */
fun telegramCodeIn(text: String): String? = Regex("(?<!\\d)(\\d{5,6})(?!\\d)").findAll(text).map { it.value }.singleOrNull()

private val DigitsOnly = InputTransformation {
    val digits = asCharSequence().filter(Char::isDigit).toString()
    if (digits != asCharSequence().toString()) replace(0, length, digits)
}

private const val PHONE_MIN = 6
private const val PHONE_FIELD_MAX = 20
private const val CODE_FIELD_MAX = 6

/** The Telegram app on this phone: login-token links, opening it to read the code, password help. */
object TelegramApp {
    private const val PROBE = "tg://login?token=probe"
    private const val PASSWORD_HELP = "https://telegram.org/faq#q-i-forgot-my-password"

    fun canOpenLogin(context: Context): Boolean =
        runCatching {
            context.packageManager.queryIntentActivities(Intent(Intent.ACTION_VIEW, Uri.parse(PROBE)), 0).isNotEmpty()
        }.getOrDefault(false)

    fun openLogin(context: Context, url: String): Boolean = try {
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        true
    } catch (_: ActivityNotFoundException) {
        false
    }

    /** Opens the Telegram app (where the login code arrives); false when none is installed. */
    fun open(context: Context): Boolean {
        val pm = context.packageManager
        val target = runCatching { pm.queryIntentActivities(Intent(Intent.ACTION_VIEW, Uri.parse(PROBE)), 0) }.getOrNull()
            ?.firstOrNull()?.activityInfo?.packageName ?: return false
        val launch = pm.getLaunchIntentForPackage(target) ?: return false
        return runCatching { context.startActivity(launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }.isSuccess
    }

    fun openPasswordHelp(context: Context) {
        runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(PASSWORD_HELP)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
    }
}
