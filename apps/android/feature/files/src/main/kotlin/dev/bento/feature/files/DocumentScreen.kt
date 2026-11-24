package dev.bento.feature.files

import android.graphics.Bitmap
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.rememberTransformableState
import androidx.compose.foundation.gestures.transformable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.bento.designsystem.component.BentoFilterChip
import dev.bento.designsystem.component.BentoIconButton
import dev.bento.designsystem.component.BentoTextField
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.ErrorState
import dev.bento.designsystem.component.LoadingState
import dev.bento.designsystem.component.ProgressBar
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.strings.R as StringsR
import kotlinx.coroutines.flow.distinctUntilChanged

/** Full-screen in-app opener for PDFs and text (product/android.md §4.5). */
@Composable
fun DocumentScreen(assetId: String, onBack: () -> Unit, modifier: Modifier = Modifier, viewModel: DocumentViewModel = hiltViewModel()) {
    LaunchedEffect(assetId) { viewModel.open(assetId) }
    val state by viewModel.state.collectAsStateWithLifecycle()
    DocumentContent(
        state = state,
        onBack = onBack,
        onPage = viewModel::setPage,
        onMonospace = viewModel::toggleMonospace,
        onSearchOpen = viewModel::openSearch,
        onQuery = viewModel::search,
        onStep = viewModel::step,
        modifier = modifier
    )
}

@Composable
fun DocumentContent(
    state: DocumentState,
    onBack: () -> Unit,
    onPage: (Int) -> Unit = {},
    onMonospace: () -> Unit = {},
    onSearchOpen: (Boolean) -> Unit = {},
    onQuery: (String) -> Unit = {},
    onStep: (Int) -> Unit = {},
    modifier: Modifier = Modifier
) {
    val c = BentoTheme.colors
    val title = state.asset?.filename.orEmpty()
    Column(modifier.fillMaxSize().background(c.tray)) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            BentoIconButton(BentoIcons.ArrowLeft, stringResource(StringsR.string.common_action_back), onBack)
            Text(
                title,
                Modifier.weight(1f).semantics { heading() },
                color = c.ink,
                style = BentoTheme.typography.sectionTitle,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            when (val body = state.body) {
                is DocumentBody.Pdf -> if (body.source.searchable) {
                    BentoIconButton(BentoIcons.TextSearch, stringResource(StringsR.string.files_pdf_search), {
                        onSearchOpen(!state.search.open)
                    }, selected = state.search.open)
                }

                is DocumentBody.Text -> BentoFilterChip(
                    stringResource(StringsR.string.files_text_monospace),
                    selected = state.monospace,
                    onSelectedChange = { onMonospace() },
                    leadingIcon = BentoIcons.Code,
                    modifier = Modifier.padding(end = 8.dp)
                )

                else -> Unit
            }
        }
        when (val body = state.body) {
            DocumentBody.Loading -> LoadingState(Modifier.fillMaxSize(), label = stringResource(StringsR.string.files_text_loading))

            is DocumentBody.Downloading -> Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.Center) {
                Text(stringResource(StringsR.string.files_preparing, title), color = c.ink, style = BentoTheme.typography.body)
                ProgressBar(if (body.total > 0) body.done.toFloat() / body.total else null, Modifier.fillMaxWidth().padding(top = 12.dp))
            }

            is DocumentBody.Pdf -> PdfReader(body.source, state, onPage, onSearchOpen, onQuery, onStep)

            is DocumentBody.Text -> TextBody(body.text, state.monospace)

            DocumentBody.TooLarge -> Callout(
                Modifier.padding(16.dp),
                tone = CalloutTone.Neutral,
                body = stringResource(StringsR.string.files_text_too_large),
                icon = BentoIcons.ExternalLink
            )

            DocumentBody.Offline -> Callout(
                Modifier.padding(16.dp),
                tone = CalloutTone.Neutral,
                title = stringResource(StringsR.string.files_offline_title),
                body = stringResource(StringsR.string.files_offline_body, title),
                icon = BentoIcons.CloudOff
            )

            DocumentBody.Failed -> ErrorState(stringResource(StringsR.string.files_pdf_failed), Modifier.padding(16.dp))
        }
    }
}

