package dev.bento.app.navigation

import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.snapshots.SnapshotStateList

/**
 * Back-stack owner (pure; JVM tested). Rules (product/android.md §3): switching tabs keeps one entry per
 * tab; back from a non-start tab goes to Fotos, then exits; reselecting the current tab pops to its root.
 */
class Navigator(initial: List<Route> = listOf(Route.Photos)) {
    val backStack: SnapshotStateList<Route> = mutableStateListOf<Route>().apply { addAll(initial) }

    val current: Route get() = backStack.last()

    val currentTopLevel: TopLevel
        get() = backStack.asReversed().firstNotNullOfOrNull { TopLevel.of(it) } ?: TopLevel.PHOTOS

    fun navigate(route: Route) {
        if (TopLevel.of(route) != null) selectTab(TopLevel.of(route)!!) else backStack.add(route)
    }

    /** Tab press; returns true when it was a reselect (the screen scrolls to top / opens search). */
    fun selectTab(tab: TopLevel): Boolean {
        val reselect = currentTopLevel == tab
        val root = backStack.indexOfLast { TopLevel.of(it) == tab }
        if (reselect && root >= 0) {
            while (backStack.size > root + 1) backStack.removeAt(backStack.lastIndex)
            return true
        }
        backStack.clear()
        backStack.add(Route.Photos)
        if (tab != TopLevel.PHOTOS) backStack.add(tab.route)
        return false
    }

    /** Returns false when back should leave the app. */
    fun back(): Boolean {
        if (backStack.size <= 1) return false
        backStack.removeAt(backStack.lastIndex)
        return true
    }

    /** Replace the whole stack (deep links, onboarding finished). */
    fun reset(vararg routes: Route) {
        backStack.clear()
        backStack.addAll(routes.ifEmpty { arrayOf(Route.Photos) })
    }
}
