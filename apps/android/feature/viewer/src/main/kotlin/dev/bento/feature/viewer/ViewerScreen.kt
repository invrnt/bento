package dev.bento.feature.viewer

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.activity.compose.LocalActivity
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.AnimatedVisibilityScope
import androidx.compose.animation.core.Animatable
import androidx.compose.foundation.background
import androidx.compose.foundation.focusable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.util.VelocityTracker
import androidx.compose.ui.layout.layout
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.testTagsAsResourceId
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.media3.common.Player
import androidx.paging.compose.LazyPagingItems
import androidx.paging.compose.collectAsLazyPagingItems
import dev.bento.api.generated.AssetResponse
import dev.bento.designsystem.component.BentoFavoriteButton
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.BentoIconButton
import dev.bento.designsystem.component.BentoIconButtonVariant
import dev.bento.designsystem.component.BentoSnackbarHost
import dev.bento.designsystem.component.BentoSnackbarHostState
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.ProgressBar
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoMediaTheme
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.photos.Disclosure
import dev.bento.feature.photos.LocalBentoImageLoader
import dev.bento.feature.photos.MediaActions
import dev.bento.feature.photos.MediaEventsEffect
import dev.bento.feature.photos.MediaFormat
import dev.bento.feature.photos.MediaSheet
import dev.bento.feature.photos.MediaSheetHost
import dev.bento.feature.photos.TrackJank
import dev.bento.feature.photos.tileDescription
import dev.bento.strings.R as StringsR
import kotlinx.coroutines.launch

class ViewerNavigation(val back: () -> Unit, val openFolder: (String) -> Unit, val openActivity: () -> Unit)

@Composable
fun ViewerRoute(args: ViewerArgs, navigation: ViewerNavigation, animatedScope: AnimatedVisibilityScope? = null) {
    val vm = hiltViewModel<ViewerViewModel, ViewerViewModel.Factory>(key = "viewer:${args.assetId}:${args.session}") { it.create(args) }
    val items = vm.pages.collectAsLazyPagingItems()
    val info by vm.info.collectAsStateWithLifecycle()
    val busy by vm.actions.busy.collectAsStateWithLifecycle()
    val message by vm.message.collectAsStateWithLifecycle()
    val locale = LocalConfiguration.current.locales[0]
    val snackbar = remember { BentoSnackbarHostState() }
    val context = LocalContext.current
    LaunchedEffect(message) {
        message?.let {
            vm.messageShown()
            snackbar.show(it.resolve(context))
        }
    }
    BentoMediaTheme {
        CompositionLocalProvider(LocalBentoImageLoader provides vm.imageLoader) {
            ViewerContent(
                items = ViewerItems.Paging(items),
                opening = vm.opening,
                initialPage = vm.initialPage,
                expectedCount = vm.expectedCount,
                info = info,
                actions = vm.actions,
                busy = busy,
                snackbar = snackbar,
                navigation = navigation,
                animatedScope = animatedScope,
                player = { vm.player },
                video = VideoHooks(
                    prepare = { asset -> vm.prepareVideo(asset, autoplay = true) },
                    stop = vm::stopVideo
                ),
                onCurrent = vm::onCurrent,
                onLoadInfo = { vm.loadInfo(it, locale) },
                onOffline = vm::setOffline
            )
        }
    }
}

/** What the pager shows: live paging, or a fixed list (previews/tests). */
sealed interface ViewerItems {
    val count: Int

    fun get(index: Int): AssetResponse?

    class Paging(val items: LazyPagingItems<AssetResponse>) : ViewerItems {
        override val count: Int get() = items.itemCount

        override fun get(index: Int): AssetResponse? = if (index in 0 until items.itemCount) items[index] else null
    }

    class Fixed(val items: List<AssetResponse>) : ViewerItems {
        override val count: Int get() = items.size

        override fun get(index: Int): AssetResponse? = items.getOrNull(index)
    }
}

class VideoHooks(val prepare: (AssetResponse) -> Unit, val stop: () -> Unit)