@Composable
private fun TextBody(text: String, monospace: Boolean) {
    val style = if (monospace) BentoTheme.typography.mono else BentoTheme.typography.body
    SelectionContainer(Modifier.fillMaxSize()) {
        Text(
            text,
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).horizontalScroll(rememberScrollState(), enabled = monospace)
                .padding(16.dp),
            color = BentoTheme.colors.ink,
            style = style,
            softWrap = !monospace
        )
    }
}

@Composable
private fun PdfReader(
    source: PdfSource,
    state: DocumentState,
    onPage: (Int) -> Unit,
    onSearchOpen: (Boolean) -> Unit,
    onQuery: (String) -> Unit,
    onStep: (Int) -> Unit
) {
    val c = BentoTheme.colors
    val list = rememberLazyListState()
    var scale by remember { mutableFloatStateOf(1f) }
    var offset by remember { mutableStateOf(Offset.Zero) }
    val transform = rememberTransformableState { zoom, pan, _ ->
        scale = (scale * zoom).coerceIn(1f, MAX_ZOOM)
        offset = if (scale == 1f) Offset.Zero else offset + pan
    }
    LaunchedEffect(list) { snapshotFlow { list.firstVisibleItemIndex }.distinctUntilChanged().collect { onPage(it) } }
    LaunchedEffect(state.search.current, state.search.matches) {
        state.search.currentMatch?.let { list.animateScrollToItem(it.page) }
    }
    Column(Modifier.fillMaxSize()) {
        if (state.search.open) PdfSearchBar(state.search, onQuery, onStep, onClose = { onSearchOpen(false) })
        BoxWithConstraints(Modifier.weight(1f).fillMaxWidth().clip(BentoShapes.xs)) {
            val widthPx = with(LocalDensity.current) { maxWidth.roundToPx() }
            LazyColumn(
                state = list,
                modifier = Modifier.fillMaxSize().transformable(transform).graphicsLayer {
                    scaleX = scale
                    scaleY = scale
                    translationX = offset.x
                    translationY = offset.y
                },
                contentPadding = PaddingValues(12.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                items(source.pageCount) { page ->
                    PdfPage(
                        source,
                        page,
                        widthPx,
                        highlights = state.search.matches.filter {
                            it.page == page
                        },
                        current = state.search.currentMatch
                    )
                }
            }
            Text(
                stringResource(StringsR.string.files_pdf_page_counter, state.page + 1, source.pageCount),
                color = c.inkInverse,
                style = BentoTheme.typography.badge,
                modifier = Modifier.align(Alignment.TopEnd).padding(12.dp).background(c.tooltip, BentoShapes.full)
                    .padding(horizontal = 10.dp, vertical = 4.dp).semantics { liveRegion = LiveRegionMode.Polite }
            )
        }
        PageRail(source, state.page, onPage)
        LaunchedEffect(state.page) {
            if (list.firstVisibleItemIndex != state.page &&
                !list.isScrollInProgress
            ) {
                list.scrollToItem(state.page)
            }
        }
    }
}

@Composable
private fun PdfSearchBar(search: PdfSearch, onQuery: (String) -> Unit, onStep: (Int) -> Unit, onClose: () -> Unit) {
    val field = rememberTextFieldState(search.query)
    LaunchedEffect(field) { snapshotFlow { field.text.toString() }.collect { if (it != search.query) onQuery(it) } }
    Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        BentoTextField(
            field,
            stringResource(StringsR.string.files_pdf_search),
            Modifier.weight(1f),
            hideLabel = true,
            leadingIcon = BentoIcons.Search,
            placeholder = stringResource(StringsR.string.files_pdf_search)
        )
        val status = when {
            search.query.isBlank() || search.searching -> ""
            search.matches.isEmpty() -> stringResource(StringsR.string.files_pdf_no_matches)
            else -> stringResource(StringsR.string.files_pdf_match_position, search.current + 1, search.matches.size)
        }
        Text(
            status,
            color = BentoTheme.colors.inkMuted,
            style = BentoTheme.typography.metadata,
            modifier = Modifier.padding(horizontal = 8.dp).semantics { liveRegion = LiveRegionMode.Polite }
        )
        BentoIconButton(BentoIcons.ChevronLeft, stringResource(StringsR.string.files_pdf_previous), {
            onStep(-1)
        }, dense = true, enabled = search.matches.isNotEmpty())
        BentoIconButton(BentoIcons.ChevronRight, stringResource(StringsR.string.files_pdf_next), {
            onStep(1)
        }, dense = true, enabled = search.matches.isNotEmpty())
        BentoIconButton(BentoIcons.X, stringResource(StringsR.string.files_pdf_search_close), onClose, dense = true)
    }
}

