package dev.bento.feature.pairing

import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dev.bento.api.generated.PairingRequestItem
import dev.bento.api.generated.PairingResponse
import dev.bento.designsystem.component.BentoAnnounce
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonSize
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.recovery.Hero
import dev.bento.feature.recovery.HeroTone
import dev.bento.feature.recovery.Outcome
import dev.bento.feature.recovery.SetupScaffold
import dev.bento.feature.recovery.attempt
import dev.bento.strings.R as StringsR
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Review of a Sync-channel join request on this phone ("Un dispositivo nuevo quiere unirse"). */
data class RequestReviewState(
    val loading: Boolean = true,
    val pairing: PairingResponse? = null,
    val problem: PairingProblem? = null,
    val acting: Boolean = false,
    val rejected: Boolean = false
)

@HiltViewModel
class PairingRequestViewModel @Inject constructor(private val repo: PairingRepository) : ViewModel() {
    private val _state = MutableStateFlow(RequestReviewState())
    val state: StateFlow<RequestReviewState> = _state.asStateFlow()
    private var requestId: String? = null

    /** Reviewing posts an offer to the other device: once per request. */
    fun review(id: String) {
        if (requestId == id) return
        requestId = id
        viewModelScope.launch {
            when (val result = attempt { repo.review(id) }) {
                is Outcome.Ok -> {
                    _state.update { it.copy(loading = false, pairing = result.value) }
                    follow(result.value.id)
                }

                is Outcome.Err -> _state.update { it.copy(loading = false, problem = pairingProblem(result.problem.code)) }
            }
        }
    }

    fun decide(approve: Boolean) {
        val id = requestId ?: return
        if (_state.value.acting) return
        _state.update { it.copy(acting = true, problem = null) }
        viewModelScope.launch {
            when (val result = attempt { if (approve) repo.approveRequest(id) else repo.rejectRequest(id) }) {
                is Outcome.Ok -> _state.update { it.copy(acting = false, pairing = result.value, rejected = !approve) }
                is Outcome.Err -> _state.update { it.copy(acting = false, problem = pairingProblem(result.problem.code)) }
            }
        }
    }

    private fun follow(pairingId: String) {
        viewModelScope.launch {
            repo.follow(pairingId, current = { _state.value.pairing }, onUpdate = { next -> _state.update { it.copy(pairing = next) } })
        }
    }
}

/** Opened from the Devices list or the `Dispositivos` notification. */
@Composable
fun PairingRequestScreen(
    requestId: String,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: PairingRequestViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    androidx.compose.runtime.LaunchedEffect(requestId) { viewModel.review(requestId) }
    PairingRequestContent(state, onApprove = {
        viewModel.decide(true)
    }, onReject = { viewModel.decide(false) }, onClose = onClose, modifier = modifier)
}

@Suppress("CyclomaticComplexMethod", "LongMethod")
@Composable
fun PairingRequestContent(
    state: RequestReviewState,
    onApprove: () -> Unit,
    onReject: () -> Unit,
    onClose: () -> Unit,
    modifier: Modifier = Modifier
) {
    val pairing = state.pairing
    val name = pairing?.peer?.let { deviceDisplayName(it.deviceName, it.platform) }.orEmpty()
    val close: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit = {
        BentoButton(
            stringResource(StringsR.string.pairing_host_done),
            onClose,
            Modifier.fillMaxWidth(),
            variant = BentoButtonVariant.Primary,
            size = BentoButtonSize.Large
        )
    }
    val blocking = setOf(PairingProblem.RequestTaken, PairingProblem.DeviceRemoved)
    when {
        state.loading -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_request_review_title),
            hero = Hero.Loader,
            onBack = onClose,
            modifier = modifier
        )

        state.problem != null &&
            (pairing == null || state.problem in blocking) -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_request_failed_title),
            body = stringResource(pairingProblemText(state.problem)),
            hero = Hero.Icon(BentoIcons.TriangleAlert, HeroTone.Warning),
            onBack = onClose,
            modifier = modifier,
            actions = close
        )

        pairing?.state == "completed" -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_host_completed_title),
            body = stringResource(StringsR.string.pairing_host_completed_body, name),
            hero = Hero.Icon(BentoIcons.CircleCheck, HeroTone.Success),
            modifier = modifier,
            actions = close
        )

        state.rejected || pairing?.state == "rejected" || pairing?.state == "cancelled" -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_host_rejected_title),
            body = stringResource(StringsR.string.pairing_host_rejected_body),
            hero = Hero.Icon(BentoIcons.ShieldCheck),
            modifier = modifier,
            actions = close
        )

        pairing?.state == "failed" || pairing?.state == "expired" -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_request_failed_title),
            body = stringResource(
                pairingProblemText(pairingProblem(pairing.error?.code ?: if (pairing.state == "expired") "expired" else null))
            ),
            hero = Hero.Icon(BentoIcons.TriangleAlert, HeroTone.Warning),
            modifier = modifier,
            actions = close
        )

        pairing?.state == "approving" || pairing?.state == "bootstrapping" -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_request_review_title),
            hero = Hero.Loader,
            onBack = onClose,
            modifier = modifier
        ) { StatusLine(stringResource(StringsR.string.pairing_host_approving, name)) }

        else -> SetupScaffold(
            title = stringResource(StringsR.string.pairing_host_approve_title, name),
            body = stringResource(StringsR.string.pairing_request_review_body),
            onBack = onClose,
            modifier = modifier,
            actions = {
                BentoButton(
                    stringResource(StringsR.string.pairing_host_approve),
                    onApprove,
                    Modifier.fillMaxWidth(),
                    variant = BentoButtonVariant.Primary,
                    size = BentoButtonSize.Large,
                    loading = state.acting,
                    enabled = pairing?.sas != null
                )
                BentoButton(
                    stringResource(StringsR.string.pairing_host_reject),
                    onReject,
                    Modifier.fillMaxWidth(),
                    size = BentoButtonSize.Large,
                    enabled = !state.acting
                )
            }
        ) {
            val sas = pairing?.sas
            if (sas != null) PairingSas(sas) else StatusLine(stringResource(StringsR.string.pairing_request_waiting_emojis))
            Spacer(Modifier.height(8.dp))
            Text(
                stringResource(StringsR.string.pairing_host_sas_hint),
                color = BentoTheme.colors.inkMuted,
                style = BentoTheme.typography.metadata,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth()
            )
            if (state.problem != null) {
                Spacer(Modifier.height(12.dp))
                Callout(
                    tone = CalloutTone.Danger,
                    body = stringResource(pairingProblemText(state.problem)),
                    announce = BentoAnnounce.Assertive
                )
            }
        }
    }
}
