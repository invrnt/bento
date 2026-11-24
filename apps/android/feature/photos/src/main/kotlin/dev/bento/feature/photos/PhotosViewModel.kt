package dev.bento.feature.photos

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.paging.PagingData
import androidx.paging.cachedIn
import coil3.ImageLoader
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import dev.bento.api.ApiException
import dev.bento.api.BinaryEndpoints
import dev.bento.api.UploadSource
import dev.bento.api.generated.AssetResponse
import dev.bento.data.PhoneFoldersRepository
import dev.bento.data.SessionRepository
import dev.bento.data.TimelineLayout
import dev.bento.data.TimelineRepository
import dev.bento.data.Topic
import dev.bento.designsystem.component.AvatarStatus
import dev.bento.strings.R as StringsR
import javax.inject.Inject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** The single card shown at the top of Fotos (product/android.md §4.3), most important first. */
sealed interface PhotosCard {
    data object SignInNeeded : PhotosCard

    data object KitPending : PhotosCard

    data class PartialAccess(val visible: Int) : PhotosCard

    data object BackupOff : PhotosCard
}

/** Avatar + status line source for the top bar (the full Cuenta y actividad sheet is agent 41's). */
data class AccountSummary(val name: String?, val status: AvatarStatus)

/** Pure card priority: sign-in > kit > partial access > backup off (dismissed for 7 days with "Ahora no"). */
object PhotosCards {
    private const val BACKUP_SNOOZE_MS = 7L * 24 * 60 * 60 * 1000

    fun pick(
        signedIn: Boolean?,
        kitSaved: Boolean?,
        partialVisible: Int?,
        backupOn: Boolean?,
        backupDismissedAt: Long?,
        nowMs: Long
    ): PhotosCard? = when {
        signedIn == false -> PhotosCard.SignInNeeded
        kitSaved == false -> PhotosCard.KitPending
        partialVisible != null -> PhotosCard.PartialAccess(partialVisible)
        backupOn == false && (backupDismissedAt == null || nowMs - backupDismissedAt > BACKUP_SNOOZE_MS) -> PhotosCard.BackupOff
        else -> null
    }
}

@HiltViewModel
class PhotosViewModel @Inject constructor(
    private val timeline: TimelineRepository,
    private val session: SessionRepository,
    private val phoneFolders: PhoneFoldersRepository,
    private val prefs: MediaPreferences,
    private val binary: BinaryEndpoints,
    invalidations: dev.bento.data.Invalidations,
    @ApplicationContext private val context: Context,
    val actions: MediaActions,
    val imageLoader: ImageLoader,
    val sessions: ViewerSessions
) : ViewModel() {
    init {
        actions.bind(viewModelScope)
    }

    private val _cached = MutableStateFlow<List<AssetResponse>?>(null)

    /** The last first screen (UI cache), shown until live data arrives: the app never opens to a spinner. */
    val cached: StateFlow<List<AssetResponse>?> = _cached.asStateFlow()

    private val pages = timeline.sharedPositional
    val cells: Flow<PagingData<GridCell>> = pages.map { it.toGridCells(dayHeaders = true) }.cachedIn(viewModelScope)
    val monthCells: Flow<PagingData<GridCell>> = pages.map { it.toGridCells(dayHeaders = false) }.cachedIn(viewModelScope)
    val layout: StateFlow<TimelineLayout> = timeline.layout

    val density: StateFlow<GridDensity> = prefs.density.stateIn(viewModelScope, SharingStarted.Eagerly, GridDensity.Comfortable)

    private val signedIn = MutableStateFlow<Boolean?>(null)
    private val kitSaved = MutableStateFlow<Boolean?>(null)
    private val partial = MutableStateFlow<Int?>(null)
    private val backupOn = MutableStateFlow<Boolean?>(null)
    private val _account = MutableStateFlow(AccountSummary(null, AvatarStatus.Idle))
    val account: StateFlow<AccountSummary> = _account.asStateFlow()

    val card: StateFlow<PhotosCard?> = combine(signedIn, kitSaved, partial, backupOn, prefs.backupCardDismissedAt) { s, k, p, b, d ->
        PhotosCards.pick(s, k, p, b, d, System.currentTimeMillis())
    }.stateIn(viewModelScope, SharingStarted.Eagerly, null)

    init {
        viewModelScope.launch { _cached.value = withContext(Dispatchers.IO) { timeline.cachedFirstScreen() }.orEmpty() }
        refreshStatus()
        // Media access is reported by the platform bridge right after the engine starts: look once more.
        viewModelScope.launch {
            kotlinx.coroutines.delay(STATUS_SETTLE_MS)
            refreshStatus()
        }
        // Sign-in, kit and backup changes arrive as invalidations (server events): the card follows them.
        // Debounced: every server event invalidates all topics, and a busy backup sends many.
        @OptIn(kotlinx.coroutines.FlowPreview::class)
        invalidations.topics
            .filter { topics -> topics.any { it == Topic.ACCOUNT || it == Topic.SETTINGS || it == Topic.DEVICES } }
            .debounce(1_500)
            .onEach { refreshStatus() }
            .launchIn(viewModelScope)
    }

    private companion object {
        const val STATUS_SETTLE_MS = 4_000L
    }

    fun refreshStatus() {
        viewModelScope.launch {
            runCatching {
                val account = session.account()
                signedIn.value = account.step == "authorized"
                _account.value = AccountSummary(
                    name = account.account?.displayName,
                    status = if (account.step == "authorized") AvatarStatus.Idle else AvatarStatus.Attention
                )
            }
            runCatching { kitSaved.value = session.vault().let { it.state != "ready" || it.recoveryKitSaved } }
            runCatching {
                val folders = phoneFolders.folders().filter { it.kind == "media_store" }
                backupOn.value = folders.any { it.enabled }
                partial.value = phoneFolders.partialAccessVisible()
            }
        }
    }

    fun setDensity(density: GridDensity) {
        viewModelScope.launch { prefs.setDensity(density) }
    }

    fun dismissBackupCard() {
        viewModelScope.launch { prefs.dismissBackupCard() }
    }

    /** Fast scroller / fling landed in placeholders: reload from that photo (one request from the month cursor). */
    fun jumpTo(position: Int) = timeline.jumpTo(position)

    /** `Subir fotos` from the system photo picker (no media permission needed). */
    fun upload(uris: List<Uri>) {
        if (uris.isEmpty()) return
        viewModelScope.launch {
            val failed = uris.count { uri -> !runCatching { binary.uploadAsset(source(uri), mode = "photos") }.isSuccess }
            if (failed > 0) {
                actionsMessage(StringsR.string.photos_action_failed)
            } else {
                actionsMessage(StringsR.string.photos_upload_started)
            }
            timeline.jumpTo(0)
        }
    }

    private val _messages = MutableStateFlow<UiText?>(null)
    val messages: StateFlow<UiText?> = _messages.asStateFlow()

    fun messageShown() {
        _messages.value = null
    }

    private fun actionsMessage(res: Int) {
        _messages.value = UiText(res)
    }

    private fun source(uri: Uri): UploadSource {
        val resolver = context.contentResolver
        var name = "foto"
        var size = -1L
        resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                name = cursor.getString(0) ?: name
                size = if (cursor.isNull(1)) -1L else cursor.getLong(1)
            }
        }
        val mime = resolver.getType(uri) ?: "application/octet-stream"
        return UploadSource(MediaExporter.safeName(name), mime, size) {
            resolver.openInputStream(uri) ?: throw ApiException.EngineUnavailable()
        }
    }
}