/** Which viewer-only sheet is open. */
private sealed interface ViewerSheet {
    data object Info : ViewerSheet

    data object Rename : ViewerSheet

    data object Speed : ViewerSheet
}

@Suppress("LongMethod", "LongParameterList", "CyclomaticComplexMethod")
@Composable
fun ViewerContent(
    items: ViewerItems,
    opening: AssetResponse?,
    initialPage: Int,
    expectedCount: Int,
    info: ViewerInfo?,
    actions: MediaActions?,
    busy: Boolean,
    snackbar: BentoSnackbarHostState,
    navigation: ViewerNavigation,
    animatedScope: AnimatedVisibilityScope?,
    player: () -> Player?,
    video: VideoHooks,
    onCurrent: (AssetResponse, Int) -> Unit,
    onLoadInfo: (AssetResponse) -> Unit,
    onOffline: (AssetResponse, Boolean) -> Unit,
    modifier: Modifier = Modifier,
    initialChrome: ViewerChrome = ViewerChrome()
) {
    val c = BentoTheme.colors
    var chrome by remember { mutableStateOf(initialChrome) }
    fun dispatch(intent: ViewerIntent) {
        chrome = ViewerReducer.reduce(chrome, intent)
    }
    var mediaSheet by remember { mutableStateOf<MediaSheet?>(null) }
    var viewerSheet by remember { mutableStateOf<ViewerSheet?>(if (initialChrome.infoOpen) ViewerSheet.Info else null) }
    var offlineNotice by remember { mutableStateOf(false) }
    var speed by remember { mutableFloatStateOf(1f) }
    val scope = rememberCoroutineScope()
    val count = maxOf(items.count, expectedCount, if (opening != null) initialPage + 1 else 0)
    val pager = rememberPagerState(initialPage = initialPage.coerceAtLeast(0)) { count }
    fun assetAt(page: Int): AssetResponse? = items.get(page) ?: opening?.takeIf { page == initialPage }
    val current = assetAt(pager.currentPage)

    if (actions != null) {
        MediaEventsEffect(actions, snackbar, onSheet = { mediaSheet = it }, onTrashed = { if (items.count <= 1) navigation.back() })
    }
    LaunchedEffect(pager) {
        snapshotFlow { pager.settledPage }.collect { page ->
            dispatch(ViewerIntent.PageChanged)
            offlineNotice = false
            assetAt(page)?.let { asset ->
                onCurrent(asset, page)
                if (MediaFormat.isVideo(asset)) video.prepare(asset) else video.stop()
            }
        }
    }
    LaunchedEffect(chrome.dismissed) { if (chrome.dismissed) navigation.back() }
    LaunchedEffect(viewerSheet, current?.id) { if (viewerSheet == ViewerSheet.Info && current != null) onLoadInfo(current) }
    SystemBarsForViewer(visible = chrome.chromeVisible)
    TrackJank("Visor", pager.isScrollInProgress)

    BoxWithConstraints(modifier.fillMaxSize().semantics { testTagsAsResourceId = true }) {
        val wide = maxWidth >= 600.dp
        val heightPx = constraints.maxHeight.toFloat().coerceAtLeast(1f)
        val dragY = remember { Animatable(0f) }
        val focus = remember { FocusRequester() }
        LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }

        Box(
            Modifier
                .fillMaxSize()
                .background(c.black.copy(alpha = (1f - chrome.dismissProgress * 1.4f).coerceIn(0f, 1f)))
        )
        Row(Modifier.fillMaxSize()) {
            Box(
                Modifier
                    .weight(1f)
                    .fillMaxHeight()
                    .focusRequester(focus)
                    .focusable()
                    .onKeyEvent { event ->
                        if (event.type != KeyEventType.KeyDown) return@onKeyEvent false
                        when (event.key) {
                            Key.DirectionRight -> scope.launch {
                                pager.animateScrollToPage((pager.currentPage + 1).coerceAtMost(count - 1))
                            }.let { true }

                            Key.DirectionLeft -> scope.launch {
                                pager.animateScrollToPage((pager.currentPage - 1).coerceAtLeast(0))
                            }.let { true }

                            Key.Escape -> navigation.back().let { true }

                            else -> false
                        }
                    }
                    .verticalSwipe(
                        enabled = chrome.verticalGesturesEnabled,
                        onDrag = { delta ->
                            scope.launch { dragY.snapTo(dragY.value + delta) }
                            if (dragY.value + delta > 0) dispatch(ViewerIntent.DismissDrag((dragY.value + delta) / heightPx))
                        },
                        onEnd = { velocity ->
                            when {
                                dragY.value < -heightPx * 0.08f || velocity < -1_400f -> {
                                    dispatch(ViewerIntent.SwipeUp)
                                    viewerSheet = ViewerSheet.Info
                                    scope.launch { dragY.animateTo(0f) }
                                }

                                ViewerReducer.shouldCommitDismiss(dragY.value / heightPx, velocity) && dragY.value > 0 ->
                                    dispatch(ViewerIntent.DismissRelease(commit = true))

                                else -> {
                                    dispatch(ViewerIntent.DismissRelease(commit = false))
                                    scope.launch { dragY.animateTo(0f) }
                                }
                            }
                        }
                    )
                    // Shrink with the finger through layout (not a draw transform) so the shared element returns from
                    // exactly where the photo is.
                    .layout { measurable, constraints ->
                        val progress = (dragY.value / heightPx).coerceIn(0f, 1f)
                        val scale = 1f - 0.3f * progress
                        val w = (constraints.maxWidth * scale).toInt().coerceAtLeast(1)
                        val h = (constraints.maxHeight * scale).toInt().coerceAtLeast(1)
                        val placeable = measurable.measure(Constraints.fixed(w, h))
                        layout(constraints.maxWidth, constraints.maxHeight) {
                            placeable.place(
                                (constraints.maxWidth - w) / 2,
                                (constraints.maxHeight - h) / 2 + dragY.value.toInt().coerceAtLeast(0)
                            )
                        }
                    }
            ) {
                HorizontalPager(
                    state = pager,
                    key = { page -> assetAt(page)?.id ?: "placeholder:$page" },
                    beyondViewportPageCount = 1,
                    pageSpacing = 16.dp,
                    userScrollEnabled = chrome.pagingEnabled,
                    modifier = Modifier.fillMaxSize().testTag(ViewerTestTags.Pager)
                ) { page ->
                    val asset = assetAt(page)
                    when {
                        asset == null -> Box(Modifier.fillMaxSize())

                        MediaFormat.isVideo(asset) -> VideoPage(
                            player = player(),
                            active = page == pager.settledPage,
                            aspect = aspectOf(asset),
                            controlsVisible = chrome.chromeVisible,
                            onTap = { dispatch(ViewerIntent.Tap) },
                            poster = { SharedPoster(asset, animatedScope, shared = page == pager.currentPage) },
                            modifier = Modifier.testTag(ViewerTestTags.page(asset.id))
                        )

                        else -> PhotoPage(
                            asset = asset,
                            animatedScope = animatedScope,
                            sharedActive = page == pager.currentPage,
                            contentDescription = tileDescription(asset, MediaFormat.dayOf(asset), selected = false),
                            onTap = { dispatch(ViewerIntent.Tap) },
                            onZoomChanged = { zoomed -> if (page == pager.currentPage) dispatch(ViewerIntent.Zoom(zoomed)) },
                            onSignals = { signals -> if (page == pager.settledPage) offlineNotice = signals.offline }
                        )
                    }
                }
            }
            if (wide && viewerSheet == ViewerSheet.Info && current != null) {
                Column(
                    Modifier
                        .width(360.dp)
                        .fillMaxHeight()
                        .background(c.raised)
                        .windowInsetsPadding(WindowInsets.safeDrawing)
                        .verticalScroll(rememberScrollState())
                        .padding(16.dp)
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            stringResource(StringsR.string.viewer_info),
                            color = c.ink,
                            style = BentoTheme.typography.sectionTitle,
                            modifier = Modifier.weight(1f)
                        )
                        BentoIconButton(BentoIcons.X, stringResource(StringsR.string.common_action_close), { viewerSheet = null })
                    }
                    ViewerInfoContent(current, info, infoCallbacks(navigation, { viewerSheet = ViewerSheet.Rename }))
                }
            }
        }

        val showChrome = chrome.chromeVisible && chrome.dismissProgress == 0f
        // With the side pane open, the chrome stays over the photo column.
        val paneWidth = if (wide && viewerSheet == ViewerSheet.Info && current != null) 360.dp else 0.dp
        AnimatedVisibility(
            showChrome,
            enter = BentoTheme.motion.fadeIn,
            exit = BentoTheme.motion.fadeOut,
            modifier = Modifier.align(Alignment.TopStart).padding(end = paneWidth)
        ) {
            TopChrome(current, onBack = navigation.back)
        }
        Column(Modifier.align(Alignment.BottomStart).padding(end = paneWidth).fillMaxWidth()) {
            if (offlineNotice && current != null) {
                Callout(
                    tone = CalloutTone.Warning,
                    title = stringResource(StringsR.string.viewer_offline_title),
                    body = stringResource(StringsR.string.viewer_offline_hint),
                    icon = BentoIcons.CloudOff,
                    modifier = Modifier.padding(16.dp).testTag(ViewerTestTags.Offline)
                )
            }
            BentoSnackbarHost(snackbar, Modifier.fillMaxWidth())
            if (busy) {
                ProgressBar(
                    null,
                    Modifier.fillMaxWidth().padding(horizontal = 16.dp),
                    label = stringResource(StringsR.string.photos_preparing_copy)
                )
            }
            AnimatedVisibility(
                showChrome && current != null && actions != null,
                enter = BentoTheme.motion.fadeIn,
                exit = BentoTheme.motion.fadeOut
            ) {
                if (current != null && actions != null) {
                    BottomActions(
                        asset = current,
                        pinned = info?.takeIf { it.assetId == current.id }?.pinned,
                        actions = actions,
                        onSheet = { mediaSheet = it },
                        onRename = { viewerSheet = ViewerSheet.Rename },
                        onDetails = {
                            dispatch(ViewerIntent.SwipeUp)
                            viewerSheet = ViewerSheet.Info
                        },
                        onSpeed = { viewerSheet = ViewerSheet.Speed },
                        onOffline = onOffline
                    )
                }
            }
        }
    }

    BackHandler(enabled = viewerSheet != null) { viewerSheet = null }
    val sheetAsset = current
    when (viewerSheet) {
        ViewerSheet.Info -> if (!isWide() && sheetAsset != null) {
            ViewerInfoSheet(sheetAsset, info, infoCallbacks(navigation, { viewerSheet = ViewerSheet.Rename })) {
                viewerSheet = null
                dispatch(ViewerIntent.CloseInfo)
            }
        }

        ViewerSheet.Rename -> if (sheetAsset != null && actions != null) {
            RenameSheet(sheetAsset.filename, onSave = { name ->
                actions.rename(sheetAsset, name)
                viewerSheet = null
            }, onDismiss = { viewerSheet = null })
        }

        ViewerSheet.Speed -> SpeedSheet(speed, onSelect = {
            speed = it
            player()?.setPlaybackSpeed(it)
            viewerSheet = null
        }, onDismiss = { viewerSheet = null })

        null -> Unit
    }
    if (actions != null) MediaSheetHost(mediaSheet, actions, onClose = { mediaSheet = null })
}

