package dev.bento.engine.bridge

import android.os.ParcelFileDescriptor
import java.io.File
import java.io.FileNotFoundException
import kotlinx.serialization.json.Json

internal val BridgeJson = Json {
    encodeDefaults = true
    explicitNulls = true
    ignoreUnknownKeys = true
}

/** A bridge `source` argument: an absolute path or `fd:<n>` owned by the caller. */
sealed interface BridgeSource {
    data class Path(val file: File) : BridgeSource

    data class Descriptor(val fd: Int) : BridgeSource

    companion object {
        fun parse(source: String): BridgeSource = when {
            source.startsWith("fd:") -> Descriptor(
                source.removePrefix("fd:").toIntOrNull()
                    ?: throw BridgeException(BridgeException.UNSUPPORTED, "bad descriptor source")
            )

            source.startsWith("/") -> Path(File(source))

            else -> throw BridgeException(BridgeException.UNSUPPORTED, "source must be an absolute path or fd:<n>")
        }
    }
}

/**
 * Opens [source] for reading as a descriptor the bridge owns: a path is opened, a caller-owned `fd:<n>`
 * is duplicated so closing ours never closes the caller's.
 */
internal fun BridgeSource.openPfd(): ParcelFileDescriptor = try {
    when (this) {
        is BridgeSource.Path -> ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
        is BridgeSource.Descriptor -> ParcelFileDescriptor.fromFd(fd)
    }
} catch (missing: FileNotFoundException) {
    throw BridgeException(BridgeException.NOT_FOUND, "source not found", missing)
} catch (io: java.io.IOException) {
    throw BridgeException(BridgeException.IO, "cannot open source", io)
}

/** Maps unexpected failures to [BridgeException] codes so Python adapters get typed errors. */
internal inline fun <T> bridgeCall(block: () -> T): T = try {
    block()
} catch (bridge: BridgeException) {
    throw bridge
} catch (security: SecurityException) {
    throw BridgeException(BridgeException.PERMISSION_DENIED, security.message ?: "permission denied", security)
} catch (missing: FileNotFoundException) {
    throw BridgeException(BridgeException.NOT_FOUND, missing.message ?: "not found", missing)
} catch (io: java.io.IOException) {
    throw BridgeException(BridgeException.IO, io.message ?: "io error", io)
} catch (interrupted: InterruptedException) {
    Thread.currentThread().interrupt()
    throw BridgeException(BridgeException.CANCELLED, "interrupted", interrupted)
} catch (unsupported: UnsupportedOperationException) {
    throw BridgeException(BridgeException.UNSUPPORTED, unsupported.message ?: "unsupported", unsupported)
}
