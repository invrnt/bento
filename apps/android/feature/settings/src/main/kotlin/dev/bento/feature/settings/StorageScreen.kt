package dev.bento.feature.settings

import android.text.format.Formatter
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dev.bento.api.generated.BentoEndpoints
import dev.bento.api.generated.LocalStorageResponse
import dev.bento.designsystem.component.BentoDialog
import dev.bento.designsystem.component.BentoIconButton
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.ErrorState
import dev.bento.designsystem.component.ListRow
import dev.bento.designsystem.component.LoadingState
import dev.bento.designsystem.component.SegmentOption
import dev.bento.designsystem.component.SegmentedButtons
import dev.bento.designsystem.component.SettingsRow
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.files.FilesPreferences
import dev.bento.feature.files.FilesRepository
import dev.bento.feature.recovery.Outcome
import dev.bento.feature.recovery.attempt
import dev.bento.strings.R as StringsR
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** One item made available offline on this phone (Archivos pins; names come from the backend). */
data class OfflineItem(val assetId: String, val name: String)

data class StorageUiState(
    val loading: Boolean = true,
    val loadFailed: Boolean = false,
    val usage: LocalStorageResponse? = null,
    val cacheGb: Int = PhoneSettings.DEFAULT_CACHE_GB,
    val offline: List<OfflineItem> = emptyList(),
    val confirmClear: Boolean = false,
    val clearing: Boolean = false,
    val clearedBytes: Long? = null,
    val failed: Boolean = false
)

/** Ajustes › Espacio en este teléfono (product/android.md §9, api/android-endpoints.md §6). */
@HiltViewModel
class StorageViewModel @Inject constructor(
    private val api: BentoEndpoints,
    private val phoneSettings: PhoneSettingsRepository,
    private val files: FilesRepository,
    private val filesPreferences: FilesPreferences
) : ViewModel() {
    private val _state = MutableStateFlow(StorageUiState())
    val state: StateFlow<StorageUiState> = _state.asStateFlow()

    fun load() {
        viewModelScope.launch {
            val usage = attempt { api.localStorage() }
            val settings = (attempt { phoneSettings.load() } as? Outcome.Ok)?.value
            val offline = filesPreferences.pinned.value.map { id ->
                OfflineItem(id, (attempt { files.asset(id) } as? Outcome.Ok)?.value?.filename ?: id)
            }.sortedBy { it.name.lowercase() }
            _state.update {
                it.copy(
                    loading = false,
                    loadFailed = usage is Outcome.Err && it.usage == null,
                    usage = (usage as? Outcome.Ok)?.value ?: it.usage,
                    cacheGb = settings?.cacheMaxGb ?: it.cacheGb,
                    offline = offline
                )
            }
        }
    }

    /** 1 / 2 / 5 / 10 GB (default 2 GB); the backend also shrinks it when the phone has under 10 % free. */
    fun setCacheLimit(gb: Int) {
        val before = _state.value.cacheGb
        _state.update { it.copy(cacheGb = gb, failed = false) }
        viewModelScope.launch {
            if (attempt {
                    phoneSettings.set(PhoneSettings.CACHE_MAX_GB, gb)
                } is Outcome.Err
            ) {
                _state.update { it.copy(cacheGb = before, failed = true) }
            }
        }
    }

    fun askClear(open: Boolean) = _state.update { it.copy(confirmClear = open) }

    /** `Vaciar caché`: drops cached originals and temporary copies; never pinned or not-yet-uploaded ones. */
    fun clearCache() {
        _state.update { it.copy(confirmClear = false, clearing = true, failed = false) }
        viewModelScope.launch {
            val result = attempt { api.reclaimStorage() }
            _state.update {
                it.copy(clearing = false, clearedBytes = (result as? Outcome.Ok)?.value?.freedBytes, failed = result is Outcome.Err)
            }
            load()
        }
    }

    fun unpin(item: OfflineItem) {
        _state.update { s -> s.copy(offline = s.offline - item) }
        viewModelScope.launch {
            if (attempt { files.setPinned(item.assetId, false) } is Outcome.Ok) {
                filesPreferences.setPinned(item.assetId, false)
                load()
            } else {
                _state.update { s -> s.copy(offline = (s.offline + item).sortedBy { it.name.lowercase() }, failed = true) }
            }
        }
    }
}

data class StorageActions(
    val onCacheLimit: (Int) -> Unit = {},
    val onAskClear: (Boolean) -> Unit = {},
    val onClear: () -> Unit = {},
    val onUnpin: (OfflineItem) -> Unit = {},
    val onRetry: () -> Unit = {}
)

@Composable
fun StorageScreen(onBack: (() -> Unit)?, modifier: Modifier = Modifier, viewModel: StorageViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    LaunchedEffect(viewModel) { viewModel.load() }
    StorageContent(
        state,
        StorageActions(viewModel::setCacheLimit, viewModel::askClear, viewModel::clearCache, viewModel::unpin, viewModel::load),
        onBack,
        modifier
    )
}

@Composable
fun StorageContent(state: StorageUiState, actions: StorageActions, onBack: (() -> Unit)?, modifier: Modifier = Modifier) {
    SettingsPage(stringResource(StringsR.string.settings_section_storage), onBack, modifier) {
        when {
            state.loading -> LoadingState(Modifier.padding(32.dp))

            state.loadFailed -> ErrorState(
                stringResource(StringsR.string.common_error_generic),
                Modifier.padding(16.dp),
                onRetry = actions.onRetry
            )

            else -> StorageBody(state, actions)
        }
    }
    if (state.confirmClear) {
        BentoDialog(
            title = stringResource(StringsR.string.storage_clear_title),
            consequence = stringResource(StringsR.string.storage_clear_consequence),
            confirmLabel = stringResource(StringsR.string.storage_clear),
            onConfirm = actions.onClear,
            onDismissRequest = { actions.onAskClear(false) },
            icon = BentoIcons.Eraser
        )
    }
}

