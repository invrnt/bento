package dev.bento.feature.search

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.foundation.text.input.setTextAndPlaceCursorAtEnd
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.SwipeToDismissBox
import androidx.compose.material3.Text
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil3.compose.rememberAsyncImagePainter
import dev.bento.api.BentoImage
import dev.bento.api.generated.SearchItemResponse
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoChip
import dev.bento.designsystem.component.BentoFilterChip
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.BentoIconButton
import dev.bento.designsystem.component.BentoIconSize
import dev.bento.designsystem.component.BentoSheet
import dev.bento.designsystem.component.BentoTextField
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.EmptyState
import dev.bento.designsystem.component.ErrorState
import dev.bento.designsystem.component.FileKind
import dev.bento.designsystem.component.KindIcon
import dev.bento.designsystem.component.ListRow
import dev.bento.designsystem.component.LoadingState
import dev.bento.designsystem.component.SectionHeader
import dev.bento.designsystem.component.Thumbnail
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.files.Destination
import dev.bento.feature.files.FileKinds
import dev.bento.feature.files.FolderPickerBody
import dev.bento.feature.files.LocalBentoImageLoader
import dev.bento.feature.files.di.FilesEntryPoint
import dev.bento.strings.R as StringsR
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import dev.bento.designsystem.trace.InteractionTrace

data class SearchActions(
    val onBack: () -> Unit = {},
    val onQuery: (String) -> Unit = {},
    val onSubmit: () -> Unit = {},
    val onRecent: (String) -> Unit = {},
    val onRemoveRecent: (String) -> Unit = {},
    val onClearRecents: () -> Unit = {},
    val onKind: (SearchKind?) -> Unit = {},
    val onThisMonth: () -> Unit = {},
    val onLastYear: () -> Unit = {},
    val onYear: (Int) -> Unit = {},
    val onDate: (DateFilter?) -> Unit = {},
    val onFolder: (Destination?) -> Unit = {},
    val onSheet: (FilterSheet?) -> Unit = {},
    val onOpen: (SearchItemResponse) -> Unit = {},
    val onOpenAlbum: (String) -> Unit = {},
    val onClearFilters: () -> Unit = {},
    val onEverywhere: () -> Unit = {},
    val onRetry: () -> Unit = {},
    val onLoadMore: () -> Unit = {}
)

/**
 * Buscar (product/android.md §4.7): full screen, field focused and keyboard open; recents and suggestions before
 * typing; grouped results with match reasons and highlights; filter chips with sheets (side pane at ≥ 840 dp);
 * scoped search and calm no-results states.
 */
