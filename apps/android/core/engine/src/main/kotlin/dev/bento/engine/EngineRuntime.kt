package dev.bento.engine

/**
 * The embedded backend as seen from Kotlin: the `bento.interfaces.android.engine` entrypoints of
 * `api/android-endpoints.md` §1. [ChaquopyEngineRuntime] is the real implementation; JVM tests use a fake.
 *
 * Every method blocks and is called from the engine's single background thread.
 */
interface EngineRuntime {
    /** Starts the interpreter and imports the backend in a fixed order. Idempotent. */
    fun warmUp()

    fun configure(config: EngineConfig, wrappingKey: ByteArray)

    fun migrate(): MigrationResult

    fun startWorker(mode: WorkerMode)

    /**
     * Starts uvicorn on a loopback ephemeral port with these per-start [credentials] and returns the port once
     * accepting. New credentials replace a running API (new port); the same ones return its port.
     */
    fun startApi(credentials: ApiCredentials): Int

    fun runWorkerUntil(deadlineEpochMs: Long, kinds: List<String>?): WorkerRunResult

    fun stop(timeoutMs: Long)

    /** Thread-safe, non-blocking hand-off into the worker loop. */
    fun onEvent(kind: String, payloadJson: String)

    fun status(): EngineStatus
}

/** Non-secret configuration passed to `configure` (secrets travel separately, in memory). */
data class EngineConfig(
    val dataDir: String,
    val noBackupDir: String,
    val cacheDir: String,
    val environment: String,
    val storageBackend: String,
    val telegramApiId: String?,
    val telegramApiHash: String?,
    val relayUrl: String?,
    val siteUrl: String?,
    val appVersion: String,
    val deviceNameDefault: String,
    /** Extracted `apps/api/migrations` (see [MigrationAssets]); null uses the backend's default location. */
    val migrationsDir: String? = null,
    /** Debug builds only: fake cloud directory, part size, manual login (see `DebugOptions`). */
    val debugOptions: Map<String, String> = emptyMap()
)
