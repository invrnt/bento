package dev.bento.feature.recovery

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Confirmation of a freshly shown kit by typing its last group (`POST /vault/recovery-code/confirm`). */
data class KitConfirmState(val confirming: Boolean = false, val error: KitConfirmError? = null, val confirmed: Boolean = false)

enum class KitConfirmError { Mismatch, Failed }

@HiltViewModel
class RecoveryKitViewModel @Inject constructor(private val vault: VaultRepository) : ViewModel() {
    private val _state = MutableStateFlow(KitConfirmState())
    val state: StateFlow<KitConfirmState> = _state.asStateFlow()

    fun clearError() = _state.update { it.copy(error = null) }

    fun confirm(code: String, typed: String) {
        if (_state.value.confirming) return
        if (!RecoveryCodes.matchesLastGroup(code, typed)) {
            _state.update { it.copy(error = KitConfirmError.Mismatch) }
            return
        }
        _state.update { it.copy(confirming = true, error = null) }
        viewModelScope.launch {
            when (val result = attempt { vault.confirmKit(RecoveryCodes.lastGroup(code)) }) {
                is Outcome.Ok -> _state.update { KitConfirmState(confirmed = true) }

                is Outcome.Err -> _state.update {
                    val mismatch = result.problem.code in setOf("recovery_code_invalid", "recovery_group_mismatch", "validation_failed")
                    it.copy(confirming = false, error = if (mismatch) KitConfirmError.Mismatch else KitConfirmError.Failed)
                }
            }
        }
    }
}
