package dev.bento.feature.settings

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.text.format.Formatter
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoDialog
import dev.bento.designsystem.component.BentoSheet
import dev.bento.designsystem.component.BentoTextField
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.ListRow
import dev.bento.designsystem.component.SegmentOption
import dev.bento.designsystem.component.SegmentedButtons
import dev.bento.designsystem.component.SettingsRow
import dev.bento.designsystem.component.SwitchRow
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.recovery.findActivity
import dev.bento.strings.R as StringsR
import java.time.LocalDate

/** Where Ajustes leads outside its own pages (the shell decides the routes). */
data class SettingsNavigation(
    val onBack: () -> Unit = {},
    val onDevices: () -> Unit = {},
    val onRecovery: () -> Unit = {},
    val onReconnect: () -> Unit = {},
    val onImportTelegram: () -> Unit = {},
    val onSignedOut: () -> Unit = {}
)

/** Every interaction of the Ajustes pages; defaults are no-ops for previews and screenshots. */
data class SettingsActions(
    val onTheme: (ThemeChoice) -> Unit = {},
    val onLock: (Boolean) -> Unit = {},
    val onLockTimeout: (LockTimeout) -> Unit = {},
    val onHideRecents: (Boolean) -> Unit = {},
    val onLanguage: (String) -> Unit = {},
    val onSystemLanguage: () -> Unit = {},
    val onOcr: (Boolean) -> Unit = {},
    val onAskSignOut: (Boolean) -> Unit = {},
    val onSignOut: () -> Unit = {},
    val onExportDiagnostics: () -> Unit = {},
    val onClearDiagnostic: () -> Unit = {},
    val onEditRelay: (Boolean) -> Unit = {},
    val onRelay: (String) -> Unit = {},
    val onAskReset: (Boolean) -> Unit = {},
    val onReset: () -> Unit = {},
    val onOpenUrl: (String) -> Unit = {}
)

/**
 * Ajustes (product/android.md §9): account card, then the sections. Compact windows drill in (shared-axis X by the
 * shell's predictive back); ≥ 840 dp is list-detail. Dispositivos and the recovery kit are agent 38's screens.
 */
@Composable
fun SettingsScreen(
    navigation: SettingsNavigation,
    modifier: Modifier = Modifier,
    initialSection: SettingsSection? = null,
    siteUrl: String = "",
    viewModel: SettingsViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val activity = context.findActivity()
    val diagnostics = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/plain")) { uri ->
        uri?.let(viewModel::exportDiagnostics)
    }
    val lockTitle = stringResource(StringsR.string.settings_lock_prompt_title)
    val lockSubtitle = stringResource(StringsR.string.settings_lock_prompt_subtitle)
    val actions = SettingsActions(
        onTheme = viewModel::setTheme,
        onLock = { enable ->
            if (!enable || activity == null) {
                viewModel.setLockEnabled(enable)
            } else {
                DeviceAuth.prompt(activity, lockTitle, lockSubtitle) { ok -> if (ok) viewModel.setLockEnabled(true) }
            }
        },
        onLockTimeout = viewModel::setLockTimeout,
        onHideRecents = viewModel::setHideInRecents,
        onLanguage = { tag ->
            viewModel.setLanguage(tag)
            activity?.recreate()
        },
        onSystemLanguage = {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                context.startActivity(
                    Intent(Settings.ACTION_APP_LOCALE_SETTINGS, Uri.fromParts("package", context.packageName, null))
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                )
            }
        },
        onOcr = viewModel::setOcr,
        onAskSignOut = viewModel::askSignOut,
        onSignOut = { viewModel.signOut(navigation.onSignedOut) },
        onExportDiagnostics = { diagnostics.launch("bento-diagnostico-${LocalDate.now()}.txt") },
        onClearDiagnostic = viewModel::clearDiagnostic,
        onEditRelay = viewModel::editRelay,
        onRelay = viewModel::setRelayUrl,
        onAskReset = viewModel::askReset,
        onReset = viewModel::reset,
        onOpenUrl = { url -> context.startActivity(Intent(Intent.ACTION_VIEW, url.toUri()).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
    )
    SettingsContent(state, actions, navigation, modifier, initialSection, siteUrl)
}

