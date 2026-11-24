package dev.bento.engine.bridge

import android.content.pm.PackageManager
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.security.keystore.StrongBoxUnavailableException
import java.io.File
import java.security.KeyStore
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Supplies the AES-256-GCM key that wraps the device key. */
fun interface WrappingKeySource {
    fun key(): SecretKey
}

/**
 * `wrapping.bin` = `0x01 | iv(12) | AES-256-GCM(ciphertext+tag)` of 32 random bytes, wrapped by
 * [WrappingKeySource] (AndroidKeystore `bento.wrapping.v1` in production). The file lives in
 * `noBackupFilesDir/bento/secure/` (excluded from backup and device transfer).
 */
class KeystoreKeyWrapping(
    private val file: File,
    private val keySource: WrappingKeySource,
    private val random: SecureRandom = SecureRandom()
) : KeyWrapping {
    @Synchronized
    override fun deviceWrappingKey(): ByteArray {
        if (file.exists()) return unwrap(file.readBytes())
        val raw = ByteArray(KEY_BYTES).also(random::nextBytes)
        val wrapped = wrap(raw)
        file.parentFile?.mkdirs()
        val tmp = File(file.parentFile, "${file.name}.tmp")
        tmp.writeBytes(wrapped)
        if (!tmp.renameTo(file)) throw BridgeException(BridgeException.IO, "cannot persist wrapping key")
        return raw
    }

    private fun wrap(raw: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, keySource.key())
        val iv = cipher.iv
        check(iv.size == IV_BYTES) { "unexpected IV size" }
        return byteArrayOf(VERSION) + iv + cipher.doFinal(raw)
    }

    private fun unwrap(blob: ByteArray): ByteArray {
        if (blob.size < 1 + IV_BYTES + TAG_BYTES || blob[0] != VERSION) {
            throw BridgeException(BridgeException.IO, "wrapping.bin has an unknown format")
        }
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, keySource.key(), GCMParameterSpec(TAG_BYTES * 8, blob, 1, IV_BYTES))
        val raw = try {
            cipher.doFinal(blob, 1 + IV_BYTES, blob.size - 1 - IV_BYTES)
        } catch (error: javax.crypto.AEADBadTagException) {
            throw BridgeException(BridgeException.IO, "wrapping.bin cannot be unwrapped", error)
        }
        if (raw.size != KEY_BYTES) throw BridgeException(BridgeException.IO, "wrapping.bin has a bad key size")
        return raw
    }

    companion object {
        const val ALIAS = "bento.wrapping.v1"
        private const val VERSION: Byte = 1
        private const val KEY_BYTES = 32
        private const val IV_BYTES = 12
        private const val TAG_BYTES = 16
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
    }
}

/** AndroidKeystore AES-256-GCM key, StrongBox when present, else TEE; not user-authentication bound. */
class AndroidKeystoreKeySource(private val packageManager: PackageManager) : WrappingKeySource {
    override fun key(): SecretKey {
        val store = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        (store.getKey(KeystoreKeyWrapping.ALIAS, null) as? SecretKey)?.let { return it }
        val strongBox = Build.VERSION.SDK_INT >= Build.VERSION_CODES.P &&
            packageManager.hasSystemFeature(PackageManager.FEATURE_STRONGBOX_KEYSTORE)
        return try {
            generate(strongBox)
        } catch (unavailable: StrongBoxUnavailableException) {
            generate(strongBox = false)
        }
    }

    private fun generate(strongBox: Boolean): SecretKey {
        val spec = KeyGenParameterSpec.Builder(
            KeystoreKeyWrapping.ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .setRandomizedEncryptionRequired(true)
            .setUserAuthenticationRequired(false)
            .setIsStrongBoxBacked(strongBox)
            .build()
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE).run {
            init(spec)
            generateKey()
        }
    }

    private companion object {
        const val KEYSTORE = "AndroidKeyStore"
    }
}
