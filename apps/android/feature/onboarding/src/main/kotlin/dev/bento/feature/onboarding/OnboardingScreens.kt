package dev.bento.feature.onboarding

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.bento.api.generated.TelegramAccountResponse
import dev.bento.designsystem.component.BentoAnnounce
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonSize
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.BentoSheet
import dev.bento.designsystem.component.BrandMark
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.ProgressRing
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.recovery.Hero
import dev.bento.feature.recovery.HeroTone
import dev.bento.feature.recovery.KitOccasion
import dev.bento.feature.recovery.RecoveryKitScreen
import dev.bento.feature.recovery.SetupScaffold
import dev.bento.strings.R as StringsR

/**
 * The first-run flow (product/android.md §4.1) as one destination. [reconnect] starts on "Bento se desconectó de
 * Telegram" instead of the welcome (session revoked, §11). Navigation leaves through the callbacks.
 */
@Suppress("CyclomaticComplexMethod") // one branch per step
@Composable
fun OnboardingScreen(
    reconnect: Boolean,
    onJoin: () -> Unit,
    onExistingVault: () -> Unit,
    onBackupSetup: () -> Unit,
    onFinished: () -> Unit,
    onExit: () -> Unit,
    modifier: Modifier = Modifier,
    onRemoved: () -> Unit = onExistingVault,
    viewModel: OnboardingViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    LaunchedEffect(reconnect) { viewModel.begin(reconnect) }
    LaunchedEffect(viewModel) {
        viewModel.effect.collect { effect ->
            when (effect) {
                OnboardingEffect.ExistingVault -> onExistingVault()
                OnboardingEffect.OpenBackupSetup -> onBackupSetup()
                OnboardingEffect.Finished -> onFinished()
                OnboardingEffect.RemovedWhileAway -> onRemoved()
            }
        }
    }
    when (state.step) {
        OnboardingStep.Welcome -> {
            WelcomeContent(onStart = viewModel::start, onJoin = onJoin, onLocalOnly = {
                viewModel.showLocalSheet(true)
            }, modifier = modifier)
            if (state.localSheet) LocalModeSheet(onConfirm = viewModel::confirmLocalMode, onDismiss = { viewModel.showLocalSheet(false) })
        }

        OnboardingStep.Reconnect -> ReconnectContent(onReconnect = viewModel::start, onLater = onExit, modifier = modifier)

        OnboardingStep.SignIn -> TelegramSignInScreen(
            onAuthorized = { account -> if (reconnect) viewModel.reconnected() else viewModel.authorized(account) },
            onBack = { viewModel.backToStart(reconnect) },
            copy = if (reconnect) {
                SignInCopy(
                    StringsR.string.onboarding_reconnect_signin_title,
                    StringsR.string.onboarding_reconnect_signin_body
                )
            } else {
                SignInCopy()
            },
            modifier = modifier
        )

        OnboardingStep.Creating -> {
            BackHandler {} // the vault is being created; leaving would not stop it
            CreatingContent(state.account, state.avatar, state.creating, onRetry = viewModel::create, modifier = modifier)
        }

        OnboardingStep.Notifications -> NotificationsStep(onDone = viewModel::notificationsDone, modifier = modifier)

        OnboardingStep.Kit -> state.kit?.let { kit ->
            RecoveryKitScreen(
                code = kit.code,
                qr = kit.qr,
                occasion = KitOccasion.FirstRun,
                accountName = state.account?.displayName,
                vaultCreatedAt = kit.createdAt,
                onConfirmed = viewModel::kitDone,
                onLater = viewModel::kitDone,
                modifier = modifier
            )
        } ?: LaunchedEffect(Unit) { viewModel.kitDone() }

        OnboardingStep.Done -> DoneContent(onFinish = viewModel::finish, modifier = modifier)
    }
}