/** Pages Ajustes shows itself (sections plus the licenses list). */
enum class SettingsPageKey { General, Backup, Storage, Account, Search, Telegram, Advanced, About, Licenses }

@Composable
fun SettingsContent(
    state: SettingsUiState,
    actions: SettingsActions,
    navigation: SettingsNavigation,
    modifier: Modifier = Modifier,
    initialSection: SettingsSection? = null,
    siteUrl: String = "",
    backupPage: @Composable (onBack: (() -> Unit)?) -> Unit = { BackupSettingsScreen(it) },
    storagePage: @Composable (onBack: (() -> Unit)?) -> Unit = { StorageScreen(it) }
) {
    var page by rememberSaveable { mutableStateOf(initialSection?.let(::pageOf)) }
    val open: (SettingsSection) -> Unit = { section ->
        if (section == SettingsSection.Devices) navigation.onDevices() else page = pageOf(section)
    }
    BoxWithConstraints(modifier.fillMaxSize().background(BentoTheme.colors.tray)) {
        val wide = maxWidth >= 840.dp
        val current = page
        if (wide) {
            Row(Modifier.fillMaxSize()) {
                Box(Modifier.width(360.dp).fillMaxHeight()) {
                    SettingsHome(state, navigation.onBack, open, selected = current ?: SettingsPageKey.General)
                }
                Box(Modifier.weight(1f).fillMaxHeight()) {
                    SettingsPageContent(
                        current ?: SettingsPageKey.General,
                        state,
                        actions,
                        navigation,
                        siteUrl,
                        null,
                        backupPage,
                        storagePage
                    ) {
                        page = it
                    }
                }
            }
        } else if (current == null) {
            SettingsHome(state, navigation.onBack, open, selected = null)
        } else {
            val back = { page = if (current == SettingsPageKey.Licenses) SettingsPageKey.About else null }
            BackHandler(onBack = back)
            SettingsPageContent(current, state, actions, navigation, siteUrl, back, backupPage, storagePage) { page = it }
        }
    }
    SettingsDialogs(state, actions)
}

private fun pageOf(section: SettingsSection): SettingsPageKey = when (section) {
    SettingsSection.General -> SettingsPageKey.General
    SettingsSection.Backup -> SettingsPageKey.Backup
    SettingsSection.Storage -> SettingsPageKey.Storage
    SettingsSection.Account, SettingsSection.Devices -> SettingsPageKey.Account
    SettingsSection.Search -> SettingsPageKey.Search
    SettingsSection.Telegram -> SettingsPageKey.Telegram
    SettingsSection.Advanced -> SettingsPageKey.Advanced
    SettingsSection.About -> SettingsPageKey.About
}

@Composable
private fun SettingsPageContent(
    page: SettingsPageKey,
    state: SettingsUiState,
    actions: SettingsActions,
    navigation: SettingsNavigation,
    siteUrl: String,
    onBack: (() -> Unit)?,
    backupPage: @Composable (onBack: (() -> Unit)?) -> Unit,
    storagePage: @Composable (onBack: (() -> Unit)?) -> Unit,
    onOpen: (SettingsPageKey) -> Unit
) {
    when (page) {
        SettingsPageKey.General -> GeneralPage(state, actions, onBack)
        SettingsPageKey.Backup -> backupPage(onBack)
        SettingsPageKey.Storage -> storagePage(onBack)
        SettingsPageKey.Account -> AccountPage(state, actions, navigation, onBack)
        SettingsPageKey.Search -> SearchPage(state, actions, onBack)
        SettingsPageKey.Telegram -> TelegramPage(navigation, onBack)
        SettingsPageKey.Advanced -> AdvancedPage(state, actions, onBack)
        SettingsPageKey.About -> AboutPage(state, actions, siteUrl, onBack) { onOpen(SettingsPageKey.Licenses) }
        SettingsPageKey.Licenses -> LicensesPage(onBack)
    }
}

// Home ---------------------------------------------------------------------------------------------------------