@Composable
fun SearchScreen(
    query: String,
    scopeFolderId: String?,
    scopeFolderName: String?,
    onBack: () -> Unit,
    onOpenViewer: (String) -> Unit,
    onOpenDocument: (String) -> Unit,
    onOpenFolder: (String?) -> Unit,
    onOpenAlbum: (String) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: SearchViewModel = hiltViewModel()
) {
    val context = LocalContext.current
    val root = stringResource(StringsR.string.files_title)
    LaunchedEffect(Unit) {
        val scope = if (scopeFolderId != null) Destination(scopeFolderId, scopeFolderName ?: root) else null
        viewModel.start(query, scope)
    }
    LaunchedEffect(viewModel) {
        viewModel.effect.collect { effect ->
            when (effect) {
                is SearchEffect.OpenViewer -> onOpenViewer(effect.assetId)
                is SearchEffect.OpenDocument -> onOpenDocument(effect.assetId)
                is SearchEffect.OpenFolder -> onOpenFolder(effect.folderId)
                is SearchEffect.OpenAlbum -> onOpenAlbum(effect.albumId)
            }
        }
    }
    val state by viewModel.state.collectAsStateWithLifecycle()
    if (state.results.isNotEmpty()) SideEffect { InteractionTrace.end(InteractionTrace.SEARCH_RESULTS) }
    val loader = remember(context) { runCatching { FilesEntryPoint.get(context).imageLoader() }.getOrNull() }
    val actions = SearchActions(
        onBack = onBack,
        onQuery = viewModel::setQuery,
        onSubmit = viewModel::submit,
        onRecent = viewModel::pickRecent,
        onRemoveRecent = viewModel::removeRecent,
        onClearRecents = viewModel::clearRecents,
        onKind = viewModel::setKind,
        onThisMonth = viewModel::thisMonth,
        onLastYear = viewModel::lastYear,
        onYear = viewModel::year,
        onDate = viewModel::setDate,
        onFolder = viewModel::setFolder,
        onSheet = viewModel::showSheet,
        onOpen = viewModel::open,
        onOpenAlbum = onOpenAlbum,
        onClearFilters = viewModel::clearFilters,
        onEverywhere = viewModel::searchEverywhere,
        onRetry = viewModel::retry,
        onLoadMore = viewModel::loadMore
    )
    CompositionLocalProvider(LocalBentoImageLoader provides loader) {
        SearchContent(state, actions, modifier)
        state.sheet?.let { sheet ->
            BentoSheet(onDismissRequest = { viewModel.showSheet(null) }) {
                when (sheet) {
                    FilterSheet.Kind -> KindSheetBody(state.filters.kind, viewModel::setKind)

                    FilterSheet.Date -> DateSheetBody(state, actions)

                    FilterSheet.Folder -> {
                        val browser by viewModel.folderBrowser.state.collectAsStateWithLifecycle()
                        FolderPickerBody(
                            title = stringResource(StringsR.string.search_filter_folder),
                            confirmLabel = stringResource(StringsR.string.search_folder_pick),
                            state = browser,
                            onOpen = viewModel.folderBrowser::open,
                            onUp = viewModel.folderBrowser::up,
                            onSearch = viewModel.folderBrowser::search,
                            onCreate = viewModel.folderBrowser::create,
                            onConfirm = { viewModel.setFolder(it) }
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun SearchContent(state: SearchState, actions: SearchActions, modifier: Modifier = Modifier, autoFocus: Boolean = true) {
    BoxWithConstraints(modifier.fillMaxSize().background(BentoTheme.colors.tray)) {
        val expanded = maxWidth >= 840.dp
        Column(Modifier.fillMaxSize()) {
            SearchField(state, actions, autoFocus)
            if (!expanded) FilterRow(state, actions)
            Row(Modifier.fillMaxSize()) {
                if (expanded) FilterPane(state, actions, Modifier.width(300.dp).fillMaxHeight())
                Box(Modifier.weight(1f).fillMaxHeight()) { SearchBody(state, actions) }
            }
        }
    }
}

@Composable
private fun SearchField(state: SearchState, actions: SearchActions, autoFocus: Boolean) {
    val field = rememberTextFieldState(state.query)
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { if (autoFocus) runCatching { focus.requestFocus() } }
    LaunchedEffect(field) { snapshotFlow { field.text.toString() }.collect(actions.onQuery) }
    LaunchedEffect(state.query) { if (field.text.toString() != state.query) field.setTextAndPlaceCursorAtEnd(state.query) }
    val label =
        state.scope?.let { stringResource(StringsR.string.search_field_scoped, it.name) } ?: stringResource(StringsR.string.search_field)
    Row(
        Modifier.fillMaxWidth().padding(start = 4.dp, end = 12.dp, top = 8.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        BentoIconButton(BentoIcons.ArrowLeft, stringResource(StringsR.string.common_action_back), actions.onBack)
        BentoTextField(
            field,
            label,
            Modifier.weight(1f).focusRequester(focus),
            hideLabel = true,
            placeholder = label,
            leadingIcon = BentoIcons.Search,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
            onKeyboardAction = { actions.onSubmit() },
            trailing = if (state.query.isNotEmpty()) {
                {
                    BentoIconButton(BentoIcons.X, stringResource(StringsR.string.search_clear), {
                        field.setTextAndPlaceCursorAtEnd("")
                    }, dense = true)
                }
            } else {
                null
            }
        )
    }
}

@Composable
private fun kindLabel(kind: SearchKind): String = stringResource(
    when (kind) {
        SearchKind.Photos -> StringsR.string.search_kind_photos
        SearchKind.Videos -> StringsR.string.search_kind_videos
        SearchKind.Pdf -> StringsR.string.search_kind_pdf
        SearchKind.Documents -> StringsR.string.search_kind_documents
        SearchKind.Sheets -> StringsR.string.search_kind_sheets
        SearchKind.Folders -> StringsR.string.search_kind_folders
        SearchKind.Albums -> StringsR.string.search_kind_albums
    }
)

@Composable
private fun dateLabel(date: DateFilter): String = when (date) {
    is DateFilter.ThisMonth -> stringResource(StringsR.string.search_date_this_month)

    is DateFilter.LastYear -> stringResource(StringsR.string.search_date_last_year)

    is DateFilter.Year -> date.year.toString()

    is DateFilter.Range -> {
        val format = DateTimeFormatter.ofLocalizedDate(FormatStyle.MEDIUM)
        stringResource(StringsR.string.search_date_range, date.from.format(format), date.to.format(format))
    }
}

/** Filter chips (Tipo, Fecha, Carpeta), each opening its sheet; active ones show their value. */
@Composable
private fun FilterRow(state: SearchState, actions: SearchActions) {
    val filters = state.filters
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        BentoFilterChip(
            filters.kind?.let { kindLabel(it) } ?: stringResource(StringsR.string.search_filter_kind),
            selected = filters.kind != null,
            onSelectedChange = { actions.onSheet(FilterSheet.Kind) },
            leadingIcon = BentoIcons.SlidersHorizontal
        )
        BentoFilterChip(
            filters.date?.let { dateLabel(it) } ?: stringResource(StringsR.string.search_filter_date),
            selected = filters.date != null,
            onSelectedChange = { actions.onSheet(FilterSheet.Date) },
            leadingIcon = BentoIcons.Calendar
        )
        BentoFilterChip(
            filters.folder?.let { stringResource(StringsR.string.search_filter_folder_value, it.name) }
                ?: stringResource(StringsR.string.search_filter_folder),
            selected = filters.folder != null,
            onSelectedChange = { actions.onSheet(FilterSheet.Folder) },
            leadingIcon = BentoIcons.FolderClosed
        )
        if (filters.active) {
            BentoChip(stringResource(StringsR.string.search_empty_remove_filters), actions.onClearFilters, trailingIcon = BentoIcons.X)
        }
    }
}

/** ≥ 840 dp: filters as a side pane. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun FilterPane(state: SearchState, actions: SearchActions, modifier: Modifier) {
    val filters = state.filters
    LazyColumn(modifier.background(BentoTheme.colors.surface), contentPadding = PaddingValues(16.dp)) {
        item { SectionHeader(stringResource(StringsR.string.search_filters_title)) }
        item { SectionHeader(stringResource(StringsR.string.search_filter_kind)) }
        item {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                SearchKind.entries.forEach { kind ->
                    BentoFilterChip(kindLabel(kind), selected = filters.kind == kind, onSelectedChange = {
                        actions.onKind(if (it) kind else null)
                    })
                }
            }
        }
        item { SectionHeader(stringResource(StringsR.string.search_filter_date)) }
        item { DateChips(state, actions) }
        item { SectionHeader(stringResource(StringsR.string.search_filter_folder)) }
        item {
            BentoFilterChip(
                filters.folder?.let { stringResource(StringsR.string.search_filter_folder_value, it.name) }
                    ?: stringResource(StringsR.string.search_filter_any),
                selected = filters.folder != null,
                onSelectedChange = { actions.onSheet(FilterSheet.Folder) },
                leadingIcon = BentoIcons.FolderClosed
            )
        }
        if (filters.active) {
            item {
                BentoButton(
                    stringResource(StringsR.string.search_empty_remove_filters),
                    actions.onClearFilters,
                    Modifier.padding(top = 16.dp),
                    variant = BentoButtonVariant.Ghost
                )
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun DateChips(state: SearchState, actions: SearchActions) {
    val date = state.filters.date
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        BentoFilterChip(stringResource(StringsR.string.search_date_this_month), date is DateFilter.ThisMonth, {
            if (it) actions.onThisMonth() else actions.onDate(null)
        })
        BentoFilterChip(stringResource(StringsR.string.search_date_last_year), date is DateFilter.LastYear, {
            if (it) actions.onLastYear() else actions.onDate(null)
        })
        state.suggestions.years.forEach { year ->
            BentoFilterChip(year.toString(), (date as? DateFilter.Year)?.year == year, {
                if (it) actions.onYear(year) else actions.onDate(null)
            })
        }
    }
}

@Composable
private fun SearchBody(state: SearchState, actions: SearchActions) {
    when {
        state.idle -> IdleBody(state, actions)

        state.loading && state.results.isEmpty() -> LoadingState(
            Modifier.fillMaxSize(),
            label = stringResource(StringsR.string.search_searching)
        )

        state.failed -> ErrorState(stringResource(StringsR.string.search_failed), Modifier.padding(16.dp), onRetry = actions.onRetry)

        state.noResults -> NoResults(state, actions)

        else -> Results(state, actions)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun IdleBody(state: SearchState, actions: SearchActions) {
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
        if (state.recents.isNotEmpty()) {
            item {
                SectionHeader(
                    stringResource(StringsR.string.search_recent),
                    actionLabel = stringResource(StringsR.string.search_recent_clear),
                    onAction = actions.onClearRecents
                )
            }
            items(state.recents, key = { "recent:$it" }) { recent -> RecentRow(recent, actions) }
            item {
                Text(
                    stringResource(StringsR.string.search_recent_local),
                    color = BentoTheme.colors.inkSubtle,
                    style = BentoTheme.typography.metadata,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
                )
            }
        }
        item { SectionHeader(stringResource(StringsR.string.search_suggest_types)) }
        item {
            FlowRow(
                Modifier.padding(horizontal = 16.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                listOf(SearchKind.Photos, SearchKind.Videos, SearchKind.Pdf, SearchKind.Documents, SearchKind.Sheets).forEach { kind ->
                    BentoChip(kindLabel(kind), { actions.onKind(kind) }, leadingIcon = kindIcon(kind))
                }
            }
        }
        item { SectionHeader(stringResource(StringsR.string.search_suggest_time)) }
        item { Box(Modifier.padding(horizontal = 16.dp)) { DateChips(state, actions) } }
        if (state.suggestions.folders.isNotEmpty()) {
            item { SectionHeader(stringResource(StringsR.string.search_suggest_folders)) }
            item {
                FlowRow(
                    Modifier.padding(horizontal = 16.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    state.suggestions.folders.forEach { folder ->
                        BentoChip(folder.name, { actions.onFolder(folder) }, leadingIcon = BentoIcons.FolderClosed)
                    }
                }
            }
        }
        if (state.suggestions.albums.isNotEmpty()) {
            item { SectionHeader(stringResource(StringsR.string.search_suggest_albums)) }
            item {
                FlowRow(
                    Modifier.padding(horizontal = 16.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    state.suggestions.albums.forEach { album ->
                        BentoChip(album.title, { actions.onOpenAlbum(album.id) }, leadingIcon = BentoIcons.SquareLibrary)
                    }
                }
            }
        }
    }
}

private fun kindIcon(kind: SearchKind) = when (kind) {
    SearchKind.Photos -> BentoIcons.Images
    SearchKind.Videos -> BentoIcons.Play
    SearchKind.Pdf, SearchKind.Documents -> BentoIcons.FileText
    SearchKind.Sheets -> BentoIcons.FileSpreadsheet
    SearchKind.Folders -> BentoIcons.FolderClosed
    SearchKind.Albums -> BentoIcons.SquareLibrary
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RecentRow(recent: String, actions: SearchActions) {
    val dismiss = rememberSwipeToDismissBoxState()
    LaunchedEffect(dismiss.currentValue) {
        if (dismiss.currentValue != androidx.compose.material3.SwipeToDismissBoxValue.Settled) actions.onRemoveRecent(recent)
    }
    val removeLabel = stringResource(StringsR.string.search_recent_remove, recent)
    SwipeToDismissBox(dismiss, backgroundContent = { Box(Modifier.fillMaxSize().background(BentoTheme.colors.dangerSoft)) }) {
        ListRow(
            headline = recent,
            modifier = Modifier.background(BentoTheme.colors.tray).semantics {
                customActions = listOf(CustomAccessibilityAction(removeLabel) { actions.onRemoveRecent(recent).let { true } })
            },
            leading = { BentoIcon(BentoIcons.History, null, tint = BentoTheme.colors.inkSubtle) },
            trailing = { BentoIconButton(BentoIcons.X, removeLabel, { actions.onRemoveRecent(recent) }, dense = true) },
            onClick = { actions.onRecent(recent) }
        )
    }
}

@Composable
private fun NoResults(state: SearchState, actions: SearchActions) {
    val withFilters = state.filters.active
    EmptyState(
        title = if (state.query.isNotBlank()) {
            stringResource(StringsR.string.search_empty_title, state.query.trim())
        } else {
            stringResource(StringsR.string.search_empty_title_filters)
        },
        body = stringResource(if (withFilters) StringsR.string.search_empty_body_filters else StringsR.string.search_empty_body),
        icon = BentoIcons.Search,
        modifier = Modifier.fillMaxSize().padding(24.dp),
        action = {
            Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (state.scope != null && state.filters.folder != null) {
                    BentoButton(
                        stringResource(StringsR.string.search_empty_everywhere),
                        actions.onEverywhere,
                        variant = BentoButtonVariant.Primary
                    )
                }
                if (withFilters) BentoButton(stringResource(StringsR.string.search_empty_remove_filters), actions.onClearFilters)
            }
        }
    )
}

@Composable
private fun Results(state: SearchState, actions: SearchActions) {
    val groups = state.grouped
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
        if (state.indexing) {
            item {
                Callout(
                    Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                    tone = CalloutTone.Info,
                    body = stringResource(StringsR.string.search_indexing),
                    icon = BentoIcons.Sparkles
                )
            }
        }
        groups.forEach { (group, items) -> group(group, items, state.query, actions) }
        if (state.nextCursor != null) {
            item {
                BentoButton(
                    stringResource(StringsR.string.search_load_more),
                    actions.onLoadMore,
                    Modifier.fillMaxWidth().padding(16.dp),
                    variant = BentoButtonVariant.Ghost,
                    loading = state.loadingMore
                )
            }
        }
    }
}

private fun LazyListScope.group(group: ResultGroup, items: List<SearchItemResponse>, query: String, actions: SearchActions) {
    val title = when (group) {
        ResultGroup.Photos -> StringsR.string.search_group_photos
        ResultGroup.Folders -> StringsR.string.search_group_folders
        ResultGroup.Files -> StringsR.string.search_group_files
        ResultGroup.Documents -> StringsR.string.search_group_documents
    }
    item(key = "header:$group") { SectionHeader(stringResource(title)) }
    if (group == ResultGroup.Photos) {
        item(key = "strip") {
            LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                items(items, key = { "${it.type}:${it.id}" }) { item -> PhotoHit(item, actions) }
            }
        }
    } else {
        items(items, key = { "${it.type}:${it.id}" }) { item -> ResultRow(item, query, actions) }
    }
}

@Composable
private fun PhotoHit(item: SearchItemResponse, actions: SearchActions) {
    val loader = LocalBentoImageLoader.current
    val label = stringResource(
        if (item.type ==
            "video"
        ) {
            StringsR.string.search_result_video
        } else {
            StringsR.string.search_result_photo
        },
        item.title
    )
    val painter = if (loader != null &&
        item.assetId != null
    ) {
        rememberAsyncImagePainter(BentoImage.thumbnail(item.assetId!!), loader)
    } else {
        null
    }
    Box(
        Modifier.size(112.dp).padding(2.dp).semantics(mergeDescendants = true) {}
    ) {
        Thumbnail(
            painter = painter,
            contentDescription = label,
            modifier = Modifier.fillMaxSize().clickableHit { actions.onOpen(item) },
            placeholder = {
                Box(Modifier.fillMaxSize().background(BentoTheme.colors.subtle)) {
                    KindIcon(FileKind.Image, Modifier.align(Alignment.Center))
                }
            }
        )
    }
}

private fun Modifier.clickableHit(onClick: () -> Unit): Modifier = clip(BentoShapes.xs).clickable(onClick = onClick)

@Composable
private fun ResultRow(item: SearchItemResponse, query: String, actions: SearchActions) {
    val c = BentoTheme.colors
    val kind = when (item.type) {
        "folder" -> FileKind.Folder
        "album" -> FileKind.Image
        else -> FileKinds.fileKind(null, item.title)
    }
    val reasons = MatchReasons.parse(item.reason)
    val reasonText = reasons.map { reasonLabel(it, item, query) }.distinct().joinToString(" · ")
    val supporting = listOfNotNull(
        when (item.type) {
            "folder" -> stringResource(StringsR.string.search_result_folder)
            "album" -> stringResource(StringsR.string.search_result_album)
            else -> item.subtitle?.takeUnless { isPage(item) || it == "OCR" }
        }
    ).joinToString()
    Column(
        Modifier.fillMaxWidth()
    ) {
        ListRow(
            headline = item.title,
            supporting = supporting.ifEmpty { null },
            leading = { KindIcon(kind) },
            onClick = { actions.onOpen(item) },
            modifier = Modifier.semantics(mergeDescendants = true) {}
        )
        Row(
            Modifier.fillMaxWidth().padding(start = 70.dp, end = 16.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            BentoIcon(BentoIcons.Sparkles, null, tint = c.accent, size = BentoIconSize.Dense)
            Text(
                highlighted(reasonText, query, c.accentInk),
                color = c.inkMuted,
                style = BentoTheme.typography.metadata,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )
        }
    }
}

// Exhaustive reason → copy table.
@Suppress("CyclomaticComplexMethod")
@Composable
private fun reasonLabel(reason: MatchReason, item: SearchItemResponse, query: String): String {
    val fragment = query.trim()
    return when (reason) {
        MatchReason.ImageText -> {
            val page = pageOf(item)
            when {
                page != null -> stringResource(StringsR.string.search_reason_page_text, page, fragment)

                FileKinds.openKind(null, item.title) == dev.bento.feature.files.OpenKind.Image || item.type == "ocr_block" ->
                    stringResource(StringsR.string.search_reason_image_text, fragment)

                else -> stringResource(StringsR.string.search_reason_document_text, fragment)
            }
        }

        MatchReason.DocumentText -> pageOf(item)?.let { stringResource(StringsR.string.search_reason_page_text, it, fragment) }
            ?: stringResource(StringsR.string.search_reason_document_text, fragment)

        MatchReason.Name -> stringResource(StringsR.string.search_reason_name)

        MatchReason.Folder -> stringResource(StringsR.string.search_reason_folder_plain)

        MatchReason.DocumentType -> stringResource(StringsR.string.search_reason_document_type)

        MatchReason.Date -> stringResource(StringsR.string.search_reason_date)

        MatchReason.Album -> stringResource(StringsR.string.search_reason_album)

        MatchReason.Details -> stringResource(StringsR.string.search_reason_details)

        MatchReason.Recent -> stringResource(StringsR.string.search_reason_recent)

        MatchReason.Meaning, MatchReason.Generic -> stringResource(StringsR.string.search_reason_generic)
    }
}

/** Bold + accent ink on every fragment of [text] that matches the query (accent-insensitive). */
fun highlighted(text: String, query: String, color: androidx.compose.ui.graphics.Color): AnnotatedString {
    val ranges = highlights(text, query)
    if (ranges.isEmpty()) return AnnotatedString(text)
    return buildAnnotatedString {
        append(text)
        ranges.forEach { range -> addStyle(SpanStyle(fontWeight = FontWeight.SemiBold, color = color), range.first, range.last + 1) }
    }
}

@Composable
fun KindSheetBody(selected: SearchKind?, onPick: (SearchKind?) -> Unit) {
    dev.bento.feature.files.SheetBody(stringResource(StringsR.string.search_filter_kind_title)) {
        ListRow(
            headline = stringResource(StringsR.string.search_filter_any),
            leading = { BentoIcon(if (selected == null) BentoIcons.Check else BentoIcons.Search, null) },
            onClick = { onPick(null) },
            selected = selected == null
        )
        SearchKind.entries.forEach { kind ->
            ListRow(
                headline = kindLabel(kind),
                leading = { BentoIcon(if (selected == kind) BentoIcons.Check else kindIcon(kind), null) },
                onClick = { onPick(kind) },
                selected = selected == kind
            )
        }
    }
}