/** Bienvenida. */
@Composable
fun WelcomeContent(onStart: () -> Unit, onJoin: () -> Unit, onLocalOnly: () -> Unit, modifier: Modifier = Modifier) {
    SetupScaffold(
        title = stringResource(StringsR.string.onboarding_welcome_title),
        hero = Hero.Custom { BrandMark(size = 64.dp, contentDescription = stringResource(StringsR.string.app_name)) },
        modifier = modifier,
        actions = {
            BentoButton(
                stringResource(StringsR.string.onboarding_welcome_start),
                onStart,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Primary,
                size = BentoButtonSize.Large
            )
            BentoButton(
                stringResource(StringsR.string.onboarding_welcome_join),
                onJoin,
                Modifier.fillMaxWidth(),
                size = BentoButtonSize.Large
            )
            BentoButton(
                stringResource(StringsR.string.onboarding_welcome_local),
                onLocalOnly,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Ghost
            )
        }
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Point(BentoIcons.Cloud, stringResource(StringsR.string.onboarding_welcome_point_space))
            Point(BentoIcons.Lock, stringResource(StringsR.string.onboarding_welcome_point_encrypted))
            Point(BentoIcons.MonitorSmartphone, stringResource(StringsR.string.onboarding_welcome_point_devices))
        }
        Spacer(Modifier.height(24.dp))
        Text(
            stringResource(StringsR.string.common_telegram_api_notice),
            color = BentoTheme.colors.inkMuted,
            style = BentoTheme.typography.metadata
        )
    }
}

@Composable
private fun Point(icon: ImageVector, text: String) {
    val c = BentoTheme.colors
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
        Box(Modifier.size(40.dp).clip(BentoShapes.md).background(c.accentSoft), contentAlignment = Alignment.Center) {
            BentoIcon(icon, contentDescription = null, tint = c.accentInk)
        }
        Text(text, color = c.ink, style = BentoTheme.typography.bodyStrong, modifier = Modifier.weight(1f))
    }
}

/** "Usar solo en este teléfono" confirmation: states that nothing syncs or is backed up. */
@Composable
fun LocalModeSheet(onConfirm: () -> Unit, onDismiss: () -> Unit) {
    BentoSheet(onDismissRequest = onDismiss, title = stringResource(StringsR.string.onboarding_local_title)) {
        LocalModeSheetBody(onConfirm, onDismiss)
    }
}

@Composable
fun LocalModeSheetBody(onConfirm: () -> Unit, onDismiss: () -> Unit) {
    Column(Modifier.padding(horizontal = 24.dp).padding(bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(
            stringResource(StringsR.string.onboarding_local_title),
            color = BentoTheme.colors.ink,
            style = BentoTheme.typography.sectionTitle
        )
        Text(stringResource(StringsR.string.onboarding_local_body), color = BentoTheme.colors.inkMuted, style = BentoTheme.typography.body)
        Text(stringResource(StringsR.string.onboarding_local_later), color = BentoTheme.colors.inkMuted, style = BentoTheme.typography.body)
        Spacer(Modifier.height(4.dp))
        BentoButton(
            stringResource(StringsR.string.onboarding_local_confirm),
            onConfirm,
            Modifier.fillMaxWidth(),
            variant = BentoButtonVariant.Primary,
            size = BentoButtonSize.Large
        )
        BentoButton(
            stringResource(StringsR.string.onboarding_local_cancel),
            onDismiss,
            Modifier.fillMaxWidth(),
            variant = BentoButtonVariant.Ghost
        )
    }
}

/** Creando tu nube: who is connected, the three compartments being prepared, slow and failed states. */
@Composable
fun CreatingContent(
    account: TelegramAccountResponse?,
    avatar: ImageBitmap?,
    state: CreatingState,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier
) {
    SetupScaffold(
        title = stringResource(StringsR.string.onboarding_creating_title),
        body = stringResource(if (state.failed) StringsR.string.onboarding_creating_failed else StringsR.string.onboarding_creating_body),
        hero = if (state.failed) Hero.Icon(BentoIcons.TriangleAlert, HeroTone.Danger) else Hero.Loader,
        modifier = modifier,
        actions = if (state.failed) {
            {
                BentoButton(
                    stringResource(StringsR.string.common_action_retry),
                    onRetry,
                    Modifier.fillMaxWidth(),
                    variant = BentoButtonVariant.Primary,
                    size = BentoButtonSize.Large
                )
            }
        } else {
            null
        }
    ) {
        if (account != null) {
            AccountRow(account, avatar)
            Spacer(Modifier.height(20.dp))
        }
        if (state.failed) {
            Callout(
                tone = CalloutTone.Danger,
                body = stringResource(StringsR.string.onboarding_creating_failed_hint),
                announce = BentoAnnounce.Assertive
            )
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Compartment(stringResource(StringsR.string.onboarding_creating_channels), state.done)
                Compartment(stringResource(StringsR.string.onboarding_creating_folder), state.done)
                Compartment(stringResource(StringsR.string.onboarding_creating_keys), state.done)
            }
            if (state.slow && !state.done) {
                Spacer(Modifier.height(16.dp))
                Callout(
                    tone = CalloutTone.Neutral,
                    body = stringResource(StringsR.string.onboarding_creating_slow),
                    announce = BentoAnnounce.Polite
                )
            }
        }
    }
}