@Composable
private fun isWide(): Boolean = LocalConfiguration.current.screenWidthDp >= 600

@Composable
private fun infoCallbacks(navigation: ViewerNavigation, onRename: () -> Unit): InfoCallbacks {
    val context = LocalContext.current
    return InfoCallbacks(
        onRename = onRename,
        onOpenFolder = navigation.openFolder,
        onOpenMaps = { lat, lng ->
            val uri = Uri.parse("geo:$lat,$lng?q=$lat,$lng")
            runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, uri).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
        },
        onOpenActivity = navigation.openActivity
    )
}

@Composable
private fun TopChrome(asset: AssetResponse?, onBack: () -> Unit) {
    val c = BentoTheme.colors
    val locale = LocalConfiguration.current.locales[0]
    Row(
        Modifier
            .fillMaxWidth()
            .background(c.black.copy(alpha = 0.35f))
            .windowInsetsPadding(WindowInsets.statusBars)
            .heightIn(min = 56.dp)
            .padding(horizontal = 4.dp)
            .testTag(ViewerTestTags.Chrome),
        verticalAlignment = Alignment.CenterVertically
    ) {
        BentoIconButton(BentoIcons.ArrowLeft, stringResource(StringsR.string.viewer_close), onBack, tint = c.white)
        if (asset != null) {
            Column(Modifier.padding(start = 4.dp)) {
                Text(MediaFormat.longDate(MediaFormat.dayOf(asset), locale), color = c.white, style = BentoTheme.typography.labelStrong)
                Text(asset.filename, color = c.white.copy(alpha = 0.8f), style = BentoTheme.typography.metadata, maxLines = 1)
            }
        }
    }
}

