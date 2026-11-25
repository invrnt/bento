package dev.bento.feature.settings

import android.content.Context
import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import dev.bento.api.generated.TelegramAccountResponse
import dev.bento.api.generated.VaultStatusResponse
import dev.bento.data.ActivityRepository
import dev.bento.data.SessionRepository
import dev.bento.data.SettingsRepository
import dev.bento.engine.BentoEngine
import dev.bento.engine.EngineBuildInfo
import dev.bento.feature.recovery.Outcome
import dev.bento.feature.recovery.attempt
import javax.inject.Inject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.filterIsInstance
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Sections of Ajustes (product/android.md §9), in order. Devices and the recovery kit are agent 38's screens. */
enum class SettingsSection { General, Backup, Storage, Account, Devices, Search, Telegram, Advanced, About }

enum class DiagnosticResult { Saved, Failed }

data class SettingsUiState(
    val loading: Boolean = true,
    val account: TelegramAccountResponse? = null,
    val signedIn: Boolean = false,
    val vault: VaultStatusResponse? = null,
    val prefs: LocalPrefs = LocalPrefs(),
    val phone: PhoneSettings? = null,
    val storageBackend: String? = null,
    val lockAvailable: Boolean = false,
    val appVersion: String = "",
    val defaultRelayUrl: String = "",
    val confirmSignOut: Boolean = false,
    val signingOut: Boolean = false,
    val confirmReset: Boolean = false,
    val editingRelay: Boolean = false,
    val diagnostic: DiagnosticResult? = null,
    val failed: Boolean = false
)

