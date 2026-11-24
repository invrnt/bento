package dev.bento.feature.files

import dev.bento.api.BentoJson
import dev.bento.api.generated.BentoInterfacesHttpRoutesAndroidImportRequest
import dev.bento.api.generated.EnsureFolderRequest
import dev.bento.data.DriveRepository
import dev.bento.data.Invalidations
import dev.bento.data.UiCache
import dev.bento.testing.FakeApiTransport
import java.nio.file.Files
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class FolderTreeImportTest {
    private val tmp = Files.createTempDirectory("tree").toFile()

    private class FakeTree : TreeReader {
        val nodes = mapOf<String?, List<TreeNode>>(
            null to listOf(
                TreeNode("doc:1", "factura.pdf", "application/pdf", 10, false),
                TreeNode("doc:dir", "../2024", null, null, true),
                TreeNode("doc:slash", "a/b", null, null, true)
            ),
            "doc:dir" to listOf(TreeNode("doc:2", "..\\escape.jpg", "image/jpeg", 20, false)),
            "doc:slash" to emptyList()
        )

        override fun rootName(treeUri: String) = "Escritorio/Viejo"

        override fun children(treeUri: String, documentUri: String?) = nodes[documentUri].orEmpty()
    }

    @Test
    fun recreatesTheTreeWithSanitizedSegments() = runTest {
        val ensured = mutableListOf<String>()
        val api = FakeApiTransport().apply {
            on("POST /api/drive/paths") { """{"paths":{"f_cur":"/Trabajo"},"missing":[]}""" }
            on("POST /api/drive/folders/ensure") { call ->
                val path = BentoJson.decodeFromString(EnsureFolderRequest.serializer(), call.body!!).path
                ensured += path
                """{"folder":${FilesFixtures.folderResponse("id:$path", path.substringAfterLast('/'))},"path":"$path","created":[]}"""
            }
            on("POST /api/android/imports") { """{"import_id":"imp","done":true,"counts":{},"items":[]}""" }
            on("GET /api/android/imports/imp") { """{"import_id":"imp","done":true,"counts":{},"items":[]}""" }
        }
        val endpoints = api.endpoints()
        val invalidations = Invalidations()
        val repo =
            FilesRepository(
                endpoints,
                null,
                DriveRepository(endpoints, invalidations, UiCache(tmp, "1"), backgroundScope),
                invalidations,
                UiCache(tmp, "1")
            )
        val handles = object : ContentHandles {
            var next = 1L

            override fun register(uri: String) = ContentHandles.Registered(next++, "n", "application/octet-stream", 1)
        }
        val uploads = UploadCoordinator(
            endpoints,
            handles,
            object : TransferControl {
                override fun start(estimatedBytes: Long) = Unit

                override fun stop() = Unit
            },
            ImportFailureLog(tmp),
            invalidations,
            backgroundScope,
            pollMs = 5
        )
        val result = FolderTreeImport(FakeTree(), repo, uploads).run("tree:1", "f_cur")
        settle()
        assertTrue(ensured.containsAll(listOf("/Trabajo/Escritorio_Viejo", "/Trabajo/Escritorio_Viejo/_2024")))
        assertTrue(ensured.none { it.contains("..") })
        assertEquals(2, result.files)
        val imports = api.calls.filter { it.method == "POST" && it.path == "/api/android/imports" }
            .map { BentoJson.decodeFromString(BentoInterfacesHttpRoutesAndroidImportRequest.serializer(), it.body!!) }
        assertEquals(setOf("id:/Trabajo/Escritorio_Viejo", "id:/Trabajo/Escritorio_Viejo/_2024"), imports.map { it.folderId }.toSet())
        assertEquals(setOf("factura.pdf", "escape.jpg"), imports.flatMap { it.items }.map { it.displayName }.toSet())
    }

    @Test
    fun planIsBounded() {
        val wide = object : TreeReader {
            override fun rootName(treeUri: String) = "R"

            override fun children(treeUri: String, documentUri: String?) =
                (1..10).map { TreeNode("d:$documentUri:$it", "f$it", null, 1, false) } +
                    TreeNode("dir:${documentUri.orEmpty()}x", "sub", null, null, true)
        }
        val tmpRepo =
            FilesRepository(
                FakeApiTransport().endpoints(),
                null,
                DriveRepository(FakeApiTransport().endpoints(), Invalidations(), UiCache(tmp, "1"), kotlinx.coroutines.GlobalScope),
                Invalidations(),
                UiCache(tmp, "1")
            )
        val importer = FolderTreeImport(
            wide,
            tmpRepo,
            UploadCoordinator(
                FakeApiTransport().endpoints(),
                object : ContentHandles {
                    override fun register(uri: String) = ContentHandles.Registered(1, "n", "x", 1)
                },
                object : TransferControl {
                    override fun start(estimatedBytes: Long) = Unit

                    override fun stop() = Unit
                },
                ImportFailureLog(tmp),
                Invalidations(),
                kotlinx.coroutines.GlobalScope
            ),
            maxFiles = 25,
            maxDepth = 3
        )
        val (files, truncated) = importer.plan("t")
        assertEquals(25, files.size)
        assertTrue(truncated)
        assertTrue(files.all { it.segments.size <= 3 })
    }
}
