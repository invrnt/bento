package dev.bento.testing

import dev.bento.engine.BentoEngine
import dev.bento.engine.EngineConfig
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.StandardTestDispatcher

val testEngineConfig = EngineConfig(
    dataDir = "/data/files/bento",
    noBackupDir = "/data/no_backup",
    cacheDir = "/data/cache",
    environment = "debug",
    storageBackend = "fake",
    telegramApiId = null,
    telegramApiHash = null,
    relayUrl = null,
    siteUrl = null,
    appVersion = "0.0.0-test",
    deviceNameDefault = "Pixel",
)

/** A [BentoEngine] on virtual time with a [FakeEngineRuntime]; everything runs on the test scheduler. */
class TestEngineHarness(scope: TestScope, val runtime: FakeEngineRuntime = FakeEngineRuntime()) {
    val keeper = FakeProcessKeeper()
    val keys = FakeKeyWrapping()
    private val dispatcher = StandardTestDispatcher(scope.testScheduler)
    val engine = BentoEngine(
        runtime = runtime,
        config = { testEngineConfig },
        wrappingKey = keys::deviceWrappingKey,
        processKeeper = keeper,
        scope = scope.backgroundScope,
        engineDispatcher = dispatcher,
        blockingDispatcher = dispatcher,
        clock = { scope.testScheduler.currentTime },
        tokenFactory = { "test-token-0123456789" },
    )
}