@Composable
fun SettingsHome(state: SettingsUiState, onBack: () -> Unit, onOpen: (SettingsSection) -> Unit, selected: SettingsPageKey?) {
    SettingsPage(stringResource(StringsR.string.settings_title), onBack) {
        AccountCard(state)
        SettingsGroup {
            SectionRow(SettingsSection.General, onOpen, selected)
            SectionRow(SettingsSection.Backup, onOpen, selected)
            SectionRow(SettingsSection.Storage, onOpen, selected)
        }
        SettingsGroup {
            SectionRow(SettingsSection.Account, onOpen, selected)
            SectionRow(SettingsSection.Devices, onOpen, selected, devices = state.vault?.devicesCount?.toInt())
            SectionRow(SettingsSection.Search, onOpen, selected)
            SectionRow(SettingsSection.Telegram, onOpen, selected)
        }
        SettingsGroup {
            SectionRow(SettingsSection.Advanced, onOpen, selected)
            SectionRow(SettingsSection.About, onOpen, selected)
        }
    }
}

@Composable
private fun SectionRow(section: SettingsSection, onOpen: (SettingsSection) -> Unit, selected: SettingsPageKey?, devices: Int? = null) {
    val (title, summary, icon) = when (section) {
        SettingsSection.General -> Triple(
            StringsR.string.settings_section_general,
            StringsR.string.settings_section_general_summary,
            BentoIcons.SunMoon
        )

        SettingsSection.Backup -> Triple(
            StringsR.string.settings_section_backup,
            StringsR.string.settings_section_backup_summary,
            BentoIcons.CloudUpload
        )

        SettingsSection.Storage -> Triple(
            StringsR.string.settings_section_storage,
            StringsR.string.settings_section_storage_summary,
            BentoIcons.HardDrive
        )

        SettingsSection.Account -> Triple(
            StringsR.string.settings_section_account,
            StringsR.string.settings_section_account_summary,
            BentoIcons.Cloud
        )

        SettingsSection.Devices -> Triple(
            StringsR.string.settings_section_devices,
            StringsR.string.settings_section_devices_summary,
            BentoIcons.MonitorSmartphone
        )

        SettingsSection.Search -> Triple(
            StringsR.string.settings_section_search,
            StringsR.string.settings_section_search_summary,
            BentoIcons.Search
        )

        SettingsSection.Telegram -> Triple(
            StringsR.string.settings_section_telegram,
            StringsR.string.settings_section_telegram_summary,
            BentoIcons.Send
        )

        SettingsSection.Advanced -> Triple(
            StringsR.string.settings_section_advanced,
            StringsR.string.settings_section_advanced_summary,
            BentoIcons.Wrench
        )

        SettingsSection.About -> Triple(
            StringsR.string.settings_section_about,
            StringsR.string.settings_section_about_summary,
            BentoIcons.Info
        )
    }
    val isSelected = selected != null && section != SettingsSection.Devices && pageOf(section) == selected
    Box(
        Modifier.clip(
            BentoShapes.md
        ).background(if (isSelected) BentoTheme.colors.accentSoft else androidx.compose.ui.graphics.Color.Transparent)
    ) {
        SettingsRow(
            stringResource(title),
            onClick = { onOpen(section) },
            summary = stringResource(summary),
            icon = icon,
            value = devices?.takeIf { it > 0 }?.let { pluralStringResource(StringsR.plurals.common_count_devices, it, it) }
        )
    }
}

/** Avatar initials, name and "1,2 TB en tu nube · 3 dispositivos". */
@Composable
private fun AccountCard(state: SettingsUiState) {
    val context = LocalContext.current
    val c = BentoTheme.colors
    val name = state.account?.displayName ?: stringResource(StringsR.string.settings_account_this_phone)
    val usage = state.vault?.let { vault ->
        val bytes = Formatter.formatShortFileSize(context, vault.usage.bytes)
        val devices = vault.devicesCount.toInt()
        stringResource(
            StringsR.string.settings_account_usage,
            bytes,
            pluralStringResource(StringsR.plurals.common_count_devices, devices, devices)
        )
    } ?: stringResource(if (state.signedIn) StringsR.string.common_state_loading else StringsR.string.settings_account_local)
    Row(
        Modifier.padding(horizontal = 16.dp).fillMaxWidth().clip(BentoShapes.lg).background(c.raised).padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        Box(Modifier.size(48.dp).clip(BentoShapes.full).background(c.accentSoft), contentAlignment = Alignment.Center) {
            Text(initialsOf(name), color = c.accentInk, style = BentoTheme.typography.bodyStrong)
        }
        Column(Modifier.weight(1f)) {
            Text(name, color = c.ink, style = BentoTheme.typography.sectionTitle)
            Text(usage, color = c.inkMuted, style = BentoTheme.typography.metadata)
        }
    }
}

