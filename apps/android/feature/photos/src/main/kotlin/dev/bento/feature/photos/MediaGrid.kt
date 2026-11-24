package dev.bento.feature.photos

import androidx.compose.animation.AnimatedVisibilityScope
import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyGridState
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.isCtrlPressed
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.collectionInfo
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import dev.bento.api.generated.AssetResponse
import dev.bento.data.TimelineLayout
import dev.bento.designsystem.component.SelectionCheck
import dev.bento.designsystem.component.bentoMediaKey
import dev.bento.designsystem.component.bentoSharedMedia
import dev.bento.designsystem.theme.BentoHaptic
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.designsystem.theme.bentoHaptics
import dev.bento.strings.R as StringsR
import java.time.LocalDate
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive

/** Density, one scroll state per density (crossfaded, never resized), and the pinch focal anchor. */
@Stable
class MediaGridState(initialDensity: GridDensity = GridDensity.Comfortable) {
    var density: GridDensity by mutableStateOf(initialDensity)
        private set
    private val states = HashMap<GridDensity, LazyGridState>()
    internal var anchor: DensityAnchor? = null

    fun gridState(density: GridDensity = this.density): LazyGridState = states.getOrPut(density) { LazyGridState() }

    val current: LazyGridState get() = gridState(density)

    /** Change density keeping [anchor] (the item under the fingers, or the first visible one) in place. */
    fun changeDensity(target: GridDensity, anchor: DensityAnchor?) {
        if (target == density) return
        this.anchor = anchor
        density = target
    }

    suspend fun scrollToTop() = current.animateScrollToItem(0)
}

/** Where the focal item was: its key, its photo position (fallback), and where on screen it should stay. */
data class DensityAnchor(val key: String, val photoPosition: Int, val focusY: Float, val fractionY: Float)

/** Callbacks a grid exposes on each tile (also TalkBack custom actions). */
class MediaGridCallbacks(
    /** [position] is the photo's position in the collection (media only, no headers). */
    val onOpen: (cell: GridCell.Media, position: Int) -> Unit,
    val onFavorite: ((AssetResponse) -> Unit)? = null,
    val onShare: ((AssetResponse) -> Unit)? = null,
    val onDelete: ((AssetResponse) -> Unit)? = null,
    /** Fast scroller / fling landed in placeholders: load the page that starts at this photo position. */
    val onJump: ((Int) -> Unit)? = null,
    /** `Delete` key with a selection (keyboard). */
    val onDeleteSelection: (() -> Unit)? = null
)

/**
 * The photo grid shared by Fotos and Colecciones: uniform square tiles, 2 dp gutters, month headers (sticky as an
 * overlay with the push-up effect) and day sub-headers, pinch density anchored on the focal item, long-press + drag
 * range selection with edge auto-scroll, fast scroller with date bubble and year ticks (when a [layout] is given),
 * keyboard shortcuts, and TalkBack actions on every tile.
 */
@Suppress("LongMethod", "CyclomaticComplexMethod")
@Composable
fun MediaGrid(
    cellsFor: (GridDensity) -> MediaCells,
    state: MediaGridState,
    selection: SelectionState,
    callbacks: MediaGridCallbacks,
    modifier: Modifier = Modifier,
    layout: TimelineLayout? = null,
    contentPadding: PaddingValues = PaddingValues(),
    pinchEnabled: Boolean = true,
    animatedScope: AnimatedVisibilityScope? = null,
    /** Library picker: taps always toggle selection (no viewer). */
    pickMode: Boolean = false,
    top: (@Composable () -> Unit)? = null
) {
    val haptics = bentoHaptics()
    val reduced = BentoTheme.motion.reduced
    val moreLabel = stringResource(StringsR.string.photos_density_more)
    val lessLabel = stringResource(StringsR.string.photos_density_less)
    val gridLabel = stringResource(StringsR.string.photos_grid_label)
    BoxWithConstraints(
        modifier
            .fillMaxSize()
            .semantics {
                contentDescription = gridLabel
                customActions = listOf(
                    CustomAccessibilityAction(moreLabel) { state.changeDensity(state.density.smaller(), null).let { true } },
                    CustomAccessibilityAction(lessLabel) { state.changeDensity(state.density.larger(), null).let { true } }
                )
            }
    ) {
        val widthDp = maxWidth.value
        Crossfade(targetState = state.density, animationSpec = tween(if (reduced) 120 else 180), label = "grid-density") { density ->
            val cells = cellsFor(density)
            DensityGrid(
                density = density,
                columns = density.columns(widthDp),
                widthDp = widthDp,
                cells = cells,
                gridState = state.gridState(density),
                state = state,
                selection = selection,
                callbacks = callbacks,
                layout = layout,
                contentPadding = contentPadding,
                animatedScope = animatedScope,
                top = top,
                pickMode = pickMode,
                onPinchStep = { direction, centroid ->
                    val target = if (direction > 0) density.larger() else density.smaller()
                    if (target != density) {
                        haptics.perform(BentoHaptic.SegmentTick)
                        state.changeDensity(target, focalAnchor(state.gridState(density), cells, centroid, if (top != null) 1 else 0))
                    }
                },
                pinchEnabled = pinchEnabled
            )
        }
    }
}