/** Ajustes home and the small sections (General, Cuenta y nube, Búsqueda, Telegram, Avanzado, Acerca de). */
@HiltViewModel
class SettingsViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val session: SessionRepository,
    private val settings: SettingsRepository,
    private val phoneSettings: PhoneSettingsRepository,
    private val activity: ActivityRepository,
    private val backup: BackupRepository,
    private val local: LocalSettings,
    private val lock: AppLockState,
    private val engine: BentoEngine,
    buildInfo: EngineBuildInfo
) : ViewModel() {
    private val _state =
        MutableStateFlow(SettingsUiState(appVersion = buildInfo.appVersion, defaultRelayUrl = buildInfo.relayUrl.orEmpty()))
    val state: StateFlow<SettingsUiState> = _state.asStateFlow()

    init {
        local.prefs.onEach { prefs -> _state.update { it.copy(prefs = prefs) } }.launchIn(viewModelScope)
        // Every time the engine (re)starts: a load made while it was starting may have come back empty.
        engine.state.filterIsInstance<dev.bento.engine.EngineState.Ready>().onEach { refresh() }.launchIn(viewModelScope)
        refresh()
    }

    fun refresh() {
        _state.update { it.copy(lockAvailable = DeviceAuth.available(context)) }
        viewModelScope.launch {
            val account = (attempt { session.account() } as? Outcome.Ok)?.value
            val vault = (attempt { session.vault() } as? Outcome.Ok)?.value
            val phone = (attempt { phoneSettings.load() } as? Outcome.Ok)?.value
            val public = (attempt { settings.public() } as? Outcome.Ok)?.value
            _state.update {
                it.copy(
                    loading = false,
                    account = account?.account ?: it.account,
                    signedIn = account?.step == "authorized",
                    vault = vault ?: it.vault,
                    phone = phone ?: it.phone,
                    storageBackend = public?.storageBackend ?: phone?.storageBackend ?: it.storageBackend
                )
            }
        }
    }

    // General ---------------------------------------------------------------------------------------------------

    fun setTheme(theme: ThemeChoice) = updatePrefs { it.copy(theme = theme) }

    /** Turning the lock on is confirmed with the device credential first, so nobody locks themselves out. */
    fun setLockEnabled(enabled: Boolean) {
        if (enabled) lock.enabledNow()
        updatePrefs { it.copy(lockEnabled = enabled) }
    }

    fun setLockTimeout(timeout: LockTimeout) = updatePrefs { it.copy(lockTimeout = timeout) }

    fun setHideInRecents(hide: Boolean) = updatePrefs { it.copy(hideInRecents = hide) }

    /** Android 12 and older only (13+ opens the system per-app language screen); empty = follow the system. */
    fun setLanguage(tag: String) = updatePrefs { it.copy(language = tag) }

    private fun updatePrefs(transform: (LocalPrefs) -> LocalPrefs) {
        _state.update { it.copy(prefs = transform(it.prefs)) }
        viewModelScope.launch { local.update(transform) }
    }

    // Backend settings ------------------------------------------------------------------------------------------

    /** Búsqueda › Texto en fotos y documentos (on-device OCR; runs only while charging and idle). */
    fun setOcr(enabled: Boolean) = patch(PhoneSettings.OCR_PROVIDER, if (enabled) PhoneSettings.OCR_ON else PhoneSettings.OCR_OFF) {
        it.copy(ocrEnabled = enabled)
    }

    fun editRelay(open: Boolean) = _state.update { it.copy(editingRelay = open) }

    /** Avanzado › Servidor de emparejamiento; blank restores the default. Applies on the next engine start. */
    fun setRelayUrl(url: String) {
        _state.update { it.copy(editingRelay = false) }
        patch(PhoneSettings.RELAY_URL, url.trim()) { it.copy(relayUrl = url.trim()) }
    }

    private fun patch(key: String, value: String, optimistic: (PhoneSettings) -> PhoneSettings) {
        val before = _state.value.phone
        _state.update { s -> s.copy(phone = s.phone?.let(optimistic), failed = false) }
        viewModelScope.launch {
            when (val result = attempt { phoneSettings.set(key, value) }) {
                is Outcome.Ok -> _state.update { it.copy(phone = result.value) }
                is Outcome.Err -> _state.update { it.copy(phone = before, failed = true) }
            }
        }
    }

    // Cuenta y nube ---------------------------------------------------------------------------------------------

    fun askSignOut(open: Boolean) = _state.update { it.copy(confirmSignOut = open) }

    /** `Cerrar sesión en este teléfono`: this phone's Telegram session ends; the vault and other devices stay. */
    fun signOut(onDone: () -> Unit) {
        _state.update { it.copy(signingOut = true) }
        viewModelScope.launch {
            val result = attempt { session.logOut() }
            _state.update { it.copy(signingOut = false, confirmSignOut = result is Outcome.Err, failed = result is Outcome.Err) }
            if (result is Outcome.Ok) onDone()
        }
    }

    // Avanzado --------------------------------------------------------------------------------------------------

    fun exportDiagnostics(uri: Uri) {
        viewModelScope.launch {
            val facts = DiagnosticFacts(
                appVersion = _state.value.appVersion,
                engine = engineLabel(engine.state.value),
                storageBackend = _state.value.storageBackend,
                sync = (
                    attempt {
                        activity.syncStatus()
                    } as? Outcome.Ok
                    )?.value?.let { "${it.state} pending_ops=${it.pendingOps} error=${it.error?.code}" },
                backup = (attempt { backup.status() } as? Outcome.Ok)?.value?.let { "pending=${it.pending} waiting=${it.waiting}" },
                activity = (attempt { activity.activity() } as? Outcome.Ok)?.value?.let { ActivityDigest.describe(it) },
                settings = (attempt { settings.values() } as? Outcome.Ok)?.value
            )
            val ok = withContext(Dispatchers.IO) {
                Diagnostics.write(context, uri, Diagnostics.report(facts, Diagnostics.deviceLine(), Diagnostics.logTail(context)))
            }
            _state.update { it.copy(diagnostic = if (ok) DiagnosticResult.Saved else DiagnosticResult.Failed) }
        }
    }

    fun clearDiagnostic() = _state.update { it.copy(diagnostic = null) }

    fun askReset(open: Boolean) = _state.update { it.copy(confirmReset = open) }

    /** Wipes this phone's data and keys and ends the process (the vault is untouched). */
    fun reset() {
        PhoneReset.wipe(context)
    }
}

/** Engine state name only (never `toString()`: [EngineState.Ready] carries the API token). */
internal fun engineLabel(state: dev.bento.engine.EngineState): String = when (state) {
    is dev.bento.engine.EngineState.Ready -> "ready (${state.mode.name.lowercase()})"
    is dev.bento.engine.EngineState.Degraded -> "degraded (${state.reason.name.lowercase()})"
    dev.bento.engine.EngineState.Starting -> "starting"
    dev.bento.engine.EngineState.Stopped -> "stopped"
}

/** Summary of `/api/activity` for the diagnostic report: summary and attention kinds, no parameters (names, ids). */
object ActivityDigest {
    fun describe(activity: kotlinx.serialization.json.JsonObject): String {
        val summary = (activity["summary"] as? kotlinx.serialization.json.JsonPrimitive)?.content
        val kinds = (activity["attention"] as? kotlinx.serialization.json.JsonArray).orEmpty()
            .mapNotNull {
                ((it as? kotlinx.serialization.json.JsonObject)?.get("kind") as? kotlinx.serialization.json.JsonPrimitive)?.content
            }
        return "summary=$summary attention=${kinds.joinToString(",")}"
    }
}