@Composable
private fun PdfPage(source: PdfSource, page: Int, widthPx: Int, highlights: List<PdfMatch>, current: PdfMatch?) {
    val c = BentoTheme.colors
    val bitmap by produceState<Bitmap?>(null, source, page, widthPx) { value = runCatching { source.render(page, widthPx) }.getOrNull() }
    val label = stringResource(StringsR.string.files_pdf_page_counter, page + 1, source.pageCount)
    Box(
        Modifier.fillMaxWidth().aspectRatio(source.aspect(page)).background(c.white).border(1.dp, c.line)
            .semantics { contentDescription = label }
    ) {
        bitmap?.let { Image(it.asImageBitmap(), null, Modifier.fillMaxSize(), contentScale = ContentScale.FillBounds) }
        if (highlights.isNotEmpty()) {
            val accent = c.accent
            val strong = c.warning
            Canvas(Modifier.fillMaxSize()) {
                highlights.forEach { match ->
                    match.bounds.forEach { rect ->
                        drawRect(
                            color = (if (match == current) strong else accent).copy(alpha = HIGHLIGHT_ALPHA),
                            topLeft = Offset(rect.left * size.width, rect.top * size.height),
                            size = Size(rect.width() * size.width, rect.height() * size.height)
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun PageRail(source: PdfSource, current: Int, onPick: (Int) -> Unit) {
    val c = BentoTheme.colors
    val rail = rememberLazyListState()
    LaunchedEffect(current) { rail.animateScrollToItem((current - 2).coerceAtLeast(0)) }
    Column(Modifier.fillMaxWidth().background(c.surface)) {
        Text(
            stringResource(StringsR.string.files_pdf_pages),
            color = c.inkMuted,
            style = BentoTheme.typography.metadata,
            modifier = Modifier.padding(start = 16.dp, top = 8.dp).semantics { heading() }
        )
        LazyRow(state = rail, contentPadding = PaddingValues(12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(source.pageCount) { page ->
                val thumb by produceState<Bitmap?>(null, source, page) { value = runCatching { source.render(page, RAIL_PX) }.getOrNull() }
                val label = stringResource(StringsR.string.files_pdf_go_to_page, page + 1)
                Box(
                    Modifier.height(72.dp).aspectRatio(source.aspect(page)).background(c.white)
                        .border(if (page == current) 2.dp else 1.dp, if (page == current) c.accent else c.line)
                        .clickable(onClickLabel = label) { onPick(page) }
                        .semantics { contentDescription = label }
                ) {
                    thumb?.let { Image(it.asImageBitmap(), null, Modifier.fillMaxSize(), contentScale = ContentScale.FillBounds) }
                }
            }
        }
    }
}

private const val MAX_ZOOM = 5f
private const val RAIL_PX = 120
private const val HIGHLIGHT_ALPHA = 0.35f