private fun focalAnchor(grid: LazyGridState, cells: MediaCells, centroid: Offset, topOffset: Int): DensityAnchor? {
    val items = grid.layoutInfo.visibleItemsInfo
    val hit = items.firstOrNull { centroid.y >= it.offset.y && centroid.y < it.offset.y + it.size.height && it.index >= topOffset }
        ?: items.firstOrNull { it.index >= topOffset }
        ?: return null
    val cell = cells.peek(hit.index - topOffset)
    val key = cell?.key ?: return null
    return DensityAnchor(
        key = key,
        photoPosition = cells.positions().photoAt(hit.index - topOffset),
        focusY = centroid.y,
        fractionY = ((centroid.y - hit.offset.y) / hit.size.height.coerceAtLeast(1)).coerceIn(0f, 1f)
    )
}

@Suppress("LongMethod", "LongParameterList", "CyclomaticComplexMethod")
@Composable
private fun DensityGrid(
    density: GridDensity,
    columns: Int,
    widthDp: Float,
    cells: MediaCells,
    gridState: LazyGridState,
    state: MediaGridState,
    selection: SelectionState,
    callbacks: MediaGridCallbacks,
    layout: TimelineLayout?,
    contentPadding: PaddingValues,
    animatedScope: AnimatedVisibilityScope?,
    top: (@Composable () -> Unit)?,
    pickMode: Boolean,
    onPinchStep: (Int, Offset) -> Unit,
    pinchEnabled: Boolean
) {
    val topOffset = if (top != null) 1 else 0
    val haptics = bentoHaptics()
    val labels = TileLabels.current()
    val map = cells.positions()

    // Keep the same photo at the top when a refresh/jump replaces the loaded block (positions are exact, see PositionMap).
    val previous = remember { arrayOfNulls<PositionMap>(1) }
    SideEffect {
        val old = previous[0]
        previous[0] = map
        if (old != null && old !== map && !selection.dragging) {
            val first = gridState.firstVisibleItemIndex - topOffset
            if (first > 0) {
                val photo = old.photoAt(first)
                val target = map.indexOf(photo) + topOffset
                val wasHeader = cells.peek(first) !is GridCell.Media && cells.peek(first) != null
                if (!wasHeader && target != gridState.firstVisibleItemIndex) {
                    gridState.requestScrollToItem(target, gridState.firstVisibleItemScrollOffset)
                }
            }
        }
    }

    // Restore the pinch anchor once this density's grid has laid out.
    LaunchedEffect(density) {
        val anchor = state.anchor ?: return@LaunchedEffect
        state.anchor = null
        var index = (0 until cells.count).firstOrNull { cells.peek(it)?.key == anchor.key } ?: map.indexOf(anchor.photoPosition)
        index += topOffset
        gridState.scrollToItem(index)
        val info = gridState.layoutInfo.visibleItemsInfo.firstOrNull { it.index == index } ?: return@LaunchedEffect
        val desiredTop = anchor.focusY - anchor.fractionY * info.size.height
        gridState.scrollBy(-(desiredTop - info.offset.y))
    }

    // Edge auto-scroll while range-selecting.
    var autoScroll by remember { mutableFloatStateOf(0f) }
    var lastPointer by remember { mutableStateOf(Offset.Zero) }
    LaunchedEffect(autoScroll) {
        if (autoScroll == 0f) return@LaunchedEffect
        while (isActive) {
            gridState.scrollBy(autoScroll)
            gridState.itemIndexAt(lastPointer)?.let { selection.dragTo(it - topOffset, cells) }
            delay(16)
        }
    }

    // A fling that settles inside placeholders loads that spot directly instead of walking every page.
    LaunchedEffect(gridState, callbacks.onJump) {
        val jump = callbacks.onJump ?: return@LaunchedEffect
        androidx.compose.runtime.snapshotFlow { gridState.isScrollInProgress }.collect { scrolling ->
            if (scrolling) return@collect
            val first = gridState.firstVisibleItemIndex - topOffset
            if (first >= 0 && first < cells.count && cells.peek(first) == null) jump(cells.positions().photoAt(first))
        }
    }

    val density4 = LocalDensity.current
    var viewportHeight by remember { mutableFloatStateOf(0f) }
    val edge = with(density4) { 64.dp.toPx() }
    val cellPx = with(density4) { (widthDp.dp / columns).roundToPx() }.coerceAtLeast(64)

    Box(Modifier.fillMaxSize().onSizeChanged { viewportHeight = it.height.toFloat() }) {
        LazyVerticalGrid(
            columns = GridCells.Fixed(columns),
            state = gridState,
            contentPadding = contentPadding,
            horizontalArrangement = Arrangement.spacedBy(2.dp),
            verticalArrangement = Arrangement.spacedBy(2.dp),
            modifier = Modifier
                .fillMaxSize()
                .testTag(MediaTestTags.Grid)
                .semantics { collectionInfo = androidx.compose.ui.semantics.CollectionInfo(-1, columns) }
                .onPreviewKeyEvent { event ->
                    if (event.type != KeyEventType.KeyDown) return@onPreviewKeyEvent false
                    when {
                        event.isCtrlPressed && event.key == Key.A -> {
                            selection.set((0 until cells.count).mapNotNull { (cells.peek(it) as? GridCell.Media)?.asset }, true)
                            true
                        }

                        (event.key == Key.Delete || event.key == Key.Backspace) && selection.active -> {
                            callbacks.onDeleteSelection?.invoke()
                            true
                        }

                        event.key == Key.Escape && selection.active -> {
                            selection.clear()
                            true
                        }

                        else -> false
                    }
                }
                .pinchToDensity(pinchEnabled, onPinchStep)
                .longPressDragSelect(
                    enabled = true,
                    onStart = { offset ->
                        val index = gridState.itemIndexAt(offset)?.minus(topOffset) ?: return@longPressDragSelect false
                        lastPointer = offset
                        selection.beginDrag(index, cells).also { if (it) haptics.perform(BentoHaptic.LongPress) }
                    },
                    onDrag = { position ->
                        lastPointer = position
                        gridState.itemIndexAt(position)?.let { selection.dragTo(it - topOffset, cells) }
                        autoScroll = when {
                            position.y < edge -> -(edge - position.y).coerceAtMost(edge) / 2.5f
                            position.y > viewportHeight - edge -> (position.y - (viewportHeight - edge)).coerceAtMost(edge) / 2.5f
                            else -> 0f
                        }
                    },
                    onEnd = {
                        autoScroll = 0f
                        selection.endDrag()
                    }
                )
        ) {
            if (top != null) item(key = "top", span = { GridItemSpan(maxLineSpan) }, contentType = "top") { top() }
            items(
                count = cells.count,
                key = { index -> cells.peek(index)?.key ?: "placeholder:$index" },
                span = { index ->
                    if (cells.peek(index).let { it is GridCell.Month || it is GridCell.Day }) GridItemSpan(maxLineSpan) else GridItemSpan(1)
                },
                contentType = { index ->
                    when (cells.peek(index)) {
                        is GridCell.Month -> 1
                        is GridCell.Day -> 2
                        else -> 0
                    }
                }
            ) { index ->
                when (val cell = cells[index]) {
                    null -> PlaceholderTile()

                    is GridCell.Month -> MonthHeader(cell.month, Modifier.testTag(MediaTestTags.header(cell.key)))

                    is GridCell.Day -> DayHeader(
                        date = cell.date,
                        selectionMode = selection.active || pickMode,
                        dayAssets = { dayAssets(cells, index) },
                        selection = selection,
                        modifier = Modifier.testTag(MediaTestTags.header(cell.key))
                    )

                    is GridCell.Media -> {
                        val asset = cell.asset
                        val selected = asset.id in selection
                        MediaTile(
                            asset = asset,
                            date = cell.date,
                            sizePx = cellPx,
                            selected = selected,
                            selectionMode = selection.active || pickMode,
                            labels = labels,
                            actions = TileActions(
                                onOpen = { callbacks.onOpen(cell, cells.positions().photoAt(index)) },
                                onToggleSelect = { selection.toggle(asset) },
                                onFavorite = callbacks.onFavorite?.let { { it(asset) } },
                                onShare = callbacks.onShare?.let { { it(asset) } },
                                onDelete = callbacks.onDelete?.let { { it(asset) } }
                            ),
                            modifier = Modifier.bentoSharedMedia(bentoMediaKey(asset.id), animatedScope)
                        )
                    }
                }
            }
        }

        StickyMonthHeader(gridState, cells, layout, topOffset)

        if (layout != null && map.totalPhotos > FAST_SCROLLER_MIN) {
            FastScroller(
                gridState = gridState,
                cells = cells,
                layout = layout,
                topOffset = topOffset,
                onJump = callbacks.onJump,
                modifier = Modifier.align(Alignment.TopEnd).padding(top = contentPadding.calculateTopPadding())
            )
        }
    }
}

