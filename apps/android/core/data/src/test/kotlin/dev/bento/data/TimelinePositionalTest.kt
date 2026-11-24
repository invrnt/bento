package dev.bento.data

import androidx.paging.PagingSource
import dev.bento.api.generated.AssetResponse
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private fun photo(i: Int) = TimelineEntry.Photo(
    date = "2024-03-01",
    asset = AssetResponse(
        createdAt = "2024-03-01T00:00:00Z",
        favorite = i % 7 == 0,
        filename = "p$i.jpg",
        folderId = null,
        id = "p$i",
        kind = if (i % 5 == 0) "video" else "image",
        mimeType = "image/jpeg",
        mode = "photos",
        processingState = "ready",
        sha256 = "x",
        sizeBytes = 1,
        updatedAt = "2024-03-01T00:00:00Z"
    )
)

/** A fake keyset backend over [total] photos: cursor "c<n>" means "photos from position n". */
private class FakeTimeline(val total: Int) {
    val requests = mutableListOf<Pair<String?, Int>>()

    suspend fun page(cursor: String?, limit: Int): CursorPage<TimelineEntry.Photo> {
        requests += cursor to limit
        val start = cursor?.removePrefix("c")?.toInt() ?: 0
        val end = minOf(total, start + limit)
        return CursorPage((start until end).map(::photo), if (end < total) "c$end" else null)
    }
}

class TimelineLayoutTest {
    private val layout = TimelineLayout(
        listOf(MonthIndexEntry("2024-03", 10, "c0"), MonthIndexEntry("2024-02", 0, "c10"), MonthIndexEntry("2023-12", 5, "c10"))
    )

    @Test
    fun `starts are cumulative counts and monthAt is a binary search`() {
        assertEquals(listOf(0, 10, 10), layout.starts.toList())
        assertEquals(15, layout.total)
        assertEquals(0, layout.monthAt(0))
        assertEquals(0, layout.monthAt(9))
        assertEquals(2, layout.monthAt(10))
        assertEquals(2, layout.monthAt(999))
        assertEquals(-1, TimelineLayout.EMPTY.monthAt(0))
    }
}

class TimelinePositionalSourceTest {
    private val backend = FakeTimeline(1_000)
    private val months = listOf(MonthIndexEntry("2024-03", 400, "c0"), MonthIndexEntry("2024-02", 600, "c400"))
    private val jumps = AtomicReference<Int?>(null)
    private var published: TimelineLayout? = null
    private val source = TimelinePositionalSource(backend::page, { months }, { published = it }, jumps)

    @Test
    fun `refresh reports placeholders for the whole library`() = runTest {
        val page = source.load(PagingSource.LoadParams.Refresh(null, 120, true)) as PagingSource.LoadResult.Page
        assertEquals(120, page.data.size)
        assertEquals(0, page.itemsBefore)
        assertEquals(880, page.itemsAfter)
        assertEquals(120, page.nextKey)
        assertNull(page.prevKey)
        assertEquals(1_000, published?.total)
    }

    @Test
    fun `a jump into a month starts at its cursor instead of walking every page`() = runTest {
        val page = source.load(PagingSource.LoadParams.Refresh(450, 120, true)) as PagingSource.LoadResult.Page
        assertEquals("p450", page.data.first().asset.id)
        assertEquals(450, page.itemsBefore)
        // one request to skip 50 inside February (from c400), one for the page
        assertEquals(listOf("c400" to 50, "c450" to 120), backend.requests)
    }

    @Test
    fun `prepend after a jump reuses the cursors it learned`() = runTest {
        source.load(PagingSource.LoadParams.Refresh(450, 120, true))
        backend.requests.clear()
        val before = source.load(PagingSource.LoadParams.Prepend(450, 30, true)) as PagingSource.LoadResult.Page
        assertEquals((420 until 450).map { "p$it" }, before.data.map { it.asset.id })
        assertEquals("starts from the February cursor", "c400", backend.requests.first().first)
    }

    @Test
    fun `the refresh key prefers an explicit jump`() = runTest {
        jumps.set(777)
        assertEquals(777, source.getRefreshKey(androidx.paging.PagingState(emptyList(), 12, androidx.paging.PagingConfig(10), 0)))
        assertEquals(12, source.getRefreshKey(androidx.paging.PagingState(emptyList(), 12, androidx.paging.PagingConfig(10), 0)))
    }

    @Test
    fun `the end of data clears trailing placeholders even when the index was stale`() = runTest {
        val small = FakeTimeline(50)
        val stale = TimelinePositionalSource(small::page, { listOf(MonthIndexEntry("2024-03", 80, "c0")) }, {}, jumps)
        val page = stale.load(PagingSource.LoadParams.Refresh(null, 120, true)) as PagingSource.LoadResult.Page
        assertEquals(50, page.data.size)
        assertEquals(0, page.itemsAfter)
        assertNull(page.nextKey)
    }
}

class FilteredTimelineSourceTest {
    @Test
    fun `sparse filters keep scanning until enough matches`() = runTest {
        val backend = FakeTimeline(1_000)
        val source = FilteredTimelineSource(backend::page, { it.asset.favorite }, minMatches = 30, maxScan = 2_000)
        val page = source.load(PagingSource.LoadParams.Refresh(null, 60, false)) as PagingSource.LoadResult.Page
        assertTrue(page.data.size >= 30)
        assertTrue(page.data.all { it.asset.favorite })
        assertEquals("c400", page.nextKey)
    }
}

class CollectionsParsingTest {
    @Test
    fun `phone folders come from backup sources`() {
        val json = buildJsonObject {
            put(
                "items",
                buildJsonArray {
                    add(
                        buildJsonObject {
                            put("id", "s1")
                            put("kind", "media_store")
                            put("label", "Cámara")
                            put("enabled", true)
                            put("state", "idle")
                            put("files_total", 120)
                            put("files_done", 100)
                            put("files_pending", 20)
                            put("last_scan_at", JsonPrimitive(null as String?))
                        }
                    )
                }
            )
        }
        val folder = parsePhoneFolders(json).single()
        assertEquals("Cámara", folder.label)
        assertEquals(20, folder.filesPending)
        assertNull(folder.lastScanAt)
    }

    @Test
    fun `documents skip photos and videos and walk the whole tree`() {
        val json = buildJsonObject {
            put("truncated", true)
            put(
                "root",
                buildJsonObject {
                    put("kind", "folder")
                    put("id", "root")
                    put(
                        "children",
                        buildJsonArray {
                            add(asset("a1", "factura.pdf", "application/pdf", "2024-03-02"))
                            add(asset("a2", "foto.jpg", "image/jpeg", "2024-03-03"))
                            add(
                                buildJsonObject {
                                    put("kind", "folder")
                                    put("id", "f1")
                                    put("children", buildJsonArray { add(asset("a3", "notas.txt", "text/plain", "2024-03-04")) })
                                }
                            )
                        }
                    )
                }
            )
        }
        val result = parseDocuments(json)
        assertEquals(listOf("a3", "a1"), result.items.map { it.id })
        assertTrue(result.truncated)
    }

    private fun asset(id: String, name: String, mime: String, created: String) = buildJsonObject {
        put("kind", "asset")
        put("id", id)
        put("name", name)
        put("path", "/$name")
        put("mime_type", mime)
        put("size_bytes", 10)
        put("created_at", created)
    }
}