internal fun initialsOf(name: String): String =
    name.split(' ').filter { it.isNotBlank() }.take(2).joinToString("") { it.first().uppercase() }.ifEmpty { "B" }

// General ------------------------------------------------------------------------------------------------------

@Composable
fun GeneralPage(state: SettingsUiState, actions: SettingsActions, onBack: (() -> Unit)?) {
    val prefs = state.prefs
    SettingsPage(stringResource(StringsR.string.settings_section_general), onBack) {
        SettingsGroup(title = stringResource(StringsR.string.settings_theme)) {
            SegmentedButtons(
                options = listOf(
                    SegmentOption(ThemeChoice.System, stringResource(StringsR.string.settings_theme_system)),
                    SegmentOption(ThemeChoice.Light, stringResource(StringsR.string.settings_theme_light)),
                    SegmentOption(ThemeChoice.Dark, stringResource(StringsR.string.settings_theme_dark))
                ),
                selected = prefs.theme,
                onSelect = actions.onTheme,
                modifier = Modifier.fillMaxWidth().padding(12.dp)
            )
        }
        SettingsGroup(title = stringResource(StringsR.string.settings_language)) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                SettingsRow(
                    stringResource(StringsR.string.settings_language),
                    onClick = actions.onSystemLanguage,
                    summary = stringResource(StringsR.string.settings_language_system_summary),
                    icon = BentoIcons.Languages
                )
            } else {
                SegmentedButtons(
                    options = listOf(
                        SegmentOption("", stringResource(StringsR.string.settings_language_system)),
                        SegmentOption("es", "Español"),
                        SegmentOption("en", "English")
                    ),
                    selected = prefs.language,
                    onSelect = actions.onLanguage,
                    modifier = Modifier.fillMaxWidth().padding(12.dp)
                )
            }
        }
        SettingsGroup(title = stringResource(StringsR.string.settings_lock)) {
            SwitchRow(
                stringResource(StringsR.string.settings_lock),
                checked = prefs.lockEnabled,
                onCheckedChange = actions.onLock,
                summary = stringResource(
                    if (state.lockAvailable) StringsR.string.settings_lock_summary else StringsR.string.settings_lock_unavailable
                ),
                icon = BentoIcons.Fingerprint,
                enabled = state.lockAvailable || prefs.lockEnabled
            )
            if (prefs.lockEnabled) {
                Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        stringResource(StringsR.string.settings_lock_after),
                        color = BentoTheme.colors.inkMuted,
                        style = BentoTheme.typography.label
                    )
                    SegmentedButtons(
                        options = listOf(
                            SegmentOption(LockTimeout.Immediately, stringResource(StringsR.string.settings_lock_immediately)),
                            SegmentOption(LockTimeout.OneMinute, stringResource(StringsR.string.settings_lock_1min)),
                            SegmentOption(LockTimeout.FiveMinutes, stringResource(StringsR.string.settings_lock_5min)),
                            SegmentOption(LockTimeout.FifteenMinutes, stringResource(StringsR.string.settings_lock_15min))
                        ),
                        selected = prefs.lockTimeout,
                        onSelect = actions.onLockTimeout,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            }
            SwitchRow(
                stringResource(StringsR.string.settings_hide_recents),
                checked = prefs.lockEnabled && prefs.hideInRecents,
                onCheckedChange = actions.onHideRecents,
                summary = stringResource(StringsR.string.settings_hide_recents_summary),
                icon = BentoIcons.EyeOff,
                enabled = prefs.lockEnabled
            )
        }
        SettingsNote(stringResource(StringsR.string.settings_lock_background_note))
    }
}

// Cuenta y nube ------------------------------------------------------------------------------------------------