private const val FAST_SCROLLER_MIN = 60

/** Loaded media of the day whose header is at [headerIndex]. */
private fun dayAssets(cells: MediaCells, headerIndex: Int): List<AssetResponse> = buildList {
    var i = headerIndex + 1
    while (i < cells.count) {
        when (val cell = cells.peek(i)) {
            is GridCell.Media -> add(cell.asset)
            null -> Unit
            else -> return@buildList
        }
        i++
    }
}

@Composable
private fun PlaceholderTile() {
    Box(Modifier.aspectRatio(1f).background(BentoTheme.colors.sunken).clearAndSetSemantics {})
}

@Composable
internal fun MonthHeader(month: String, modifier: Modifier = Modifier) {
    val locale = LocalConfiguration.current.locales[0]
    Text(
        MediaFormat.monthTitle(month, locale),
        color = BentoTheme.colors.ink,
        style = BentoTheme.typography.monthHeader,
        modifier = modifier
            .fillMaxWidth()
            .background(BentoTheme.colors.surface)
            .padding(start = 16.dp, end = 16.dp, top = 20.dp, bottom = 8.dp)
            .semantics { heading() }
    )
}

@Composable
private fun DayHeader(
    date: String,
    selectionMode: Boolean,
    dayAssets: () -> List<AssetResponse>,
    selection: SelectionState,
    modifier: Modifier = Modifier
) {
    val locale = LocalConfiguration.current.locales[0]
    val title = dayLabel(date, locale)
    val c = BentoTheme.colors
    val allSelected = selectionMode && dayAssets().let { list -> list.isNotEmpty() && list.all { it.id in selection } }
    val toggleLabel =
        stringResource(if (allSelected) StringsR.string.photos_action_unselect_day else StringsR.string.photos_action_select_day, title)
    Row(
        modifier
            .fillMaxWidth()
            .heightIn(min = 40.dp)
            .then(
                if (selectionMode) {
                    Modifier.toggleable(allSelected, role = Role.Checkbox) { selection.set(dayAssets(), !allSelected) }
                        .semantics { contentDescription = toggleLabel }
                } else {
                    Modifier
                }
            )
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        if (selectionMode) SelectionCheck(allSelected)
        Text(title, color = c.inkMuted, style = BentoTheme.typography.label, modifier = Modifier.semantics { heading() })
    }
}

