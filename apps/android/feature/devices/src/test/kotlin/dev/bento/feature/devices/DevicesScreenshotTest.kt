package dev.bento.feature.devices

import androidx.compose.runtime.Composable
import androidx.compose.ui.test.junit4.createComposeRule
import dev.bento.api.BentoJson
import dev.bento.api.generated.DeviceResponse
import dev.bento.api.generated.PairingRequestItem
import dev.bento.testing.BentoScreenshots
import dev.bento.testing.TrustFixtures
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = BentoScreenshots.QUALIFIERS)
class DevicesScreenshotTest {
    @get:Rule
    val compose = createComposeRule()

    private fun shot(name: String, content: @Composable () -> Unit) = BentoScreenshots.capture(compose, "screenshots", name, content)
    private fun d(json: String) = BentoJson.decodeFromString(DeviceResponse.serializer(), json)
    private val now = java.time.Instant.parse("2026-11-24T10:00:00Z").toEpochMilli()
    private val devices = listOf(
        d(TrustFixtures.device("d_me", "Pixel 8", platform = "android", current = true)),
        d(TrustFixtures.device("d_new", "Equipo raro", platform = "windows", needsReview = true)),
        d(TrustFixtures.device("d_lap", "Portátil de Ana", lastSeen = "2026-11-24T09:58:00+00:00")),
        d(TrustFixtures.device("d_mac", "MacBook", platform = "macos", lastSeen = "2026-11-20T09:00:00+00:00"))
    )

    @Test fun list() = shot("list") { DevicesContent(DevicesState(loading = false, devices = devices), DevicesActions(), now = now) }

    @Test fun listWithRequestAndNotice() = shot("list-request-notice") {
        DevicesContent(
            DevicesState(
                loading = false,
                devices = devices.filterNot { it.needsReview },
                requests = listOf(PairingRequestItem("2026-11-24T10:00:00+00:00", "Pixel 9", "req_1", "android")),
                notice = RemovalNotice("Portátil viejo", alsoRemoved = 1, sessionOpen = true, excludedSessionsOpen = true)
            ),
            DevicesActions(),
            now = now
        )
    }

    @Test fun loading() = shot("loading") { DevicesContent(DevicesState(), DevicesActions(), now = now) }

    @Test fun error() = shot("error") { DevicesContent(DevicesState(loading = false, loadFailed = true), DevicesActions(), now = now) }

    @Test fun local() = shot("local") { DevicesContent(DevicesState(loading = false, localOnly = true), DevicesActions(), now = now) }

    @Test fun removalLoading() = shot("removal-loading") { RemovalSheetBody(RemovalState(devices[2]), DevicesActions()) }

    @Test fun removalExclusions() = shot("removal-exclusions") {
        RemovalSheetBody(RemovalState(devices[2], loadingPreview = false, recipients = listOf(devices[0], devices[1], devices[3]), excluded = setOf("d_new")), DevicesActions())
    }

    @Test fun removalFailed() = shot("removal-failed") {
        RemovalSheetBody(RemovalState(devices[2], loadingPreview = false, previewFailed = true, failed = RemovalFailure.Generic), DevicesActions())
    }

    @Test fun removedSelf() = shot("this-phone-removed") { DeviceRemovedScreen({}, {}, {}) }
}
