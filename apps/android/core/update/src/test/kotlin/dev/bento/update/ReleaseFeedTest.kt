package dev.bento.update

import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test

class ReleaseFeedTest {
    private val server = MockWebServer()

    @Before
    fun setUp() = server.start()

    @After
    fun tearDown() = server.close()

    private fun url(path: String) = server.url(path).toString().replace("localhost", "127.0.0.1")

    private fun release(tag: String, draft: Boolean = false, prerelease: Boolean = false, arch: String = "universal") = """
        {"tag_name":"$tag","draft":$draft,"prerelease":$prerelease,"assets":[
          {"name":"bento-update-android-$arch.json","state":"uploaded","browser_download_url":"${url("/$tag/m.json")}"},
          {"name":"bento-update-android-$arch.json.sig","state":"uploaded","browser_download_url":"${url("/$tag/m.sig")}"}
        ]}
    """.trimIndent()

    private fun feed() = GitHubReleaseFeed(OkHttpClient(), url("/repos/invrnt/bento/releases"), allowLoopbackHttp = true)

    @Test
    fun picksTheHighestStableAndroidRelease() = runTest {
        val listing = listOf(
            release("v2.0.0"), // desktop release
            release("android-v1.10.0", prerelease = true),
            release("android-v1.9.0"),
            release("android-v1.2.0"),
            release("android-v9.0.0", draft = true)
        ).joinToString(",", "[", "]")
        server.enqueue(MockResponse.Builder().body(listing).build())
        server.enqueue(MockResponse.Builder().body("manifest").build())
        server.enqueue(MockResponse.Builder().body("signature").build())
        val signed = feed().latest(UpdateArch.Universal)!!
        assertEquals("1.9.0", signed.tagVersion)
        assertEquals("manifest", signed.manifest.decodeToString())
        assertEquals("signature", signed.signature.decodeToString())
        assertEquals("/repos/invrnt/bento/releases?per_page=30", server.takeRequest().target)
        assertEquals("/android-v1.9.0/m.json", server.takeRequest().target)
    }

    @Test
    fun releaseWithoutThisTargetsManifestIsNoUpdate() = runTest {
        server.enqueue(MockResponse.Builder().body("[${release("android-v1.3.0", arch = "arm64")}]").build())
        assertNull(feed().latest(UpdateArch.Universal))
    }

    @Test
    fun tagParsing() {
        assertEquals("1.2.3", GitHubReleaseFeed.tagVersion("android-v1.2.3"))
        assertNull(GitHubReleaseFeed.tagVersion("v1.2.3"))
        assertNull(GitHubReleaseFeed.tagVersion("android-v1.2.3-rc1"))
    }

    @Test(expected = java.io.IOException::class)
    fun plainHttpOutsideLoopbackIsRefused() = runTest {
        GitHubReleaseFeed(OkHttpClient(), "http://example.com/releases").latest(UpdateArch.Universal)
    }
}
