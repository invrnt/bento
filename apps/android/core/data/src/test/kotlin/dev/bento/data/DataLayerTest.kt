package dev.bento.data

import androidx.paging.PagingSource
import androidx.paging.testing.asSnapshot
import dev.bento.api.ApiException
import dev.bento.api.generated.AssetResponse
import dev.bento.testing.FakeApiTransport
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

private fun asset(id: String, favorite: Boolean = false) = """{"id":"$id","filename":"$id.jpg","kind":"photo","mime_type":"image/jpeg",
    "mode":"photos","processing_state":"ready","sha256":"x","size_bytes":10,"created_at":"2024-03-01T00:00:00Z","favorite":$favorite,
    "folder_id":null,"preview_url":null,"thumbnail_url":null,"taken_at":null,"updated_at":"2024-03-01T00:00:00Z"}""".replace("\n", "")

private fun timelinePage(groups: List<Pair<String, List<String>>>, next: String?) =
    """{"groups":[${groups.joinToString(",") { (date, ids) ->
        """{"date":"$date","assets":[${ids.joinToString(",") { asset(it) }}]}"""
    }}],""" +
        """"next_cursor":${next?.let { "\"$it\"" } ?: "null"}}"""

class CursorPagingSourceTest {
    @Test
    fun `pages follow next_cursor and stop at null`() = runTest {
        val source = CursorPagingSource { cursor, _ ->
            if (cursor == null) CursorPage(listOf(1, 2), "c2") else CursorPage(listOf(3), null)
        }
        val first = source.load(PagingSource.LoadParams.Refresh(null, 2, false)) as PagingSource.LoadResult.Page
        assertEquals(listOf(1, 2), first.data)
        assertEquals("c2", first.nextKey)
        val second = source.load(PagingSource.LoadParams.Append("c2", 2, false)) as PagingSource.LoadResult.Page
        assertNull(second.nextKey)
    }

    @Test
    fun `a repeated cursor ends paging instead of looping`() = runTest {
        val source = CursorPagingSource<Int> { _, _ -> CursorPage(listOf(1), "same") }
        val page = source.load(PagingSource.LoadParams.Append("same", 2, false)) as PagingSource.LoadResult.Page
        assertNull(page.nextKey)
    }

