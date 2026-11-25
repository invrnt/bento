package dev.bento.app.navigation

import dev.bento.feature.onboarding.Gate

/**
 * App start routing (first run vs library, product/android.md §1 "Instant", §4.1, §11). The first frame uses the
 * cached guess ([initialStack]); when the engine answers, [apply] corrects the stack only if the person has not moved
 * yet, and shows the reconnect / device-removed screens once per process over the visible library.
 */
class StartRouter(private val navigator: Navigator) {
    private var resolved = false
    private var shownReconnect = false
    private var shownRemoved = false

    // One branch per gate, kept together so it reads against product/android.md §4.1 / §11.
    @Suppress("CyclomaticComplexMethod")
    fun apply(gate: Gate) {
        val untouched = !resolved && navigator.backStack.size == 1
        val root = navigator.backStack.first()
        resolved = true
        when (gate) {
            Gate.App -> if (untouched && root == Route.Onboarding) navigator.reset(Route.Photos)

            Gate.FirstRun -> if (untouched && root == Route.Photos) navigator.reset(Route.Onboarding)

            Gate.Locked -> if (untouched) navigator.reset(Route.Join(choose = true))

            Gate.Reconnect -> {
                if (untouched && root == Route.Onboarding) navigator.reset(Route.Photos)
                if (!shownReconnect && !inSetup()) {
                    shownReconnect = true
                    navigator.navigate(Route.Reconnect)
                }
            }

            Gate.Removed -> {
                if (untouched && root == Route.Onboarding) navigator.reset(Route.Photos)
                if (!shownRemoved && !inSetup()) {
                    shownRemoved = true
                    navigator.navigate(Route.DeviceRemoved)
                }
            }
        }
    }

    private fun inSetup(): Boolean = navigator.backStack.any {
        it is Route.Onboarding || it is Route.Reconnect || it is Route.Join || it is Route.DeviceRemoved
    }

    companion object {
        fun initialStack(cached: Gate): List<Route> = listOf(if (cached == Gate.App) Route.Photos else Route.Onboarding)
    }
}