/** Compartir · Favorito · Añadir a álbum · Eliminar · overflow (product/android.md §4.4). */
@Suppress("LongMethod", "LongParameterList")
@Composable
private fun BottomActions(
    asset: AssetResponse,
    pinned: Boolean?,
    actions: MediaActions,
    onSheet: (MediaSheet) -> Unit,
    onRename: () -> Unit,
    onDetails: () -> Unit,
    onSpeed: () -> Unit,
    onOffline: (AssetResponse, Boolean) -> Unit
) {
    val c = BentoTheme.colors
    var menu by remember { mutableStateOf(false) }
    val isVideo = MediaFormat.isVideo(asset)
    Row(
        Modifier
            .fillMaxWidth()
            .background(c.black.copy(alpha = 0.35f))
            .windowInsetsPadding(WindowInsets.navigationBars)
            .heightIn(min = 64.dp)
            .padding(horizontal = 8.dp)
            .testTag(ViewerTestTags.Actions),
        horizontalArrangement = Arrangement.SpaceEvenly,
        verticalAlignment = Alignment.CenterVertically
    ) {
        BentoIconButton(BentoIcons.Share2, stringResource(StringsR.string.common_action_share), {
            actions.export(Disclosure.Share) { actions.share(listOf(asset)) }
        }, tint = c.white)
        BentoFavoriteButton(asset.favorite, { actions.favorite(listOf(asset), it) }, onMedia = true)
        BentoIconButton(BentoIcons.SquareLibrary, stringResource(StringsR.string.common_action_add_to_album), {
            onSheet(MediaSheet.AddToAlbum(listOf(asset.id)))
        }, tint = c.white)
        BentoIconButton(BentoIcons.Trash2, stringResource(StringsR.string.common_action_delete), {
            actions.trash(listOf(asset.id))
        }, tint = c.white)
        Box {
            BentoIconButton(BentoIcons.EllipsisVertical, stringResource(StringsR.string.ds_more_options), { menu = true }, tint = c.white)
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }, shape = BentoShapes.lg, containerColor = c.raised) {
                @Composable
                fun item(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, onClick: () -> Unit) = DropdownMenuItem(
                    text = { Text(label, color = c.ink, style = BentoTheme.typography.body) },
                    leadingIcon = { BentoIcon(icon, null, tint = c.ink) },
                    onClick = {
                        menu = false
                        onClick()
                    },
                    modifier = Modifier.heightIn(min = 48.dp).semantics { contentDescription = label }
                )
                item(BentoIcons.Send, stringResource(StringsR.string.common_action_send_telegram)) {
                    onSheet(MediaSheet.Telegram(listOf(asset)))
                }
                item(BentoIcons.Download, stringResource(StringsR.string.common_action_save_to_phone)) {
                    actions.export(Disclosure.SaveToPhone) { actions.saveToPhone(listOf(asset)) }
                }
                item(BentoIcons.FolderInput, stringResource(StringsR.string.photos_action_move_to_folder)) {
                    onSheet(MediaSheet.Move(listOf(asset)))
                }
                item(BentoIcons.PencilLine, stringResource(StringsR.string.common_action_rename), onRename)
                item(BentoIcons.ExternalLink, stringResource(StringsR.string.common_action_open_with)) {
                    actions.export(Disclosure.OpenWith) { actions.openWith(asset) }
                }
                if (!isVideo) {
                    item(BentoIcons.ImageUp, stringResource(StringsR.string.viewer_action_use_as)) {
                        actions.export(Disclosure.OpenWith) { actions.useAs(asset) }
                    }
                }
                item(
                    BentoIcons.CloudOff,
                    stringResource(if (pinned == true) StringsR.string.viewer_action_offline_off else StringsR.string.viewer_action_offline)
                ) { onOffline(asset, pinned != true) }
                if (isVideo) item(BentoIcons.Gauge, stringResource(StringsR.string.viewer_action_speed), onSpeed)
                item(BentoIcons.Info, stringResource(StringsR.string.viewer_action_details), onDetails)
            }
        }
    }
}

