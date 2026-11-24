package dev.bento.feature.settings

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.runtime.Composable
import androidx.compose.ui.test.junit4.createComposeRule
import dev.bento.api.BentoJson
import dev.bento.api.generated.LocalStorageResponse
import dev.bento.api.generated.TelegramAccountResponse
import dev.bento.api.generated.VaultStatusResponse
import dev.bento.testing.BentoScreenshots
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** Roborazzi goldens of every settings/backup state (light, dark, 200 %, compact, expanded). */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = BentoScreenshots.QUALIFIERS)
class SettingsScreenshotTest {
    @get:Rule
    val compose = createComposeRule()

    private fun shot(name: String, content: @Composable () -> Unit) = BentoScreenshots.capture(compose, "screenshots", name, content)

    private val now = java.time.Instant.parse("2026-11-24T10:00:00Z").toEpochMilli()
    private val buckets = listOf(
        BucketRow("b_cam", "Cámara", 1240, suggested = true, sourceId = "s1", enabled = true, pending = 340),
        BucketRow("b_shots", "Capturas de pantalla", 96, suggested = true, sourceId = "s2", enabled = true),
        BucketRow("b_wa", "WhatsApp Images", 3012, suggested = false)
    )
    private val base = BackupUiState(
        loading = false,
        access = MediaAccess.Full,
        location = true,
        buckets = buckets,
        settings = PhoneSettings(revision = 1),
        status = BackupStatus(pending = 340, waiting = mapOf("wifi" to 340), lastBackupAt = "2026-11-24T09:57:00+00:00"),
        policy = BackupPolicy()
    )
    private val account = TelegramAccountResponse("Ana García", "+57 •••• 4567", premium = false, userId = 1, username = "ana")
    private val vault = BentoJson.decodeFromString(
        VaultStatusResponse.serializer(),
        """{"created_at":"2026-01-01T00:00:00+00:00","devices_count":3,"other_vaults":0,"recovery_kit_saved":true,"state":"ready",
        "usage":{"bytes":1320000000000,"files":18000},"vault_id":"v1"}"""
    )
    private val settings = SettingsUiState(
        loading = false,
        account = account,
        signedIn = true,
        vault = vault,
        phone = PhoneSettings(revision = 1),
        storageBackend = "telegram",
        lockAvailable = true,
        appVersion = "0.1.0"
    )

    @Test fun backupWaitingWifi() = shot("backup-waiting-wifi") { BackupSettingsContent(base, BackupActions(), now, onBack = {}) }

    @Test fun backupDone() = shot("backup-done") {
        BackupSettingsContent(base.copy(status = BackupStatus(lastBackupAt = "2026-11-24T09:57:00+00:00")), BackupActions(), now, onBack = {
        })
    }

    @Test fun backupPartial() = shot("backup-partial") {
        BackupSettingsContent(
            base.copy(
                access = MediaAccess.Partial,
                visibleCount = 12,
                showLocationNotice = true
            ),
            BackupActions(),
            now,
            onBack = {
            }
        )
    }

    @Test fun backupRevoked() = shot("backup-revoked") {
        BackupSettingsContent(base.copy(access = MediaAccess.Denied), BackupActions(), now, onBack = {})
    }

    @Test fun backupPausedLowBatteryStalled() = shot("backup-paused-stalled") {
        BackupSettingsContent(base.copy(policy = BackupPolicy(effectivePaused = true), stalled = true), BackupActions(), now, onBack = {})
    }

    @Test fun backupOffDenied() = shot("backup-off-denied") {
        BackupSettingsContent(
            base.copy(access = MediaAccess.Denied, deniedThisSession = true, buckets = buckets.map { it.copy(enabled = false) }),
            BackupActions(),
            now,
            onBack = {}
        )
    }

    @Test fun backupLoading() = shot("backup-loading") { BackupSettingsContent(BackupUiState(), BackupActions(), now, onBack = {}) }

    @Test fun backupError() = shot("backup-error") {
        BackupSettingsContent(BackupUiState(loading = false, loadFailed = true), BackupActions(), now, onBack = {})
    }

    @Test fun setupStep() = shot("setup") {
        BackupSetupContent(BackupUiState(loading = false, settings = PhoneSettings(revision = 1)), BackupActions())
    }

    @Test fun setupDenied() = shot("setup-denied") {
        BackupSetupContent(
            BackupUiState(loading = false, deniedThisSession = true, settings = PhoneSettings(revision = 1)),
            BackupActions()
        )
    }

    @Test fun freeUpPreview() = shot("free-up-preview") {
        FreeUpSheetBody(
            FreeUpState.Preview(
                FreeUpPreview(
                    List(860) {
                        FreeUpItem("a$it", "$it", 3_720_930)
                    },
                    3_200_000_000,
                    860
                )
            ),
            BackupActions()
        )
    }

    @Test fun freeUpDone() = shot("free-up-done") { FreeUpSheetBody(FreeUpState.Done(860, 3_200_000_000), BackupActions()) }

    @Test fun storage() = shot("storage") {
        StorageContent(
            StorageUiState(
                loading = false,
                usage = LocalStorageResponse(1_100_000_000, 420, 2_000_000_000, 300_000_000, 12, 250_000_000),
                offline = listOf(OfflineItem("a1", "Contrato 2026.pdf"), OfflineItem("a2", "Pasaporte.jpg"))
            ),
            StorageActions(),
            onBack = {}
        )
    }

    @Test fun home() = shot("home") {
        SettingsContent(settings, SettingsActions(), SettingsNavigation(), backupPage = {}, storagePage = {})
    }

    @Test fun general() = shot("general") {
        GeneralPage(
            settings.copy(
                prefs = LocalPrefs(lockEnabled = true, lockTimeout = LockTimeout.FiveMinutes)
            ),
            SettingsActions(),
            onBack = {
            }
        )
    }

    @Test fun account() = shot("account") { AccountPage(settings, SettingsActions(), SettingsNavigation(), onBack = {}) }

    @Test fun search() = shot("search") { SearchPage(settings, SettingsActions(), onBack = {}) }

    @Test fun telegram() = shot("telegram") { TelegramPage(SettingsNavigation(), onBack = {}) }

    @Test fun advanced() = shot("advanced") {
        AdvancedPage(settings.copy(diagnostic = DiagnosticResult.Saved), SettingsActions(), onBack = {})
    }

    @Test fun about() = shot("about") { AboutPage(settings, SettingsActions(), "https://bento.example", onBack = {}) {} }

    @Test fun licenses() = shot("licenses") { LicensesPage(onBack = {}) }

    @Test fun resetSheet() = shot("reset") { Column { ResetSheetBody("RESTABLECER", rememberTextFieldState(), SettingsActions()) } }

    @Test fun locked() = shot("locked") { LockScreen(onUnlock = {}) }
}
