package dev.bento.app.navigation

import java.net.URI

/**
 * Parses pairing links (android-runtime.md §9): `bento://join?v=1&c=<code>` and the verified App Link
 * `https://<site>/join#v=1&c=<code>`. Unknown versions or malformed codes open the join screen empty.
 */
object DeepLinks {
    private val code = Regex("^[0-9A-Za-z-]{4,64}$")

    fun parse(link: String?, siteHost: String?): Route? {
        if (link.isNullOrBlank()) return null
        val uri = runCatching { URI(link) }.getOrNull() ?: return null
        val params = when {
            uri.scheme == "bento" && uri.host == "join" -> parseParams(uri.rawQuery)

            uri.scheme == "https" && siteHost != null && uri.host.equals(siteHost, ignoreCase = true) && uri.path == "/join" ->
                parseParams(uri.rawFragment)

            else -> return null
        }
        val value = params["c"]?.takeIf { params["v"] == "1" && code.matches(it) }
        return Route.Join(value?.uppercase())
    }

    private fun parseParams(raw: String?): Map<String, String> = raw.orEmpty().split('&').mapNotNull { part ->
        val index = part.indexOf('=')
        if (index <= 0) null else part.substring(0, index) to java.net.URLDecoder.decode(part.substring(index + 1), "UTF-8")
    }.toMap()
}