/** Hides the system bars with the chrome (swipe from an edge shows them transiently); restores them on exit. */
@Composable
private fun SystemBarsForViewer(visible: Boolean) {
    val activity = LocalActivity.current ?: return
    val view = LocalView.current
    val controller = remember(activity, view) { WindowCompat.getInsetsController(activity.window, view) }
    DisposableEffect(controller) {
        val lightStatus = controller.isAppearanceLightStatusBars
        val lightNav = controller.isAppearanceLightNavigationBars
        controller.isAppearanceLightStatusBars = false
        controller.isAppearanceLightNavigationBars = false
        onDispose {
            controller.show(WindowInsetsCompat.Type.systemBars())
            controller.isAppearanceLightStatusBars = lightStatus
            controller.isAppearanceLightNavigationBars = lightNav
        }
    }
    LaunchedEffect(visible) {
        if (visible) {
            controller.show(WindowInsetsCompat.Type.systemBars())
        } else {
            controller.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            controller.hide(WindowInsetsCompat.Type.systemBars())
        }
    }
}

/**
 * Swipe down (dismiss) / up (info) at fit zoom. Runs in the Initial pass and claims the gesture only once it is clearly
 * vertical, so Telephoto (which handles pans in the Main pass) and the pager keep horizontal and zoomed gestures.
 */
