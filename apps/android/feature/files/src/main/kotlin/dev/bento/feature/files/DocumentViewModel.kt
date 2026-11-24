package dev.bento.feature.files

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import dev.bento.api.ApiException
import dev.bento.api.generated.AssetResponse
import java.io.File
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** In-app openers: the PDF reader and the text viewer (product/android.md §4.5). */
sealed interface DocumentBody {
    data object Loading : DocumentBody

    data class Downloading(val done: Long, val total: Long) : DocumentBody

    data class Pdf(val source: PdfSource) : DocumentBody

    data class Text(val text: String) : DocumentBody

    /** Text larger than 2 MiB, or a type the viewer does not handle: `Abrir con…` from Archivos. */
    data object TooLarge : DocumentBody

    data object Offline : DocumentBody

    data object Failed : DocumentBody
}

data class PdfSearch(
    val open: Boolean = false,
    val query: String = "",
    val searching: Boolean = false,
    val matches: List<PdfMatch> = emptyList(),
    val current: Int = 0
) {
    val currentMatch: PdfMatch? get() = matches.getOrNull(current)
}

data class DocumentState(
    val asset: AssetResponse? = null,
    val body: DocumentBody = DocumentBody.Loading,
    val page: Int = 0,
    val monospace: Boolean = false,
    val search: PdfSearch = PdfSearch()
)

/** Opens a temporary file as a [PdfSource] (Android's renderer on the device). */
fun interface PdfOpener {
    fun open(file: File, onClose: (File) -> Unit): PdfSource
}

@HiltViewModel
class DocumentViewModel @Inject constructor(
    private val repository: FilesRepository,
    private val content: ContentFiles,
    private val preferences: FilesPreferences,
    private val connectivity: Connectivity,
    private val pdfOpener: PdfOpener
) : ViewModel() {
    private val _state = MutableStateFlow(DocumentState())
    val state: StateFlow<DocumentState> = _state.asStateFlow()
    private var searchJob: Job? = null
    private var assetId: String? = null

    fun open(assetId: String) {
        if (this.assetId == assetId) return
        this.assetId = assetId
        viewModelScope.launch {
            try {
                val asset = repository.asset(assetId)
                _state.update { it.copy(asset = asset) }
                if (!connectivity.online() && assetId !in preferences.pinned.value) {
                    _state.update { it.copy(body = DocumentBody.Offline) }
                    return@launch
                }
                when (FileKinds.openKind(asset)) {
                    OpenKind.Pdf -> openPdf(asset)
                    OpenKind.Text -> openText(asset)
                    else -> _state.update { it.copy(body = DocumentBody.TooLarge) }
                }
            } catch (error: ApiException) {
                _state.update { it.copy(body = if (connectivity.online()) DocumentBody.Failed else DocumentBody.Offline) }
            } catch (error: java.io.IOException) {
                _state.update { it.copy(body = DocumentBody.Failed) }
            }
        }
    }

    private suspend fun openPdf(asset: AssetResponse) {
        val file = content.readerCopy(asset.id) { done, total -> _state.update { it.copy(body = DocumentBody.Downloading(done, total)) } }
        val source = try {
            pdfOpener.open(file) { content.discard(it) }
        } catch (error: java.io.IOException) {
            content.discard(file)
            _state.update { it.copy(body = DocumentBody.Failed) }
            return
        } catch (error: SecurityException) {
            content.discard(file)
            _state.update { it.copy(body = DocumentBody.Failed) }
            return
        }
        _state.update { it.copy(body = DocumentBody.Pdf(source)) }
    }

    private suspend fun openText(asset: AssetResponse) {
        if (asset.sizeBytes > ContentFiles.TEXT_LIMIT) {
            _state.update { it.copy(body = DocumentBody.TooLarge) }
            return
        }
        val text = content.text(asset.id)
        _state.update { it.copy(body = if (text == null) DocumentBody.TooLarge else DocumentBody.Text(text)) }
    }

    fun setPage(page: Int) = _state.update { it.copy(page = page) }

    fun toggleMonospace() = _state.update { it.copy(monospace = !it.monospace) }

    fun openSearch(open: Boolean) {
        searchJob?.cancel()
        _state.update { it.copy(search = if (open) it.search.copy(open = true) else PdfSearch()) }
    }

    fun search(query: String) {
        val source = (_state.value.body as? DocumentBody.Pdf)?.source ?: return
        _state.update { it.copy(search = it.search.copy(query = query, searching = query.isNotBlank())) }
        searchJob?.cancel()
        if (query.isBlank()) {
            _state.update { it.copy(search = it.search.copy(matches = emptyList(), current = 0, searching = false)) }
            return
        }
        searchJob = viewModelScope.launch {
            delay(SEARCH_DEBOUNCE_MS)
            val matches = runCatching { source.search(query) }.getOrDefault(emptyList())
            _state.update { state ->
                state.copy(
                    search = state.search.copy(matches = matches, current = 0, searching = false),
                    page = matches.firstOrNull()?.page ?: state.page
                )
            }
        }
    }

    fun step(delta: Int) = _state.update { state ->
        val matches = state.search.matches
        if (matches.isEmpty()) return@update state
        val next = (state.search.current + delta).mod(matches.size)
        state.copy(search = state.search.copy(current = next), page = matches[next].page)
    }

    override fun onCleared() {
        (_state.value.body as? DocumentBody.Pdf)?.source?.close()
    }

    private companion object {
        const val SEARCH_DEBOUNCE_MS = 250L
    }
}
