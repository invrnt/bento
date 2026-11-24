package dev.bento.update

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.IntentCompat
import dagger.hilt.android.AndroidEntryPoint
import java.io.File
import javax.inject.Inject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Hands a verified APK to the system installer. Never silent: the system always asks the user. */
interface UpdateInstaller {
    suspend fun install(apk: File)

    /** Opens Ajustes › "Instalar apps desconocidas" for Bento. */
    fun openUnknownSourcesSettings(context: Context)
}

class PackageInstallerUpdater(private val context: Context) : UpdateInstaller {
    override suspend fun install(apk: File) = withContext(Dispatchers.IO) {
        val installer = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL).apply {
            setAppPackageName(context.packageName)
            setSize(apk.length())
            setInstallReason(PackageManager.INSTALL_REASON_USER)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_REQUIRED)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) setPackageSource(PackageInstaller.PACKAGE_SOURCE_DOWNLOADED_FILE)
        }
        val sessionId = installer.createSession(params)
        try {
            installer.openSession(sessionId).use { session ->
                apk.inputStream().use { input ->
                    session.openWrite("base.apk", 0, apk.length()).use { output ->
                        input.copyTo(output, BUFFER)
                        session.fsync(output)
                    }
                }
                val callback = Intent(context, UpdateInstallReceiver::class.java).setPackage(context.packageName)
                // The installer adds its status extras, so the PendingIntent must be mutable.
                val pending = PendingIntent.getBroadcast(
                    context,
                    sessionId,
                    callback,
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE
                )
                session.commit(pending.intentSender)
            }
        } catch (error: Exception) {
            runCatching { installer.abandonSession(sessionId) }
            throw error
        }
    }

    override fun openUnknownSourcesSettings(context: Context) {
        val intent = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}"))
        if (context !is android.app.Activity) intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
    }

    private companion object {
        const val BUFFER = 64 * 1024
    }
}

/** Results of a [PackageInstallerUpdater] session (non-exported; only the system installer's PendingIntent reaches it). */
@AndroidEntryPoint
class UpdateInstallReceiver : BroadcastReceiver() {
    @Inject lateinit var checker: UpdateChecker

    override fun onReceive(context: Context, intent: Intent) {
        when (val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                val confirm = IntentCompat.getParcelableExtra(intent, Intent.EXTRA_INTENT, Intent::class.java)
                if (confirm == null) {
                    checker.onInstallResult(InstallResult.Failed)
                    return
                }
                // The system installer's own confirmation screen (it shows the app, version and asks the user).
                confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                runCatching { context.startActivity(confirm) }.onFailure { checker.onInstallResult(InstallResult.Failed) }
            }

            PackageInstaller.STATUS_SUCCESS -> checker.onInstallResult(InstallResult.Installed)

            PackageInstaller.STATUS_FAILURE_ABORTED -> checker.onInstallResult(InstallResult.Cancelled)

            PackageInstaller.STATUS_FAILURE_STORAGE -> checker.onInstallResult(InstallResult.NoSpace)

            else -> checker.onInstallResult(InstallResult.Failed)
        }
    }
}

enum class InstallResult { Installed, Cancelled, NoSpace, Failed }
