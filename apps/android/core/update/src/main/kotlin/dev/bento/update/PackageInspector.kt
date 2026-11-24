package dev.bento.update

import android.content.Context
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.content.pm.Signature
import android.os.Build
import java.io.File
import java.security.MessageDigest

/** Signing certificates as SHA-256 hex: [current] signs the APK now, [history] includes rotated-from certificates. */
data class SignerSet(val current: Set<String>, val history: Set<String>)

data class ArchiveInfo(val packageName: String, val versionCode: Long, val signers: SignerSet)

/** PackageManager reads the updater needs; faked in tests. */
interface PackageInspector {
    fun installed(): InstalledApp

    fun installedSigners(): SignerSet?

    fun archive(apk: File): ArchiveInfo?

    /** "Instalar apps desconocidas" is allowed for Bento. */
    fun canRequestInstalls(): Boolean
}

object SignerCheck {
    /**
     * The new APK must be signed by the installed app's current certificate set, or by a rotated certificate whose
     * lineage contains it (APK Signature Scheme v3), and by a certificate the signed manifest lists.
     */
    fun matches(installed: SignerSet, apk: SignerSet, manifestCertificates: Set<String>): Boolean {
        if (installed.current.isEmpty() || apk.current.isEmpty()) return false
        val sameOrRotated = apk.current == installed.current || (installed.current.size == 1 && installed.current.single() in apk.history)
        return sameOrRotated && apk.current.all { it in manifestCertificates }
    }
}

class AndroidPackageInspector(private val context: Context) : PackageInspector {
    private val pm: PackageManager get() = context.packageManager

    override fun installed(): InstalledApp {
        val info = pm.getPackageInfo(context.packageName, 0)
        val arch = if (Build.SUPPORTED_ABIS.firstOrNull() == "arm64-v8a") UpdateArch.Arm64 else UpdateArch.Universal
        return InstalledApp(context.packageName, info.longVersionCode, Build.VERSION.SDK_INT, arch)
    }

    override fun installedSigners(): SignerSet? = runCatching {
        signers(pm.getPackageInfo(context.packageName, PackageManager.GET_SIGNING_CERTIFICATES))
    }.getOrNull()

    override fun archive(apk: File): ArchiveInfo? {
        val info = pm.getPackageArchiveInfo(apk.absolutePath, PackageManager.GET_SIGNING_CERTIFICATES) ?: return null
        val signers = signers(info) ?: return null
        return ArchiveInfo(info.packageName, info.longVersionCode, signers)
    }

    override fun canRequestInstalls(): Boolean = pm.canRequestPackageInstalls()

    private fun signers(info: PackageInfo): SignerSet? {
        val signing = info.signingInfo ?: return null
        return if (signing.hasMultipleSigners()) {
            val current = signing.apkContentsSigners.digests()
            SignerSet(current, current)
        } else {
            val history = signing.signingCertificateHistory.orEmpty()
            if (history.isEmpty()) return null
            // The last entry is the current signer; earlier ones are its lineage.
            SignerSet(setOf(history.last().sha256()), history.digests())
        }
    }

    private fun Array<out Signature>?.digests(): Set<String> = orEmpty().map { it.sha256() }.toSet()

    private fun Signature.sha256(): String = MessageDigest.getInstance("SHA-256").digest(toByteArray()).toHex()
}
