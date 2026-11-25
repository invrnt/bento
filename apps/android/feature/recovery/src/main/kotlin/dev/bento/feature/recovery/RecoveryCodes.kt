package dev.bento.feature.recovery

import dev.bento.api.generated.QrMatrix as QrDto
import dev.bento.designsystem.component.CrockfordCode
import dev.bento.designsystem.component.QrMatrix

/** Recovery codes: 36 Crockford Base32 characters shown as 9 groups of 4 (architecture/telegram-first.md). */
object RecoveryCodes {
    const val LENGTH: Int = CrockfordCode.RECOVERY_LENGTH
    const val GROUP: Int = CrockfordCode.GROUP_SIZE
    const val SCHEME: String = "bento-recovery:"

    fun groups(code: String): List<String> = CrockfordCode.normalize(code).chunked(GROUP)

    fun format(code: String): String = groups(code).joinToString("-")

    fun lastGroup(code: String): String = groups(code).lastOrNull().orEmpty()

    fun matchesLastGroup(code: String, typed: String): Boolean {
        val expected = lastGroup(code)
        return expected.isNotEmpty() && CrockfordCode.normalize(typed) == expected
    }

    /** The kit's QR payload `bento-recovery:<code>`; anything else (a pairing link, a URL) is not a recovery code. */
    fun fromScan(raw: String): String? {
        val value = raw.trim()
        if (!value.startsWith(SCHEME, ignoreCase = true)) return null
        val code = CrockfordCode.normalize(value.substring(SCHEME.length))
        return code.takeIf { it.length == LENGTH }
    }

    /** Typos caught by the checksum vs. a valid code of another vault (web `recoveryErrorKey`). */
    fun isChecksumProblem(code: String): Boolean = Regex("checksum|format|malformed|validation_failed").containsMatchIn(code)
}

/** Backend QR (`{size, rows}`) to the design-system matrix. */
fun QrDto.toMatrix(): QrMatrix = QrMatrix.fromRows(rows)