@Composable
private fun Compartment(label: String, done: Boolean) {
    val c = BentoTheme.colors
    val status =
        stringResource(if (done) StringsR.string.onboarding_creating_step_done else StringsR.string.onboarding_creating_step_working)
    val description = stringResource(StringsR.string.common_label_value, label, status)
    Row(
        Modifier.fillMaxWidth().clearAndSetSemantics { contentDescription = description },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Box(Modifier.size(24.dp), contentAlignment = Alignment.Center) {
            if (done) {
                BentoIcon(
                    BentoIcons.CircleCheck,
                    contentDescription = null,
                    tint = c.successInk
                )
            } else {
                ProgressRing(progress = null, size = 20.dp)
            }
        }
        Text(label, color = c.ink, style = BentoTheme.typography.body)
    }
}

@Composable
fun AccountRow(account: TelegramAccountResponse, avatar: ImageBitmap?, modifier: Modifier = Modifier) {
    val c = BentoTheme.colors
    Row(
        modifier
            .fillMaxWidth()
            .clip(BentoShapes.lg)
            .background(c.subtle)
            .border(1.dp, c.line, BentoShapes.lg)
            .padding(12.dp)
            .semantics(mergeDescendants = true) {},
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Box(Modifier.size(44.dp).clip(BentoShapes.full).background(c.accentSoft), contentAlignment = Alignment.Center) {
            if (avatar != null) {
                Image(avatar, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.size(44.dp))
            } else {
                Text(account.displayName.take(1).uppercase(), color = c.accentInk, style = BentoTheme.typography.sectionTitle)
            }
        }
        Column(Modifier.weight(1f)) {
            Text(
                stringResource(StringsR.string.onboarding_connected_as, account.displayName),
                color = c.ink,
                style = BentoTheme.typography.bodyStrong,
                maxLines = 2
            )
            account.username?.let { Text("@$it", color = c.inkMuted, style = BentoTheme.typography.metadata) }
        }
        BentoIcon(BentoIcons.CircleCheck, contentDescription = null, tint = c.successInk)
    }
}

/**
 * Notification permission after the backup choice (Android 13+, §4.1 step 4 / §6): one sentence of why, the system
 * dialog once, and progress stays visible in the app if denied. Skips itself when not needed.
 */
@Composable
fun NotificationsStep(onDone: () -> Unit, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val needed = Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
        ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { onDone() }
    if (!needed) {
        LaunchedEffect(Unit) { onDone() }
        return
    }
    NotificationsContent(onAllow = { launcher.launch(Manifest.permission.POST_NOTIFICATIONS) }, onSkip = onDone, modifier = modifier)
}

@Composable
fun NotificationsContent(onAllow: () -> Unit, onSkip: () -> Unit, modifier: Modifier = Modifier) {
    SetupScaffold(
        title = stringResource(StringsR.string.onboarding_notifications_title),
        body = stringResource(StringsR.string.onboarding_notifications_body),
        hero = Hero.Icon(BentoIcons.Bell),
        modifier = modifier,
        actions = {
            BentoButton(
                stringResource(StringsR.string.onboarding_notifications_allow),
                onAllow,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Primary,
                size = BentoButtonSize.Large
            )
            BentoButton(
                stringResource(StringsR.string.onboarding_not_now),
                onSkip,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Ghost
            )
        }
    ) {
        Text(
            stringResource(StringsR.string.onboarding_notifications_denied_note),
            color = BentoTheme.colors.inkMuted,
            style = BentoTheme.typography.metadata
        )
    }
}