@Composable
private fun StorageBody(state: StorageUiState, actions: StorageActions) {
    val context = LocalContext.current
    val usage = state.usage
    if (usage != null) UsageBar(usage)
    if (state.failed) {
        Callout(
            Modifier.padding(horizontal = 16.dp),
            tone = CalloutTone.Danger,
            body = stringResource(StringsR.string.common_error_generic)
        )
    }
    state.clearedBytes?.let {
        Callout(
            Modifier.padding(horizontal = 16.dp),
            tone = CalloutTone.Success,
            body = stringResource(StringsR.string.storage_cleared, Formatter.formatShortFileSize(context, it))
        )
    }
    SettingsGroup(stringResource(StringsR.string.storage_cache_limit)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            SegmentedButtons(
                options = PhoneSettings.CACHE_CHOICES_GB.map {
                    SegmentOption(it, stringResource(StringsR.string.common_unit_gigabytes, it.toString()))
                },
                selected = state.cacheGb,
                onSelect = actions.onCacheLimit,
                modifier = Modifier.fillMaxWidth()
            )
            Text(
                stringResource(StringsR.string.storage_cache_limit_help),
                color = BentoTheme.colors.inkMuted,
                style = BentoTheme.typography.metadata
            )
        }
        SettingsRow(
            stringResource(StringsR.string.storage_clear),
            onClick = { actions.onAskClear(true) },
            summary = stringResource(StringsR.string.storage_clear_summary),
            icon = BentoIcons.Eraser,
            showChevron = false,
            enabled = !state.clearing
        )
    }
    SettingsGroup(stringResource(StringsR.string.storage_offline_title)) {
        if (state.offline.isEmpty()) {
            Text(
                stringResource(StringsR.string.storage_offline_empty),
                color = BentoTheme.colors.inkMuted,
                style = BentoTheme.typography.body,
                modifier = Modifier.padding(16.dp)
            )
        }
        state.offline.forEach { item ->
            ListRow(
                headline = item.name,
                leading = {
                    dev.bento.designsystem.component.BentoIcon(BentoIcons.Pin, contentDescription = null, tint = BentoTheme.colors.inkMuted)
                },
                trailing = {
                    BentoIconButton(BentoIcons.PinOff, stringResource(StringsR.string.storage_offline_remove, item.name), {
                        actions.onUnpin(item)
                    })
                }
            )
        }
    }
}

/** Thumbnails · cached originals · offline items, against the cache limit (color is never the only signal: a legend). */
@Composable
private fun UsageBar(usage: LocalStorageResponse) {
    val context = LocalContext.current
    val c = BentoTheme.colors
    val cached = (usage.cacheBytes - usage.pinnedBytes).coerceAtLeast(0)
    val parts = listOf(
        Triple(StringsR.string.storage_part_thumbs, usage.thumbsBytes, c.inkSubtle),
        Triple(StringsR.string.storage_part_cache, cached, c.accent),
        Triple(StringsR.string.storage_part_offline, usage.pinnedBytes, c.success)
    )
    val total = (usage.thumbsBytes + usage.cacheBytes).coerceAtLeast(1)
    val scale = maxOf(total, usage.cacheLimitBytes + usage.thumbsBytes).toFloat()
    val used = Formatter.formatShortFileSize(context, usage.thumbsBytes + usage.cacheBytes)
    val limit = Formatter.formatShortFileSize(context, usage.cacheLimitBytes)
    val summary = stringResource(StringsR.string.storage_usage_summary, used, limit)
    Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(
            summary,
            color = c.ink,
            style = BentoTheme.typography.sectionTitle,
            modifier = Modifier.semantics {
                contentDescription =
                    summary
            }
        )
        Canvas(Modifier.fillMaxWidth().height(12.dp).clearAndSetSemantics {}) {
            drawRoundRect(c.sunken, cornerRadius = CornerRadius(size.height / 2))
            var x = 0f
            parts.forEach { (_, bytes, color) ->
                val w = size.width * (bytes / scale)
                if (w > 0f) drawRect(color, Offset(x, 0f), Size(w, size.height))
                x += w
            }
        }
        parts.forEach { (label, bytes, color) -> LegendRow(stringResource(label), Formatter.formatShortFileSize(context, bytes), color) }
        Text(
            pluralStringResource(StringsR.plurals.storage_offline_count, usage.pinnedCount.toInt(), usage.pinnedCount.toInt()),
            color = c.inkMuted,
            style = BentoTheme.typography.metadata
        )
    }
}

@Composable
private fun LegendRow(label: String, value: String, color: Color) {
    Row(Modifier.fillMaxWidth().semantics(mergeDescendants = true) {}, verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(10.dp).background(color, BentoShapes.full))
        Text(
            label,
            color = BentoTheme.colors.ink,
            style = BentoTheme.typography.label,
            modifier = Modifier.padding(start = 10.dp).weight(1f)
        )
        Text(value, color = BentoTheme.colors.inkMuted, style = BentoTheme.typography.numeric)
    }
}
