package dev.bento.feature.recovery

import dev.bento.api.generated.BentoEndpoints
import dev.bento.api.generated.CreatedVaultResponse
import dev.bento.api.generated.LastGroupRequest
import dev.bento.api.generated.RecoveryCodeRequest
import dev.bento.api.generated.RecoveryCodeResponse
import dev.bento.api.generated.VaultStatusResponse
import javax.inject.Inject
import javax.inject.Singleton

/**
 * `/api/vault*` (api/telegram-first-endpoints.md § Vault and recovery). The recovery code only ever lives in screen
 * state: it is shown once, never persisted, never logged.
 */
@Singleton
class VaultRepository @Inject constructor(private val api: BentoEndpoints) {
    suspend fun status(): VaultStatusResponse = api.vaultStatus()

    /** Not idempotent: creates the vault channels and keys on the first device. */
    suspend fun create(): CreatedVaultResponse = api.createVault()

    suspend fun unlock(code: String): VaultStatusResponse = api.unlockVault(RecoveryCodeRequest(recoveryCode = code))

    suspend fun rotate(): RecoveryCodeResponse = api.rotateRecoveryCode()

    suspend fun confirmKit(lastGroup: String): VaultStatusResponse = api.confirmRecoveryKit(LastGroupRequest(lastGroup = lastGroup))

    suspend fun verify(code: String): Boolean = api.verifyRecoveryCode(RecoveryCodeRequest(recoveryCode = code)).valid
}