private data class Tip(val icon: ImageVector, val title: Int, val body: Int)

private val tips = listOf(
    Tip(BentoIcons.Share2, StringsR.string.onboarding_done_tip_share_title, StringsR.string.onboarding_done_tip_share_body),
    Tip(BentoIcons.Inbox, StringsR.string.onboarding_done_tip_inbox_title, StringsR.string.onboarding_done_tip_inbox_body),
    Tip(BentoIcons.Search, StringsR.string.onboarding_done_tip_search_title, StringsR.string.onboarding_done_tip_search_body)
)

/** Listo: three swipeable tips and `Ir a mis fotos`. */
@Composable
fun DoneContent(onFinish: () -> Unit, modifier: Modifier = Modifier, initialTip: Int = 0) {
    val pager = rememberPagerState(initialPage = initialTip) { tips.size }
    val c = BentoTheme.colors
    SetupScaffold(
        title = stringResource(StringsR.string.onboarding_done_title),
        body = stringResource(StringsR.string.onboarding_done_body),
        hero = Hero.Icon(BentoIcons.CircleCheck, HeroTone.Success),
        modifier = modifier,
        actions = {
            BentoButton(
                stringResource(StringsR.string.onboarding_done_open),
                onFinish,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Primary,
                size = BentoButtonSize.Large
            )
        }
    ) {
        HorizontalPager(state = pager, pageSpacing = 12.dp, modifier = Modifier.fillMaxWidth()) { page ->
            val tip = tips[page]
            val position = stringResource(StringsR.string.onboarding_done_tip_position, page + 1, tips.size)
            Column(
                Modifier
                    .fillMaxWidth()
                    .heightIn(min = 168.dp)
                    .clip(BentoShapes.lg)
                    .background(c.subtle)
                    .border(1.dp, c.line, BentoShapes.lg)
                    .padding(20.dp)
                    .semantics(mergeDescendants = true) { contentDescription = position },
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Box(Modifier.size(40.dp).clip(BentoShapes.md).background(c.raised), contentAlignment = Alignment.Center) {
                    BentoIcon(tip.icon, contentDescription = null, tint = c.accentInk)
                }
                Text(stringResource(tip.title), color = c.ink, style = BentoTheme.typography.sectionTitle)
                Text(stringResource(tip.body), color = c.inkMuted, style = BentoTheme.typography.body)
            }
        }
        Spacer(Modifier.height(12.dp))
        Row(
            Modifier.fillMaxWidth().clearAndSetSemantics {
            },
            horizontalArrangement = Arrangement.spacedBy(6.dp, Alignment.CenterHorizontally)
        ) {
            repeat(tips.size) { index ->
                Box(
                    Modifier.size(
                        if (index ==
                            pager.currentPage
                        ) {
                            8.dp
                        } else {
                            6.dp
                        }
                    ).clip(BentoShapes.full).background(
                        if (index ==
                            pager.currentPage
                        ) {
                            c.accent
                        } else {
                            c.lineStrong
                        }
                    )
                )
            }
        }
    }
}

/** "Bento se desconectó de Telegram" (§11): the library stays; reconnect or keep browsing. */
@Composable
fun ReconnectContent(onReconnect: () -> Unit, onLater: () -> Unit, modifier: Modifier = Modifier) {
    SetupScaffold(
        title = stringResource(StringsR.string.onboarding_reconnect_title),
        body = stringResource(StringsR.string.onboarding_reconnect_body),
        hero = Hero.Icon(BentoIcons.Unplug, HeroTone.Warning),
        onBack = onLater,
        modifier = modifier,
        actions = {
            BentoButton(
                stringResource(StringsR.string.common_action_reconnect),
                onReconnect,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Primary,
                size = BentoButtonSize.Large
            )
            BentoButton(
                stringResource(StringsR.string.onboarding_reconnect_later),
                onLater,
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Ghost
            )
        }
    ) {
        Text(
            stringResource(StringsR.string.onboarding_reconnect_note),
            color = BentoTheme.colors.inkMuted,
            style = BentoTheme.typography.body,
            textAlign = TextAlign.Start
        )
    }
}
