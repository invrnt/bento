package dev.bento.engine

import android.content.Context
import dev.bento.engine.bridge.KeyWrapping
import java.io.File

/**
 * "Reset this phone" after the device key is lost (SEC-11, [DegradedReason.KEY_LOST]). Everything local was
 * protected by the lost key, so it is unreadable: the wrapped key, the Keystore key, the catalog and key store
 * (`noBackupFilesDir/bento`), the UI cache (`filesDir/bento`) and decrypted caches go. The vault on Telegram is not
 * touched; the person links this phone again or uses the recovery kit.
 */
class DeviceReset(private val context: Context, private val keyWrapping: KeyWrapping) {
    fun wipe() {
        keyWrapping.reset()
        File(context.noBackupFilesDir, "bento").deleteRecursively()
        File(context.filesDir, "bento").deleteRecursively()
        context.cacheDir.listFiles()?.forEach { it.deleteRecursively() }
    }
}
