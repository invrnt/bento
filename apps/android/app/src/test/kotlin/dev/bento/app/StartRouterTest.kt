package dev.bento.app

import dev.bento.app.navigation.Navigator
import dev.bento.app.navigation.Route
import dev.bento.app.navigation.StartRouter
import dev.bento.feature.onboarding.Gate
import org.junit.Assert.assertEquals
import org.junit.Test

class StartRouterTest {
    private fun router(cached: Gate): Pair<Navigator, StartRouter> {
        val nav = Navigator(StartRouter.initialStack(cached))
        return nav to StartRouter(nav)
    }

    @Test
    fun cachedLibraryStartsInPhotosAndStays() {
        val (nav, router) = router(Gate.App)
        assertEquals(listOf<Route>(Route.Photos), nav.backStack.toList())
        router.apply(Gate.App)
        assertEquals(listOf<Route>(Route.Photos), nav.backStack.toList())
    }

    @Test
    fun firstRunStartsOnWelcomeAndAWrongGuessIsCorrected() {
        val (nav, router) = router(Gate.FirstRun)
        assertEquals(listOf<Route>(Route.Onboarding), nav.backStack.toList())
        router.apply(Gate.App)
        assertEquals(listOf<Route>(Route.Photos), nav.backStack.toList())
    }

    @Test
    fun neverYanksAPersonWhoAlreadyMoved() {
        val (nav, router) = router(Gate.FirstRun)
        nav.navigate(Route.Join())
        router.apply(Gate.App)
        assertEquals(listOf(Route.Onboarding, Route.Join()), nav.backStack.toList())
        // Later resolutions (every return to the foreground) do not reset either.
        nav.reset(Route.Onboarding)
        router.apply(Gate.App)
        assertEquals(listOf<Route>(Route.Onboarding), nav.backStack.toList())
    }

    @Test
    fun lockedGoesToTheJoinChoice() {
        val (nav, router) = router(Gate.FirstRun)
        router.apply(Gate.Locked)
        assertEquals(listOf<Route>(Route.Join(choose = true)), nav.backStack.toList())
    }

    @Test
    fun reconnectAndRemovedShowOnceOverTheLibrary() {
        val (nav, router) = router(Gate.App)
        router.apply(Gate.Reconnect)
        assertEquals(listOf(Route.Photos, Route.Reconnect), nav.backStack.toList())
        nav.back()
        router.apply(Gate.Reconnect)
        assertEquals(listOf<Route>(Route.Photos), nav.backStack.toList())
        router.apply(Gate.Removed)
        assertEquals(listOf(Route.Photos, Route.DeviceRemoved), nav.backStack.toList())
    }

    @Test
    fun removedWithAnUncachedStartLandsOnTheLibraryFirst() {
        val (nav, router) = router(Gate.FirstRun)
        router.apply(Gate.Removed)
        assertEquals(listOf(Route.Photos, Route.DeviceRemoved), nav.backStack.toList())
    }
}