@Composable
fun AccountPage(state: SettingsUiState, actions: SettingsActions, navigation: SettingsNavigation, onBack: (() -> Unit)?) {
    SettingsPage(stringResource(StringsR.string.settings_section_account), onBack) {
        SettingsGroup(title = stringResource(StringsR.string.settings_telegram_account)) {
            val account = state.account
            if (state.signedIn && account != null) {
                ListRow(
                    headline = account.displayName,
                    supporting = listOfNotNull(account.username?.let { "@$it" }, account.phoneMasked).joinToString(" · ").ifEmpty { null },
                    leading = {
                        dev.bento.designsystem.component.BentoIcon(
                            BentoIcons.User,
                            contentDescription = null,
                            tint = BentoTheme.colors.inkMuted
                        )
                    }
                )
                SettingsRow(
                    stringResource(StringsR.string.settings_sign_out),
                    onClick = { actions.onAskSignOut(true) },
                    summary = stringResource(StringsR.string.settings_sign_out_summary),
                    icon = BentoIcons.LogOut,
                    showChevron = false
                )
            } else {
                SettingsRow(
                    stringResource(StringsR.string.common_telegram_connect),
                    onClick = navigation.onReconnect,
                    icon = BentoIcons.Send
                )
            }
        }
        SettingsGroup(title = stringResource(StringsR.string.settings_recovery)) {
            val summary = when {
                state.vault == null -> null
                state.vault.recoveryKitStale -> stringResource(StringsR.string.settings_recovery_stale)
                state.vault.recoveryKitSaved -> stringResource(StringsR.string.settings_recovery_saved)
                else -> stringResource(StringsR.string.settings_recovery_pending)
            }
            SettingsRow(
                stringResource(StringsR.string.settings_recovery_open),
                onClick = navigation.onRecovery,
                summary = summary,
                icon = BentoIcons.LifeBuoy
            )
        }
    }
}

// Búsqueda -----------------------------------------------------------------------------------------------------

@Composable
fun SearchPage(state: SettingsUiState, actions: SettingsActions, onBack: (() -> Unit)?) {
    SettingsPage(stringResource(StringsR.string.settings_section_search), onBack) {
        SettingsGroup {
            SwitchRow(
                stringResource(StringsR.string.settings_ocr),
                checked = state.phone?.ocrEnabled ?: true,
                onCheckedChange = actions.onOcr,
                summary = stringResource(StringsR.string.settings_ocr_summary),
                icon = BentoIcons.TextSearch,
                enabled = state.phone != null
            )
        }
        SettingsNote(stringResource(StringsR.string.settings_ocr_explain))
        if (state.failed) {
            Callout(
                Modifier.padding(horizontal = 16.dp),
                tone = CalloutTone.Danger,
                body = stringResource(StringsR.string.common_error_generic)
            )
        }
    }
}

// Telegram -----------------------------------------------------------------------------------------------------

@Composable
fun TelegramPage(navigation: SettingsNavigation, onBack: (() -> Unit)?) {
    SettingsPage(stringResource(StringsR.string.settings_section_telegram), onBack) {
        SettingsGroup(title = stringResource(StringsR.string.settings_inbox)) {
            ListRow(
                headline = stringResource(StringsR.string.settings_inbox_title),
                supporting = stringResource(StringsR.string.settings_inbox_body),
                leading = {
                    dev.bento.designsystem.component.BentoIcon(
                        BentoIcons.Inbox,
                        contentDescription = null,
                        tint = BentoTheme.colors.inkMuted
                    )
                }
            )
        }
        SettingsGroup {
            SettingsRow(
                stringResource(StringsR.string.settings_import_telegram),
                onClick = navigation.onImportTelegram,
                summary = stringResource(StringsR.string.settings_import_telegram_summary),
                icon = BentoIcons.Download
            )
        }
        SettingsGroup(title = stringResource(StringsR.string.settings_send_telegram)) {
            ListRow(
                headline = stringResource(StringsR.string.common_action_send_telegram),
                supporting = stringResource(StringsR.string.settings_send_telegram_body),
                leading = {
                    dev.bento.designsystem.component.BentoIcon(
                        BentoIcons.Send,
                        contentDescription = null,
                        tint = BentoTheme.colors.inkMuted
                    )
                }
            )
        }
        SettingsNote(stringResource(StringsR.string.common_telegram_api_notice))
    }
}