    @Test
    fun `api errors become LoadResult Error`() = runTest {
        val source = CursorPagingSource<Int> { _, _ -> throw ApiException.EngineUnavailable() }
        assertTrue(source.load(PagingSource.LoadParams.Refresh(null, 2, false)) is PagingSource.LoadResult.Error)
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class TimelineRepositoryTest {
    @get:Rule
    val temp = TemporaryFolder()

    private val transport = FakeApiTransport()

    private fun repository(scope: kotlinx.coroutines.CoroutineScope, cache: UiCache = UiCache(temp.root, "1")) =
        TimelineRepository(transport.endpoints(), Invalidations(), cache, scope)

    @Test
    fun `timeline flattens groups with one day header per date across pages`() = runTest {
        transport.on("GET /api/photos/timeline") { call ->
            if (call.query["cursor"] == null) {
                timelinePage(listOf("2024-03-02" to listOf("a", "b")), "c2")
            } else {
                timelinePage(listOf("2024-03-02" to listOf("c"), "2024-03-01" to listOf("d")), null)
            }
        }
        val keys = repository(backgroundScope).timeline(pageSize = 2).asSnapshot { scrollTo(10) }.map { it.key }
        assertEquals(listOf("day:2024-03-02", "asset:a", "asset:b", "asset:c", "day:2024-03-01", "asset:d"), keys)
    }

    @Test
    fun `first page is written to the UI cache`() = runTest {
        transport.on("GET /api/photos/timeline") { timelinePage(listOf("2024-03-02" to listOf("a", "b")), null) }
        val cache = UiCache(temp.root, "1")
        val repo = repository(backgroundScope, cache)
        repo.timeline().asSnapshot()
        assertEquals(listOf("a", "b"), repo.cachedFirstScreen()!!.map(AssetResponse::id))
    }

    @Test
    fun `trash hides the item immediately and undo restores it`() = runTest {
        transport.on("GET /api/photos/timeline") { timelinePage(listOf("2024-03-02" to listOf("a", "b")), null) }
        transport.on("DELETE /api/assets/a") { asset("a") }
        transport.on("POST /api/trash/restore") { "{}" }
        val repo = repository(backgroundScope)
        val undo = repo.trash("a")
        assertEquals(listOf("day:2024-03-02", "asset:b"), repo.timeline().asSnapshot().map { it.key })
        undo.undo()
        undo.undo()
        assertEquals(1, transport.count("POST /api/trash/restore"))
        assertTrue(transport.calls.last { it.path == "/api/trash/restore" }.body!!.contains("\"a\""))
    }

    @Test
    fun `favorite failure rolls back and rethrows`() = runTest {
        transport.on("GET /api/photos/timeline") { timelinePage(listOf("2024-03-02" to listOf("a")), null) }
        transport.fail("POST /api/photos/a/favorite", 503, "storage_unavailable")
        val repo = repository(backgroundScope)
        val original = repo.timeline().asSnapshot().filterIsInstance<TimelineEntry.Photo>().single().asset
        try {
            repo.setFavorite(original, true)
            fail("expected ApiException")
        } catch (expected: ApiException.Http) {
            assertEquals("storage_unavailable", expected.code)
        }
        val after = repo.timeline().asSnapshot().filterIsInstance<TimelineEntry.Photo>().single().asset
        assertEquals(false, after.favorite)
    }

    @Test
    fun `month index comes from the timeline index endpoint`() = runTest {
        transport.on("GET /api/photos/timeline/index") {
            """{"months":[{"month":"2024-03","count":2,"first_cursor":"c1"},{"month":"2024-02","count":2,"first_cursor":"c2"}]}"""
        }
        val index = repository(backgroundScope).monthIndex()
        assertEquals(listOf(MonthIndexEntry("2024-03", 2, "c1"), MonthIndexEntry("2024-02", 2, "c2")), index)
    }
}

class UiCacheTest {
    @get:Rule
    val temp = TemporaryFolder()

    @Test
    fun `entries survive restarts for the same vault and schema`() {
        val cache = UiCache(temp.root, "1")
        cache.bindVault("v1")
        cache.write("fotos", listOf("a", "b"), String.serializer())
        assertEquals(listOf("a", "b"), UiCache(temp.root, "1").read("fotos", String.serializer()))
    }

    @Test
    fun `vault change, schema change and clear invalidate`() {
        val serializer = String.serializer()
        val cache = UiCache(temp.root, "1").apply { bindVault("v1") }
        cache.write("fotos", listOf("a"), serializer)
        assertNull(UiCache(temp.root, "2").read("fotos", serializer))
        cache.write("fotos", listOf("a"), serializer)
        cache.bindVault("v2")
        assertNull(cache.read("fotos", serializer))
        cache.write("archivos", listOf("x"), serializer)
        cache.clear()
        assertNull(cache.read("archivos", serializer))
    }

    @Test
    fun `at most 300 items and safe keys only`() {
        val serializer = Int.serializer()
        val cache = UiCache(temp.root, "1")
        cache.write("fotos", (1..1000).toList(), serializer)
        assertEquals(UiCache.MAX_ITEMS, cache.read("fotos", serializer)!!.size)
        try {
            cache.write("../escape", listOf(1), serializer)
            fail("expected rejection")
        } catch (expected: IllegalArgumentException) {
            // expected
        }
    }
}

class OptimisticTest {
    @Test
    fun `overlay replace, hide and clear`() {
        val overlay = OverlayStore<String>()
        overlay.replace("a", "A2")
        overlay.hide("b")
        assertEquals("A2", overlay.apply("a", "A"))
        assertTrue(overlay.isHidden("b"))
        overlay.clear("a")
        assertEquals("A", overlay.apply("a", "A"))
    }

    @Test
    fun `untyped pages parse items and cursor`() {
        val page = untypedPage(
            buildJsonObject {
                put("items", kotlinx.serialization.json.JsonArray(listOf(buildJsonObject { put("id", "t1") }, JsonPrimitive(3))))
                put("next_cursor", "n")
            }
        )
        assertEquals(1, page.items.size)
        assertEquals("n", page.nextCursor)
        assertEquals(0, untypedPage(JsonPrimitive(1)).items.size)
    }
}

class SessionRepositoryTest {
    @get:Rule
    val temp = TemporaryFolder()

    @Test
    fun `a different vault clears the UI cache`() = runTest {
        val transport = FakeApiTransport()
        var vault = "v1"
        transport.on("GET /api/vault") {
            """{"state":"ready","vault_id":"$vault","devices_count":1,"other_vaults":0,"recovery_kit_saved":true,"created_at":null,""" +
                """"usage":{"bytes":0,"files":0}}"""
        }
        val serializer = String.serializer()
        val cache = UiCache(temp.root, "1")
        val session = SessionRepository(transport.endpoints(), cache, Invalidations())
        session.vault()
        cache.write("fotos", listOf("a"), serializer)
        vault = "v2"
        session.vault()
        assertEquals("v2", session.vaultId.value)
        assertNull(cache.read("fotos", serializer))
    }
}
