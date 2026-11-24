package dev.bento.feature.files

import dev.bento.data.DriveRepository
import dev.bento.data.Invalidations
import dev.bento.data.UiCache
import dev.bento.testing.FakeApiTransport
import dev.bento.testing.MainDispatcherRule
import java.nio.file.Files
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class FilesViewModelTest {
    @get:Rule
    val main = MainDispatcherRule()

    private val tmp = Files.createTempDirectory("files").toFile()
    private val preferences = InMemoryFilesPreferences()
    private var online = true

    class FakeAudio : AudioControls {
        private val _state = MutableStateFlow(AudioState())
        override val state: StateFlow<AudioState> = _state
        var played: String? = null

        override fun play(assetId: String, title: String) {
            played = assetId
            _state.value = AudioState(assetId, title, playing = true)
        }

        override fun toggle() = Unit

        override fun seekTo(positionMs: Long) = Unit

        override fun tick() = Unit

        override fun close() {
            _state.value = AudioState()
        }
    }

    private val audio = FakeAudio()

    private val api = FakeApiTransport().apply {
        on("GET /api/drive/items") { call ->
            when (call.query["folder_id"]) {
                null -> FilesFixtures.items(*FilesFixtureJson.root.toTypedArray())

                "f_work" -> FilesFixtures.items(
                    FilesFixtures.file("a_in", "Contrato.pdf", folderId = "f_work"),
                    crumbs = listOf("f_work" to "Trabajo")
                )

                else -> FilesFixtures.items()
            }
        }
    }

    private object FilesFixtureJson {
        val root = listOf(
            FilesFixtures.file("a_b", "b.pdf", size = 10),
            FilesFixtures.folder("f_work", "Trabajo"),
            FilesFixtures.file("a_a", "a.zip", mime = "application/zip", size = 99),
            FilesFixtures.file("a_t", "notas.txt", mime = "text/plain", size = 30),
            FilesFixtures.file("a_s", "voz.m4a", mime = "audio/mp4", size = 40),
            FilesFixtures.file("a_i", "foto.jpg", mime = "image/jpeg", size = 50)
        )
    }

    private fun TestScope.vm(): FilesViewModel {
        val endpoints = api.endpoints()
        val invalidations = Invalidations()
        val cache = UiCache(tmp, "1")
        val repo = FilesRepository(endpoints, null, DriveRepository(endpoints, invalidations, cache, backgroundScope), invalidations, cache)
        val uploads = UploadCoordinator(
            endpoints,
            object : ContentHandles {
                override fun register(uri: String) = ContentHandles.Registered(1, "n", "x", 1)
            },
            object : TransferControl {
                override fun start(estimatedBytes: Long) = Unit

                override fun stop() = Unit
            },
            ImportFailureLog(tmp),
            invalidations,
            backgroundScope
        )
        val content =
            ContentFiles(dev.bento.api.BentoHttp(okhttp3.OkHttpClient(), { throw dev.bento.api.ApiException.EngineUnavailable() }), tmp)
        return FilesViewModel(
            repo,
            preferences,
            content,
            uploads,
            audio,
            { online },
            invalidations,
            object : TreeReader {
                override fun rootName(treeUri: String) = "r"

                override fun children(treeUri: String, documentUri: String?) = emptyList<TreeNode>()
            }
        )
    }

    @Test
    fun listsFoldersFirstAndRemembersSortPerFolder() = runTest(main.dispatcher) {
        val vm = vm()
        vm.start(null)
        settle()
        assertEquals(listOf("f_work", "a_a", "a_b", "a_i", "a_t", "a_s"), vm.state.value.items.map { it.id })
        vm.setSort(FolderSort(SortField.Size, descending = true))
        assertEquals("a_a", vm.state.value.items[1].id)
        vm.navigateTo("f_work")
        settle()
        assertEquals(FolderSort(), vm.state.value.sort)
        assertEquals("Trabajo", vm.state.value.folderName)
        assertTrue(vm.up())
        settle()
        assertEquals(FolderSort(SortField.Size, true), vm.state.value.sort)
        assertFalse(vm.up())
    }

    @Test
    fun opensEachKindTheRightWay() = runTest(main.dispatcher) {
        val vm = vm()
        vm.start(null)
        settle()
        val items = vm.state.value.items.associateBy { it.id }
        val effects = mutableListOf<FilesEffect>()
        val collector = backgroundScope.launchCollect(vm, effects)
        vm.open(items.getValue("a_i"))
        vm.open(items.getValue("a_b"))
        vm.open(items.getValue("a_t"))
        vm.open(items.getValue("a_s"))
        settle()
        assertEquals(
            listOf(FilesEffect.OpenViewer("a_i"), FilesEffect.OpenDocument("a_b"), FilesEffect.OpenDocument("a_t")),
            effects.take(3)
        )
        assertEquals("a_s", audio.played)
        // Other types go through the plaintext disclosure first.
        vm.open(items.getValue("a_a"))
        assertTrue(vm.state.value.sheet is FilesSheet.Disclosure)
        vm.open(items.getValue("f_work"))
        settle()
        assertEquals("f_work", vm.state.value.folderId)
        collector.cancel()
    }

    @Test
    fun offlineOpensOnlyPinnedFiles() = runTest(main.dispatcher) {
        val vm = vm()
        vm.start(null)
        settle()
        val pdf = vm.state.value.items.first { it.id == "a_b" }
        online = false
        vm.open(pdf)
        assertEquals(FilesSheet.OfflineUnavailable(pdf), vm.state.value.sheet)
        vm.dismissSheet()
        preferences.setPinned("a_b", true)
        settle()
        val effects = mutableListOf<FilesEffect>()
        val collector = backgroundScope.launchCollect(vm, effects)
        vm.open(pdf)
        settle()
        assertNull(vm.state.value.sheet)
        assertEquals(listOf(FilesEffect.OpenDocument("a_b")), effects)
        // Images open from thumbnails/previews already on the phone (the viewer handles its own offline state).
        vm.open(vm.state.value.items.first { it.id == "a_i" })
        settle()
        assertEquals(FilesEffect.OpenViewer("a_i"), effects.last())
        collector.cancel()
    }

    @Test
    fun pinCallsTheApiAndRollsBackOnFailure() = runTest(main.dispatcher) {
        api.on("PUT /api/assets/a_b/offline") { """{"asset_id":"a_b","pinned":true,"downloading":true}""" }
        val vm = vm()
        vm.start(null)
        settle()
        val pdf = vm.state.value.items.first { it.id == "a_b" }
        vm.setPinned(pdf, true)
        settle()
        assertEquals(setOf("a_b"), vm.state.value.pinned)
        api.fail("DELETE /api/assets/a_b/offline", 503, "unavailable")
        vm.setPinned(pdf, false)
        settle()
        assertEquals(setOf("a_b"), preferences.pinned.value)
    }

    @Test
    fun trashHidesAtOnceAndUndoRestores() = runTest(main.dispatcher) {
        api.on("DELETE /api/assets/a_b") { FilesFixtures.asset("a_b", "b.pdf") }
        api.on("POST /api/trash/restore") { "{}" }
        val vm = vm()
        vm.start(null)
        settle()
        val effects = mutableListOf<FilesEffect>()
        val collector = backgroundScope.launchCollect(vm, effects)
        vm.trash(listOf(vm.state.value.items.first { it.id == "a_b" }))
        assertTrue(vm.state.value.items.none { it.id == "a_b" })
        settle()
        val message = (effects.last() as FilesEffect.Message).message
        assertTrue(message.undo != null)
        message.undo!!.undo()
        settle()
        assertEquals(1, api.count("POST /api/trash/restore"))
        assertTrue(vm.state.value.items.any { it.id == "a_b" })
        collector.cancel()
    }

    @Test
    fun moveRefusesCyclesAndRemembersDestination() = runTest(main.dispatcher) {
        api.on("POST /api/drive/items/a_b/move") { FilesFixtures.asset("a_b", "b.pdf", folderId = "f_work") }
        val vm = vm()
        vm.start(null)
        settle()
        val work = vm.state.value.items.first { it.id == "f_work" }
        vm.moveTo(listOf(work), Destination("f_work", "Trabajo"))
        assertTrue(vm.state.value.items.any { it.id == "f_work" })
        vm.moveTo(listOf(vm.state.value.items.first { it.id == "a_b" }), Destination("f_work", "Trabajo"))
        settle()
        assertEquals(1, api.count("POST /api/drive/items/a_b/move"))
        assertEquals(Destination("f_work", "Trabajo"), preferences.recentDestinations.value.first())
    }

    @Test
    fun newFolderValidatesAndReportsConflicts() = runTest(main.dispatcher) {
        api.fail("POST /api/drive/folders", 409, "folder_exists")
        val vm = vm()
        vm.start(null)
        settle()
        vm.showSheet(FilesSheet.NewFolder)
        vm.createFolder("   ")
        assertEquals(UiText.of(dev.bento.strings.R.string.files_new_folder_empty), vm.state.value.newFolderError)
        vm.createFolder("Trabajo")
        settle()
        assertEquals(UiText.of(dev.bento.strings.R.string.files_new_folder_exists), vm.state.value.newFolderError)
        assertEquals(FilesSheet.NewFolder, vm.state.value.sheet)
        api.on("POST /api/drive/folders") { FilesFixtures.folderResponse("f_new", "Facturas") }
        vm.createFolder("Facturas/2026")
        settle()
        assertTrue(api.calls.last { it.path == "/api/drive/folders" }.body!!.contains("Facturas_2026"))
        assertNull(vm.state.value.sheet)
    }

    @Test
    fun selectionAndDisclosureSkip() = runTest(main.dispatcher) {
        val vm = vm()
        vm.start(null)
        settle()
        val zip = vm.state.value.items.first { it.id == "a_a" }
        vm.toggleSelection(zip)
        assertTrue(vm.state.value.selecting)
        vm.open(vm.state.value.items.first { it.id == "a_b" })
        assertEquals(setOf("a_a", "a_b"), vm.state.value.selection)
        vm.selectAll()
        assertEquals(vm.state.value.items.size, vm.state.value.selection.size)
        vm.clearSelection()
        vm.openWith(zip)
        vm.confirmDisclosure(dontShowAgain = true)
        assertTrue(preferences.skipsDisclosure(Disclosure.OpenWith))
        vm.cancelPreparing()
        vm.openWith(zip)
        assertNull(vm.state.value.sheet)
    }

    @Test
    fun loadFailureOfflineKeepsCachedItems() = runTest(main.dispatcher) {
        val vm = vm()
        vm.start(null)
        settle()
        api.fail("GET /api/drive/items", 503, "unavailable")
        online = false
        vm.load()
        settle()
        assertTrue(vm.state.value.offline)
        assertFalse(vm.state.value.loadFailed)
        assertTrue(vm.state.value.items.isNotEmpty())
    }
}

private fun kotlinx.coroutines.CoroutineScope.launchCollect(vm: FilesViewModel, into: MutableList<FilesEffect>) =
    launch { vm.effect.collect { into += it } }