@Composable
private fun dayLabel(date: String, locale: java.util.Locale): String {
    val today = LocalDate.now(java.time.ZoneOffset.UTC)
    return when (date.take(10)) {
        today.toString() -> stringResource(StringsR.string.photos_header_today)
        today.minusDays(1).toString() -> stringResource(StringsR.string.photos_header_yesterday)
        else -> MediaFormat.dayTitle(date, locale, today)
    }
}

/**
 * The current month pinned at the top while scrolling; the next month header pushes it up. Decorative for TalkBack
 * (the real headers in the grid are the headings).
 */
@Composable
private fun StickyMonthHeader(gridState: LazyGridState, cells: MediaCells, layout: TimelineLayout?, topOffset: Int) {
    val month by remember(cells, layout) {
        derivedStateOf {
            val first = gridState.firstVisibleItemIndex - topOffset
            if (first < 0 || (first == 0 && gridState.firstVisibleItemScrollOffset == 0)) return@derivedStateOf null
            cells.peek(first)?.month ?: layout?.let { l ->
                val m = l.monthAt(cells.positions().photoAt(first))
                l.months.getOrNull(m)?.month
            }
        }
    }
    val current = month ?: return
    var height by remember { mutableFloatStateOf(0f) }
    Box(
        Modifier
            .fillMaxWidth()
            .testTag(MediaTestTags.StickyHeader)
            .onSizeChanged { height = it.height.toFloat() }
            .graphicsLayer {
                val next = gridState.layoutInfo.visibleItemsInfo.firstOrNull { item ->
                    (item.key as? String)?.startsWith("month:") == true && item.key != "month:$current" && item.offset.y > 0
                }
                translationY = if (next != null && next.offset.y < height) (next.offset.y - height) else 0f
            }
            .clearAndSetSemantics {}
    ) {
        MonthHeader(current)
    }
}
