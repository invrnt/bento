package dev.bento.update

import android.content.Context
import java.io.File
import java.io.IOException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/** Last check time and the version whose card the user dismissed ("Ahora no"). */
interface UpdatePreferences {
    var lastCheckedAt: Long?
    var dismissedVersion: String?
}

class SharedUpdatePreferences(context: Context) : UpdatePreferences {
    private val prefs = context.getSharedPreferences("bento_update", Context.MODE_PRIVATE)

    override var lastCheckedAt: Long?
        get() = prefs.getLong(LAST_CHECK, -1).takeIf { it >= 0 }
        set(value) = prefs.edit().apply { if (value == null) remove(LAST_CHECK) else putLong(LAST_CHECK, value) }.apply()

    override var dismissedVersion: String?
        get() = prefs.getString(DISMISSED, null)
        set(value) = prefs.edit().putString(DISMISSED, value).apply()

    private companion object {
        const val LAST_CHECK = "last_checked_at"
        const val DISMISSED = "dismissed_version"
    }
}

data class UpdateConfig(val publicKeys: List<ByteArray>, val repository: String, val allowLoopbackHttp: Boolean) {
    val enabled: Boolean get() = publicKeys.isNotEmpty()
}

/**
 * The updater: check the signed manifest, download with resume, verify SHA-256 and signer, hand to the installer.
 * Every step is user-initiated except the daily background check ([UpdateCheckWorker]), which only checks.
 */