@Suppress("CyclomaticComplexMethod", "LoopWithTooManyJumpStatements")
private fun Modifier.verticalSwipe(enabled: Boolean, onDrag: (Float) -> Unit, onEnd: (velocityY: Float) -> Unit): Modifier =
    if (!enabled) {
        this
    } else {
        pointerInput(Unit) {
            awaitEachGesture {
                val down = awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
                val slop = viewConfiguration.touchSlop
                val tracker = VelocityTracker()
                tracker.addPosition(down.uptimeMillis, down.position)
                var claimed = false
                while (true) {
                    val event = awaitPointerEvent(PointerEventPass.Initial)
                    if (event.changes.size > 1) return@awaitEachGesture
                    val change = event.changes.firstOrNull { it.id == down.id } ?: return@awaitEachGesture
                    tracker.addPosition(change.uptimeMillis, change.position)
                    if (!change.pressed) {
                        if (claimed) onEnd(tracker.calculateVelocity().y)
                        return@awaitEachGesture
                    }
                    val total = change.position - down.position
                    if (!claimed) {
                        if (kotlin.math.abs(total.x) > slop) return@awaitEachGesture
                        val vertical = kotlin.math.abs(total.y) > slop && kotlin.math.abs(total.y) > 2 * kotlin.math.abs(total.x)
                        if (vertical) claimed = true else continue
                    }
                    val delta = change.position.y - change.previousPosition.y
                    change.consume()
                    onDrag(delta)
                }
            }
        }
    }
