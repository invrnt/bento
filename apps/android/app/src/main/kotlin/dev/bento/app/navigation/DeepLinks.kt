package dev.bento.app.navigation

import java.net.URI
import java.net.URLDecoder

/**
 * Parses pairing links (android-runtime.md §9): `bento://join?v=1&c=<code>` and the verified App Link
 * `https://<site>/join#v=1&c=<code>` (also `/join/`). Unknown versions or malformed codes open the join screen
 * empty. Links are untrusted input from any app or web page (SEC-05, SEC-10): parsing never throws, oversize
 * links are ignored, and a code only prefills the join screen (it never joins by itself).
 */
object DeepLinks {
    /** Far above a real link (~60 characters); longer input is not parsed at all. */
    const val MAX_LINK_LENGTH = 2_048
    private const val MAX_PARAMS = 16
    private val code = Regex("^[0-9A-Za-z-]{4,64}$")
    private val joinPaths = setOf("/join", "/join/")

    fun parse(link: String?, siteHost: String?): Route? {
        if (link.isNullOrBlank() || link.length > MAX_LINK_LENGTH) return null
        val uri = runCatching { URI(link) }.getOrNull() ?: return null
        val params = when {
            uri.scheme == "bento" && uri.host == "join" -> parseParams(uri.rawQuery)

            uri.scheme == "https" && siteHost != null && uri.host.equals(siteHost, ignoreCase = true) && uri.path in joinPaths ->
                parseParams(uri.rawFragment)

            else -> return null
        }
        val value = params["c"]?.takeIf { params["v"] == "1" && code.matches(it) }
        return Route.Join(value?.uppercase())
    }

    /** `a=1&b=2` → map; a parameter whose `%` escape is malformed is dropped instead of throwing. */
    private fun parseParams(raw: String?): Map<String, String> = raw.orEmpty().split('&').take(MAX_PARAMS).mapNotNull { part ->
        val index = part.indexOf('=')
        if (index <= 0) return@mapNotNull null
        val value = runCatching { URLDecoder.decode(part.substring(index + 1), "UTF-8") }.getOrNull() ?: return@mapNotNull null
        part.substring(0, index) to value
    }.toMap()
}
