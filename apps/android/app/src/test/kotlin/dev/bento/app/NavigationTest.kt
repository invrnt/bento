package dev.bento.app

import dev.bento.app.navigation.DeepLinks
import dev.bento.app.navigation.Navigator
import dev.bento.app.navigation.Route
import dev.bento.app.navigation.TopLevel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NavigatorTest {
    @Test
    fun `back from a non-start tab goes to Fotos, then exits`() {
        val nav = Navigator()
        nav.selectTab(TopLevel.FILES)
        assertEquals(listOf(Route.Photos, Route.Files()), nav.backStack.toList())
        assertTrue(nav.back())
        assertEquals(TopLevel.PHOTOS, nav.currentTopLevel)
        assertFalse("back at Fotos leaves the app", nav.back())
    }

    @Test
    fun `switching tabs keeps one entry per tab`() {
        val nav = Navigator()
        nav.selectTab(TopLevel.FILES)
        nav.navigate(Route.Viewer("a1"))
        nav.selectTab(TopLevel.COLLECTIONS)
        assertEquals(listOf(Route.Photos, Route.Collections), nav.backStack.toList())
    }

    @Test
    fun `reselecting the current tab pops to its root`() {
        val nav = Navigator()
        nav.navigate(Route.Viewer("a1"))
        nav.navigate(Route.Album("b"))
        assertTrue(nav.selectTab(TopLevel.PHOTOS))
        assertEquals(listOf(Route.Photos), nav.backStack.toList())
    }

    @Test
    fun `nested folders are not top level`() {
        val nav = Navigator()
        nav.selectTab(TopLevel.FILES)
        nav.navigate(Route.Files("f1"))
        assertEquals(Route.Files("f1"), nav.current)
        assertEquals(TopLevel.FILES, nav.currentTopLevel)
    }
}

class DeepLinksTest {
    @Test
    fun `custom scheme and verified app links carry the code`() {
        assertEquals(Route.Join("ABCD-EFGH"), DeepLinks.parse("bento://join?v=1&c=abcd-efgh", "bento.example"))
        assertEquals(Route.Join("ABCD-EFGH"), DeepLinks.parse("https://bento.example/join#v=1&c=ABCD-EFGH", "bento.example"))
    }

    @Test
    fun `unknown versions and bad codes open the join screen empty`() {
        assertEquals(Route.Join(null), DeepLinks.parse("bento://join?v=2&c=ABCD", null))
        assertEquals(Route.Join(null), DeepLinks.parse("bento://join?v=1&c=%3Cscript%3E", null))
    }

    @Test
    fun `other hosts and paths are ignored`() {
        assertNull(DeepLinks.parse("https://evil.example/join#v=1&c=ABCD", "bento.example"))
        assertNull(DeepLinks.parse("https://bento.example/other#v=1&c=ABCD", "bento.example"))
        assertNull(DeepLinks.parse("https://bento.example/join#v=1&c=ABCD", null))
        assertNull(DeepLinks.parse("bento://recovery?c=ABCD", null))
        assertNull(DeepLinks.parse(null, null))
    }
}
