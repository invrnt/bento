package dev.bento.testing

/**
 * JSON bodies of the Telegram-first API (api/telegram-first-endpoints.md) for [FakeApiTransport] routes: vault,
 * account, pairing, devices, sync. Decoded by the generated DTOs, so schema drift breaks the tests that use them.
 */
object TrustFixtures {
    const val RECOVERY_CODE = "K7QM3XRA9TQWPEBZ0F4HCNDV8GMJ2KS6YPRT"

    private fun str(value: String?) = if (value == null) "null" else "\"$value\""

    fun vault(
        state: String = "ready",
        reason: String? = null,
        saved: Boolean = false,
        stale: Boolean = false,
        createdAt: String? = "2026-11-24T10:00:00+00:00",
        vaultId: String? = "vlt_1"
    ) = """{"state":"$state","vault_id":${str(vaultId)},"created_at":${str(createdAt)},"recovery_kit_saved":$saved,""" +
        """"recovery_kit_stale":$stale,"devices_count":2,"usage":{"files":10,"bytes":1000},"other_vaults":0,"reason":${str(reason)}}"""

    const val QR = """{"size":3,"rows":["101","010","101"]}"""

    fun createdVault(code: String = RECOVERY_CODE) = """{"vault":${vault(state = "ready")},"recovery_code":"$code","recovery_qr":$QR}"""

    fun recoveryCode(code: String = RECOVERY_CODE) = """{"recovery_code":"$code","recovery_qr":$QR}"""

    fun account(
        step: String,
        error: String? = null,
        retryAfter: Long? = null,
        qrUrl: String? = null,
        hint: String? = null,
        expiresAt: String? = null
    ): String {
        val account = if (step ==
            "authorized"
        ) {
            """{"user_id":1,"display_name":"Ana","username":"ana","phone_masked":"+57 ••• 12","premium":false}"""
        } else {
            "null"
        }
        val details = retryAfter?.let { ""","details":{"retry_after_seconds":$it}""" }.orEmpty()
        val err = error?.let { """{"code":"$it","message":"$it"$details}""" } ?: "null"
        val qr = if (step == "qr_pending") QR else "null"
        return """{"step":"$step","account":$account,"qr_url":${str(qrUrl)},"qr":$qr,"qr_expires_at":${str(expiresAt)},""" +
            """"password_hint":${str(hint)},"error":$err}"""
    }

    fun pairing(
        state: String,
        role: String = "guest",
        transport: String = "relay",
        sas: List<String>? = null,
        error: String? = null,
        peer: String? = "Portátil de Ana",
        platform: String = "linux",
        code: String? = null,
        vault: Boolean = false,
        id: String = "pair_1",
        expiresAt: String = "2099-01-01T00:00:00+00:00",
        telegramQr: Boolean = false
    ): String {
        val sasJson = sas?.joinToString(",", "[", "]") { "\"$it\"" } ?: "null"
        val peerJson = peer?.let { """{"device_name":"$it","platform":"$platform"}""" } ?: "null"
        val err = error?.let { """{"code":"$it","message":"$it"}""" } ?: "null"
        val vaultJson = if (vault) """{"created_at":"2025-03-12T10:00:00+00:00","devices_count":3}""" else "null"
        val link = code?.let { "\"bento://join?v=1&c=$it\"" } ?: "null"
        return """{"id":"$id","role":"$role","transport":"$transport","state":"$state","code":${str(code)},"link":$link,""" +
            """"web_link":null,"qr":${if (code != null) QR else "null"},"expires_at":"$expiresAt","peer":$peerJson,"sas":$sasJson,""" +
            """"telegram_qr":${if (telegramQr) QR else "null"},"error":$err,"vault":$vaultJson}"""
    }

    val SAS = listOf("🐙", "🌵", "🎈", "🚀")

    fun device(
        id: String,
        name: String,
        platform: String = "linux",
        current: Boolean = false,
        needsReview: Boolean = false,
        lastSeen: String? = "2026-11-24T09:00:00+00:00"
    ) = """{"id":"$id","name":"$name","platform":"$platform","added_at":"2026-10-01T10:00:00+00:00","last_seen_at":${str(lastSeen)},""" +
        """"current":$current,"removed_at":null,"introduced_by":null,"first_seen_at":"2026-11-20T10:00:00+00:00","needs_review":$needsReview}"""

    fun devices(vararg items: String) = items.joinToString(",", """{"items":[""", "]}")

    fun sync(state: String = "idle", done: Long? = null, total: Long? = null): String {
        val bootstrap = if (done != null && total != null) """{"done":$done,"total":$total}""" else "null"
        return """{"state":"$state","pending_ops":0,"last_push_at":null,"last_pull_at":null,"bootstrap":$bootstrap,""" +
            """"waiting_until":null,"error":null}"""
    }
}
