package dev.bento.feature.onboarding

import android.graphics.BitmapFactory
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import dev.bento.api.BentoHttp
import dev.bento.api.generated.AccountStatusResponse
import dev.bento.api.generated.BentoEndpoints
import dev.bento.api.generated.CodeRequest
import dev.bento.api.generated.PasswordRequest
import dev.bento.api.generated.PhoneRequest
import javax.inject.Inject
import javax.inject.Singleton

/** Telegram sign-in on this phone (`/api/account*`, api/telegram-first-endpoints.md § Account). */
@Singleton
class LoginRepository @Inject constructor(private val api: BentoEndpoints, private val http: BentoHttp) {
    suspend fun status(): AccountStatusResponse = api.accountStatus()

    /** Starts (or refreshes an expired) QR / login-token login; `qr_url` is the `tg://login?token=…` link. */
    suspend fun startQr(): AccountStatusResponse = api.startQrLogin()

    suspend fun startPhone(e164: String): AccountStatusResponse = api.startPhoneLogin(PhoneRequest(e164))

    suspend fun submitCode(code: String): AccountStatusResponse = api.submitCode(CodeRequest(code.filter(Char::isDigit)))

    suspend fun submitPassword(password: String): AccountStatusResponse = api.submitPassword(PasswordRequest(password))

    suspend fun logOut(): AccountStatusResponse = api.logOut()

    /** Small JPEG of the Telegram account, or null (404 when the account has no photo). */
    suspend fun avatar(): ImageBitmap? = runCatching {
        val bytes = http.execute("GET", "/api/account/avatar") { if (it.isSuccessful) it.body.bytes() else null } ?: return null
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
    }.getOrNull()
}
