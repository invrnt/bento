package dev.bento.feature.files

import dev.bento.api.ApiException
import dev.bento.api.BentoHttp
import java.io.File
import okhttp3.OkHttpClient
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/** SEC-04: expired plaintext copies are deleted, their grants revoked first; fresh copies stay. */
class ContentFilesPruneTest {
    @get:Rule
    val temp = TemporaryFolder()

    @Test
    fun `prune revokes and deletes only expired copies`() {
        val share = temp.newFolder("share")
        var now = 10 * ContentFiles.MAX_AGE_MS
        val revoked = mutableListOf<String>()
        val files = ContentFiles(http(), share, { now }) { revoked += it.name }
        val old = copy(share, "old", "a.pdf", now - ContentFiles.MAX_AGE_MS - 1)
        val fresh = copy(share, "fresh", "b.jpg", now - 1_000)
        files.prune()
        assertEquals(listOf("a.pdf"), revoked)
        assertFalse(old.exists())
        assertTrue(fresh.exists())

        now += ContentFiles.MAX_AGE_MS + 1
        files.prune()
        assertFalse(fresh.exists())
        assertEquals(listOf("a.pdf", "b.jpg"), revoked)
    }

    @Test
    fun `prune everything at start revokes every copy`() {
        val share = temp.newFolder("share")
        val revoked = mutableListOf<String>()
        val files = ContentFiles(http(), share, { 0L }) { revoked += it.name }
        copy(share, "x", "c.txt", 0L)
        files.prune(everything = true)
        assertEquals(listOf("c.txt"), revoked)
        assertTrue(share.listFiles().isNullOrEmpty())
    }

    private fun http() = BentoHttp(OkHttpClient(), { throw ApiException.EngineUnavailable() })

    private fun copy(share: File, dir: String, name: String, modified: Long): File {
        val folder = File(share, dir).apply { mkdirs() }
        val file = File(folder, name).apply { writeText("plaintext") }
        file.setLastModified(modified)
        folder.setLastModified(modified)
        return file
    }
}
