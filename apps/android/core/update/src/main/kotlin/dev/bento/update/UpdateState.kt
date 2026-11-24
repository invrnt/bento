package dev.bento.update

/** Why an update step stopped. Security failures never fall back to installing anyway. */
enum class UpdateFailure {
    /** No connection, timeout or an HTTP error while checking or downloading. */
    Network,

    /** The manifest's Ed25519 signature is missing, malformed or not by an embedded key. */
    Signature,

    /** The signed manifest does not describe a valid release for this app and target. */
    Manifest,

    /** The release needs a newer Android version than this phone has. */
    Incompatible,

    /** The downloaded APK does not match the signed SHA-256 or size. */
    Checksum,

    /** The APK is not signed by the same certificate as the installed app (or is another app). */
    Signer,

    /** Not enough free space for the download. */
    Storage,

    /** The system installer reported a failure. */
    Install
}

/** Updater state for the card and the Ajustes › Acerca de row. */
sealed interface UpdateState {
    /** This build has no update key (debug builds by default): no checks, nothing to show. */
    data object Unavailable : UpdateState

    data class Idle(val lastCheckedAt: Long?, val upToDate: Boolean) : UpdateState

    data object Checking : UpdateState

    data class Available(val release: UpdateRelease) : UpdateState

    /** [progress] in 0..1, `null` until the size is known. */
    data class Downloading(val release: UpdateRelease, val progress: Float?) : UpdateState

    /** Verified APK on disk. [needsPermission]: "Instalar apps desconocidas" is off for Bento. [cancelled]: the user
     *  closed the system installer last time. */
    data class Ready(val release: UpdateRelease, val needsPermission: Boolean = false, val cancelled: Boolean = false) : UpdateState

    /** Handed to the system installer, waiting for the user's confirmation. */
    data class Installing(val release: UpdateRelease) : UpdateState

    data class Failed(val reason: UpdateFailure, val release: UpdateRelease? = null) : UpdateState
}

internal val UpdateState.release: UpdateRelease?
    get() = when (this) {
        is UpdateState.Available -> release
        is UpdateState.Downloading -> release
        is UpdateState.Ready -> release
        is UpdateState.Installing -> release
        is UpdateState.Failed -> release
        else -> null
    }