// Avanzado -----------------------------------------------------------------------------------------------------

@Composable
fun AdvancedPage(state: SettingsUiState, actions: SettingsActions, onBack: (() -> Unit)?) {
    SettingsPage(stringResource(StringsR.string.settings_section_advanced), onBack) {
        state.diagnostic?.let { result ->
            Callout(
                Modifier.padding(horizontal = 16.dp),
                tone = if (result == DiagnosticResult.Saved) CalloutTone.Success else CalloutTone.Danger,
                body = stringResource(
                    if (result ==
                        DiagnosticResult.Saved
                    ) {
                        StringsR.string.settings_diagnostic_saved
                    } else {
                        StringsR.string.common_error_generic
                    }
                )
            )
        }
        SettingsGroup {
            SettingsRow(
                stringResource(StringsR.string.settings_diagnostic),
                onClick = actions.onExportDiagnostics,
                summary = stringResource(StringsR.string.settings_diagnostic_summary),
                icon = BentoIcons.FileDown,
                showChevron = false
            )
            SettingsRow(
                stringResource(StringsR.string.settings_relay),
                onClick = { actions.onEditRelay(true) },
                summary = state.phone?.relayUrl?.ifBlank { null } ?: stringResource(StringsR.string.settings_relay_default),
                icon = BentoIcons.Server
            )
            ListRow(
                headline = stringResource(StringsR.string.settings_storage_mode),
                supporting = storageModeLabel(state.storageBackend),
                leading = {
                    dev.bento.designsystem.component.BentoIcon(
                        BentoIcons.HardDrive,
                        contentDescription = null,
                        tint = BentoTheme.colors.inkMuted
                    )
                }
            )
        }
        SettingsGroup {
            SettingsRow(
                stringResource(StringsR.string.settings_reset),
                onClick = { actions.onAskReset(true) },
                summary = stringResource(StringsR.string.settings_reset_summary),
                icon = BentoIcons.TriangleAlert,
                showChevron = false
            )
        }
    }
}

@Composable
private fun storageModeLabel(backend: String?): String = stringResource(
    when (backend) {
        "local" -> StringsR.string.settings_storage_mode_local
        "fake" -> StringsR.string.settings_storage_mode_fake
        null -> StringsR.string.common_state_loading
        else -> StringsR.string.settings_storage_mode_telegram
    }
)

// Acerca de ----------------------------------------------------------------------------------------------------

@Composable
fun AboutPage(state: SettingsUiState, actions: SettingsActions, siteUrl: String, onBack: (() -> Unit)?, onLicenses: () -> Unit) {
    SettingsPage(stringResource(StringsR.string.settings_section_about), onBack) {
        SettingsGroup {
            ListRow(
                headline = stringResource(StringsR.string.settings_version),
                supporting = state.appVersion,
                leading = { dev.bento.designsystem.component.BrandMark(size = 28.dp) }
            )
        }
        SettingsGroup(title = stringResource(StringsR.string.settings_privacy)) {
            PrivacyLine(BentoIcons.Lock, StringsR.string.settings_privacy_encrypted)
            PrivacyLine(BentoIcons.Send, StringsR.string.settings_privacy_telegram)
            PrivacyLine(BentoIcons.Link, StringsR.string.settings_privacy_relay)
            PrivacyLine(BentoIcons.ShieldCheck, StringsR.string.settings_privacy_nothing_else)
        }
        SettingsNote(stringResource(StringsR.string.common_telegram_api_notice))
        SettingsGroup {
            SettingsRow(stringResource(StringsR.string.settings_licenses), onClick = onLicenses, icon = BentoIcons.Scale)
            if (siteUrl.isNotBlank()) {
                SettingsRow(
                    stringResource(StringsR.string.settings_terms),
                    onClick = { actions.onOpenUrl("${siteUrl.trimEnd('/')}/terms") },
                    icon = BentoIcons.ExternalLink,
                    showChevron = false
                )
            }
        }
    }
}

