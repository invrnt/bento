package dev.bento.feature.devices

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dev.bento.api.generated.DeviceRemovalResponse
import dev.bento.api.generated.DeviceResponse
import dev.bento.api.generated.PairingRequestItem
import dev.bento.data.DevicesRepository
import dev.bento.designsystem.component.QrMatrix
import dev.bento.feature.pairing.PairingRepository
import dev.bento.feature.recovery.Outcome
import dev.bento.feature.recovery.VaultRepository
import dev.bento.feature.recovery.attempt
import dev.bento.feature.recovery.toMatrix
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/** Removal in progress: preview of who keeps access, exclusions, then the mandatory new kit. */
data class RemovalState(
    val device: DeviceResponse,
    val loadingPreview: Boolean = true,
    val previewFailed: Boolean = false,
    val recipients: List<DeviceResponse> = emptyList(),
    val excluded: Set<String> = emptySet(),
    val removing: Boolean = false,
    val failed: RemovalFailure? = null
)

enum class RemovalFailure { Generic, ExclusionInvalid }

/** The new recovery kit after a removal (in memory only), and what to tell afterwards. */
data class RemovalResult(
    val code: String,
    val qr: QrMatrix,
    val removedName: String,
    val alsoRemoved: Int,
    val sessionOpen: Boolean,
    val excludedSessionsOpen: Boolean
)

/** A calm one-line outcome shown at the top of the list after a removal. */
data class RemovalNotice(val name: String, val alsoRemoved: Int, val sessionOpen: Boolean, val excludedSessionsOpen: Boolean)

data class DevicesState(
    val loading: Boolean = true,
    val loadFailed: Boolean = false,
    /** Signed out / local mode: show "Conecta tu Telegram" instead of a list. */
    val localOnly: Boolean = false,
    val devices: List<DeviceResponse> = emptyList(),
    val requests: List<PairingRequestItem> = emptyList(),
    val renaming: DeviceResponse? = null,
    val renameBusy: Boolean = false,
    val renameFailed: Boolean = false,
    val acknowledging: String? = null,
    val reviewFailed: String? = null,
    val removal: RemovalState? = null,
    val result: RemovalResult? = null,
    val notice: RemovalNotice? = null,
    val vaultCreatedAt: String? = null
) {
    /** Devices first seen through sync that the person has not reviewed (shown at the top). */
    val pendingReviews: List<DeviceResponse> get() = devices.filter { it.needsReview && it.removedAt == null && !it.current }
}