class UpdateChecker(
    private val config: UpdateConfig,
    private val feed: ReleaseFeed,
    private val downloader: ApkDownloader,
    private val packages: PackageInspector,
    private val installer: UpdateInstaller,
    private val preferences: UpdatePreferences,
    private val scope: CoroutineScope,
    private val now: () -> Long = System::currentTimeMillis,
    /** Package parsing (getPackageArchiveInfo on a ~100 MB APK) and file work stay off the main thread. */
    private val io: CoroutineDispatcher = Dispatchers.IO
) {
    private val mutable = MutableStateFlow(initial())
    val state: StateFlow<UpdateState> = mutable.asStateFlow()

    private val dismissed = MutableStateFlow(preferences.dismissedVersion)

    /** Whether the calm card should be visible: an update in progress whose version the user did not dismiss. */
    val showCard: StateFlow<Boolean> = combine(mutable, dismissed) { state, dismissedVersion ->
        val release = state.release ?: return@combine false
        state is UpdateState.Downloading || state is UpdateState.Installing || release.version != dismissedVersion
    }.stateIn(scope, SharingStarted.Eagerly, false)

    private val lock = Mutex()
    private var job: Job? = null

    private fun initial(): UpdateState =
        if (config.enabled) UpdateState.Idle(preferences.lastCheckedAt, upToDate = false) else UpdateState.Unavailable

    /** Fetch and verify the manifest. Returns the resulting state. */
    suspend fun check(): UpdateState = lock.withLock {
        if (!config.enabled) return UpdateState.Unavailable
        val current = mutable.value
        if (current is UpdateState.Downloading || current is UpdateState.Installing) return current
        mutable.value = UpdateState.Checking
        val next = try {
            withContext(io) { evaluate() }
        } catch (error: CancellationException) {
            mutable.value = current
            throw error
        } catch (_: IOException) {
            UpdateState.Failed(UpdateFailure.Network)
        }
        mutable.value = next
        next
    }

    private suspend fun evaluate(): UpdateState {
        val installed = packages.installed()
        val signed = feed.latest(installed.arch)
        preferences.lastCheckedAt = now()
        if (signed == null) return upToDate()
        val verdict = ManifestParser.evaluate(
            manifestBytes = signed.manifest,
            signatureBytes = signed.signature,
            publicKeys = config.publicKeys,
            installed = installed,
            repository = config.repository,
            tagVersion = signed.tagVersion,
            allowLoopbackHttp = config.allowLoopbackHttp
        )
        return when (verdict) {
            ManifestVerdict.UpToDate -> upToDate()
            is ManifestVerdict.Rejected -> UpdateState.Failed(verdict.failure)
            is ManifestVerdict.Newer -> {
                downloader.pruneOthers(verdict.release.asset)
                val apk = downloader.existing(verdict.release.asset)
                if (apk != null && verifySigner(apk, verdict.release) == null) readyState(verdict.release) else UpdateState.Available(verdict.release)
            }
        }
    }

    private fun upToDate(): UpdateState {
        // Leftovers of an installed (or abandoned) update.
        downloader.pruneOthers(null)
        return UpdateState.Idle(preferences.lastCheckedAt, upToDate = true)
    }

    fun checkInBackground() {
        scope.launch { check() }
    }

    /** User tapped "Descargar" (or "Reintentar" after a download failure). */
    fun download() {
        val release = mutable.value.release ?: return
        if (job?.isActive == true) return
        job = scope.launch {
            mutable.value = UpdateState.Downloading(release, progress = null)
            mutable.value = try {
                var lastPercent = -1
                val apk = downloader.download(release.asset) { progress ->
                    val percent = (progress.coerceIn(0f, 1f) * 100).toInt()
                    if (percent != lastPercent) {
                        lastPercent = percent
                        mutable.value = UpdateState.Downloading(release, percent / 100f)
                    }
                }
                val failure = withContext(io) { verifySigner(apk, release) }
                if (failure != null) {
                    apk.delete()
                    UpdateState.Failed(failure, release)
                } else {
                    readyState(release)
                }
            } catch (error: UpdateDownloadException) {
                UpdateState.Failed(error.failure, release)
            } catch (error: CancellationException) {
                mutable.value = UpdateState.Available(release)
                throw error
            } catch (_: IOException) {
                UpdateState.Failed(UpdateFailure.Network, release)
            }
        }
    }

    fun cancelDownload() {
        job?.cancel()
    }

    /** User tapped "Instalar": re-verifies the file on disk, then opens the system installer. */
    fun install() {
        val current = mutable.value as? UpdateState.Ready ?: return
        if (job?.isActive == true) return
        job = scope.launch {
            val release = current.release
            if (!packages.canRequestInstalls()) {
                mutable.value = current.copy(needsPermission = true)
                return@launch
            }
            val apk = downloader.existing(release.asset)
            val failure = if (apk == null) UpdateFailure.Checksum else withContext(io) { verifySigner(apk, release) }
            if (apk == null || failure != null) {
                apk?.delete()
                mutable.value = UpdateState.Failed(failure ?: UpdateFailure.Checksum, release)
                return@launch
            }
            mutable.value = UpdateState.Installing(release)
            try {
                installer.install(apk)
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                mutable.value = UpdateState.Failed(UpdateFailure.Install, release)
            }
        }
    }

    /** Back from Ajustes › "Instalar apps desconocidas" (lifecycle ON_RESUME). */
    fun refreshPermission() {
        val current = mutable.value as? UpdateState.Ready ?: return
        if (current.needsPermission && packages.canRequestInstalls()) mutable.value = current.copy(needsPermission = false)
    }

    fun openUnknownSourcesSettings(context: Context) = installer.openUnknownSourcesSettings(context)

    /** "Ahora no": hides the card for this version (Ajustes › Acerca de still shows it). */
    fun dismiss() {
        val version = mutable.value.release?.version ?: return
        preferences.dismissedVersion = version
        dismissed.value = version
    }

    fun onInstallResult(result: InstallResult) {
        val release = mutable.value.release ?: return
        mutable.value = when (result) {
            // Usually the process is replaced before this arrives; the next start sees the new versionCode.
            InstallResult.Installed -> UpdateState.Idle(preferences.lastCheckedAt, upToDate = true)
            InstallResult.Cancelled -> UpdateState.Ready(release, cancelled = true)
            InstallResult.NoSpace -> UpdateState.Failed(UpdateFailure.Storage, release)
            InstallResult.Failed -> UpdateState.Failed(UpdateFailure.Install, release)
        }
    }

    /** User tapped "Reintentar" on a failure. */
    fun retry() {
        val current = mutable.value as? UpdateState.Failed ?: return
        if (current.release != null && current.reason in DOWNLOAD_FAILURES) download() else checkInBackground()
    }

    private fun readyState(release: UpdateRelease) = UpdateState.Ready(release, needsPermission = !packages.canRequestInstalls())

    /** `null` when [apk] is this app, the signed versionCode and signed by the installed certificate. */
    private fun verifySigner(apk: File, release: UpdateRelease): UpdateFailure? {
        val archive = packages.archive(apk) ?: return UpdateFailure.Signer
        val installed = packages.installedSigners() ?: return UpdateFailure.Signer
        val ok = archive.packageName == packages.installed().packageName &&
            archive.versionCode == release.versionCode &&
            SignerCheck.matches(installed, archive.signers, release.signingCertificates)
        return if (ok) null else UpdateFailure.Signer
    }

    private companion object {
        val DOWNLOAD_FAILURES = setOf(UpdateFailure.Network, UpdateFailure.Checksum, UpdateFailure.Storage, UpdateFailure.Install)
    }
}