@Composable
private fun PrivacyLine(icon: androidx.compose.ui.graphics.vector.ImageVector, text: Int) {
    ListRow(
        headline = stringResource(text),
        leading = { dev.bento.designsystem.component.BentoIcon(icon, contentDescription = null, tint = BentoTheme.colors.inkMuted) }
    )
}

// Dialogs and sheets --------------------------------------------------------------------------------------------

@Composable
private fun SettingsDialogs(state: SettingsUiState, actions: SettingsActions) {
    if (state.confirmSignOut) {
        BentoDialog(
            title = stringResource(StringsR.string.settings_sign_out_title),
            consequence = stringResource(StringsR.string.settings_sign_out_consequence),
            confirmLabel = stringResource(StringsR.string.settings_sign_out),
            onConfirm = actions.onSignOut,
            onDismissRequest = { actions.onAskSignOut(false) },
            icon = BentoIcons.LogOut
        )
    }
    if (state.editingRelay) RelaySheet(state, actions)
    if (state.confirmReset) ResetSheet(actions)
}

@Composable
private fun RelaySheet(state: SettingsUiState, actions: SettingsActions) {
    val field = rememberTextFieldState(state.phone?.relayUrl.orEmpty())
    BentoSheet(onDismissRequest = { actions.onEditRelay(false) }, title = stringResource(StringsR.string.settings_relay)) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Text(
                stringResource(StringsR.string.settings_relay_help),
                color = BentoTheme.colors.inkMuted,
                style = BentoTheme.typography.body
            )
            val text = field.text.toString().trim()
            val invalid = text.isNotEmpty() && !RelayUrls.valid(text)
            BentoTextField(
                field,
                label = stringResource(StringsR.string.settings_relay_field),
                placeholder = state.defaultRelayUrl.ifBlank { "wss://" },
                error = if (invalid) stringResource(StringsR.string.settings_relay_invalid) else null
            )
            BentoButton(
                stringResource(StringsR.string.common_action_save),
                { actions.onRelay(text) },
                Modifier.fillMaxWidth(),
                variant = BentoButtonVariant.Primary,
                enabled = !invalid
            )
            if (state.phone?.relayUrl?.isNotBlank() == true) {
                BentoButton(stringResource(StringsR.string.settings_relay_restore), {
                    actions.onRelay("")
                }, Modifier.fillMaxWidth(), variant = BentoButtonVariant.Ghost)
            }
        }
    }
}

/** Typed confirmation ("RESTABLECER" / "RESET"): what stays (the vault, other devices) and what goes (this phone). */
@Composable
fun ResetSheet(actions: SettingsActions) {
    val word = stringResource(StringsR.string.settings_reset_word)
    val field = rememberTextFieldState()
    BentoSheet(onDismissRequest = { actions.onAskReset(false) }, title = stringResource(StringsR.string.settings_reset)) {
        ResetSheetBody(word, field, actions)
    }
}

@Composable
fun ResetSheetBody(word: String, field: androidx.compose.foundation.text.input.TextFieldState, actions: SettingsActions) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text(stringResource(StringsR.string.settings_reset_consequence), color = BentoTheme.colors.ink, style = BentoTheme.typography.body)
        Text(stringResource(StringsR.string.settings_reset_stays), color = BentoTheme.colors.inkMuted, style = BentoTheme.typography.body)
        BentoTextField(field, label = stringResource(StringsR.string.settings_reset_type, word))
        BentoButton(
            stringResource(StringsR.string.settings_reset_confirm),
            actions.onReset,
            Modifier.fillMaxWidth(),
            variant = BentoButtonVariant.Danger,
            enabled = PhoneReset.confirmed(field.text.toString(), word)
        )
    }
}

/** Relay URLs must be `wss://` (or `ws://` to loopback in development); android-runtime.md §10 "relay over wss". */
object RelayUrls {
    fun valid(url: String): Boolean {
        val uri = runCatching { java.net.URI(url) }.getOrNull() ?: return false
        val host = uri.host ?: return false
        return when (uri.scheme) {
            "wss" -> true
            "ws" -> host == "127.0.0.1" || host == "localhost" || host == "10.0.2.2"
            else -> false
        }
    }
}