@HiltViewModel
class DevicesViewModel @Inject constructor(
    private val devicesRepo: DevicesRepository,
    private val pairing: PairingRepository,
    private val vault: VaultRepository
) : ViewModel() {
    private val _state = MutableStateFlow(DevicesState())
    val state: StateFlow<DevicesState> = _state.asStateFlow()
    private var requestsJob: Job? = null

    init {
        load()
    }

    fun load() {
        _state.update { it.copy(loading = it.devices.isEmpty(), loadFailed = false) }
        viewModelScope.launch {
            val status = (attempt { vault.status() } as? Outcome.Ok)?.value
            if (status != null && status.state in setOf("local_only", "signed_out", "no_vault")) {
                _state.update { it.copy(loading = false, localOnly = true) }
                return@launch
            }
            when (val result = attempt { devicesRepo.devices() }) {
                is Outcome.Ok -> _state.update {
                    it.copy(loading = false, localOnly = false, devices = sortDevices(result.value), vaultCreatedAt = status?.createdAt)
                }

                is Outcome.Err -> _state.update { it.copy(loading = false, loadFailed = it.devices.isEmpty()) }
            }
        }
    }

    /** Polls Sync-channel join requests while the screen is visible. */
    fun watchRequests(visible: Boolean) {
        requestsJob?.cancel()
        if (!visible) return
        requestsJob = viewModelScope.launch {
            while (isActive) {
                (attempt { pairing.requests() } as? Outcome.Ok)?.let { ok -> _state.update { it.copy(requests = ok.value) } }
                delay(REQUESTS_POLL_MS)
            }
        }
    }

    // Rename ------------------------------------------------------------------------------------------------

    fun startRename(device: DeviceResponse) = _state.update { it.copy(renaming = device, renameFailed = false) }

    fun cancelRename() = _state.update { it.copy(renaming = null, renameFailed = false) }

    fun rename(name: String) {
        val device = _state.value.renaming ?: return
        val trimmed = name.trim()
        if (trimmed.isEmpty() || trimmed == device.name) {
            cancelRename()
            return
        }
        _state.update { it.copy(renameBusy = true, renameFailed = false) }
        viewModelScope.launch {
            when (val result = attempt { devicesRepo.rename(device.id, trimmed) }) {
                is Outcome.Ok -> _state.update { s ->
                    s.copy(renameBusy = false, renaming = null, devices = s.devices.map { if (it.id == device.id) result.value else it })
                }

                is Outcome.Err -> _state.update { it.copy(renameBusy = false, renameFailed = true) }
            }
        }
    }

    // Review ------------------------------------------------------------------------------------------------

    fun acknowledge(device: DeviceResponse) {
        _state.update { it.copy(acknowledging = device.id, reviewFailed = null) }
        viewModelScope.launch {
            when (val result = attempt { devicesRepo.acknowledge(device.id) }) {
                is Outcome.Ok -> _state.update { s ->
                    s.copy(
                        acknowledging = null,
                        devices = s.devices.map {
                            if (it.id ==
                                device.id
                            ) {
                                result.value
                            } else {
                                it
                            }
                        }
                    )
                }

                is Outcome.Err -> _state.update { it.copy(acknowledging = null, reviewFailed = device.id) }
            }
        }
    }

    // Removal -----------------------------------------------------------------------------------------------

    /** Opens the removal sheet; unknown devices (`needs_review`) that would keep access are listed first. */
    fun startRemoval(device: DeviceResponse) {
        _state.update { it.copy(removal = RemovalState(device)) }
        viewModelScope.launch {
            when (val result = attempt { devicesRepo.removalPreview(device.id) }) {
                is Outcome.Ok -> _state.update { s ->
                    s.copy(
                        removal = s.removal?.copy(
                            loadingPreview = false,
                            recipients = result.value.recipients.sortedWith(
                                compareByDescending<DeviceResponse> {
                                    it.current
                                }.thenByDescending { it.needsReview }
                            )
                        )
                    )
                }

                is Outcome.Err -> _state.update { s -> s.copy(removal = s.removal?.copy(loadingPreview = false, previewFailed = true)) }
            }
        }
    }

    fun toggleKeep(deviceId: String, keep: Boolean) = _state.update { s ->
        val removal = s.removal ?: return@update s
        s.copy(removal = removal.copy(excluded = if (keep) removal.excluded - deviceId else removal.excluded + deviceId, failed = null))
    }

    fun cancelRemoval() = _state.update { if (it.removal?.removing == true) it else it.copy(removal = null) }

    fun confirmRemoval() {
        val removal = _state.value.removal ?: return
        if (removal.removing) return
        _state.update { it.copy(removal = removal.copy(removing = true, failed = null)) }
        viewModelScope.launch {
            when (val result = attempt { devicesRepo.remove(removal.device.id, removal.excluded.toList().takeIf { it.isNotEmpty() }) }) {
                is Outcome.Ok -> onRemoved(removal, result.value)

                is Outcome.Err -> {
                    val failure = if (result.problem.code ==
                        "device_exclusion_invalid"
                    ) {
                        RemovalFailure.ExclusionInvalid
                    } else {
                        RemovalFailure.Generic
                    }
                    _state.update { it.copy(removal = removal.copy(removing = false, failed = failure)) }
                    if (failure == RemovalFailure.ExclusionInvalid) startRemoval(removal.device)
                }
            }
        }
    }

    private fun onRemoved(removal: RemovalState, response: DeviceRemovalResponse) {
        val removedIds = response.removedDeviceIds.toSet() + removal.device.id
        _state.update { s ->
            s.copy(
                removal = null,
                devices = s.devices.filterNot { it.id in removedIds },
                result = RemovalResult(
                    code = response.recoveryCode,
                    qr = response.recoveryQr.toMatrix(),
                    removedName = removal.device.name,
                    alsoRemoved = (removedIds - removal.device.id).size,
                    sessionOpen = !response.telegramSessionClosed,
                    excludedSessionsOpen = removal.excluded.isNotEmpty()
                )
            )
        }
    }

    /** The mandatory kit was confirmed: forget the code, keep a one-line notice. */
    fun kitSaved() = _state.update { s ->
        val result = s.result ?: return@update s
        s.copy(
            result = null,
            notice = RemovalNotice(result.removedName, result.alsoRemoved, result.sessionOpen, result.excludedSessionsOpen)
        )
    }

    fun dismissNotice() = _state.update { it.copy(notice = null) }

    companion object {
        private const val REQUESTS_POLL_MS = 5_000L

        /** This phone first, then pending reviews, then most recently seen. */
        fun sortDevices(items: List<DeviceResponse>): List<DeviceResponse> = items.filter { it.removedAt == null }.sortedWith(
            compareByDescending<DeviceResponse> { it.current }.thenByDescending { it.needsReview }.thenByDescending {
                it.lastSeenAt
                    ?: it.addedAt
            }
        )
    }
}
