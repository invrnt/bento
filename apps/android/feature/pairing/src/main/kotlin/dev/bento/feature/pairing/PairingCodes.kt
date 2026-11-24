package dev.bento.feature.pairing

import dev.bento.designsystem.component.CrockfordCode

/** Pairing codes `NNNN-SSSS-SSSS` and their links (architecture/telegram-first.md § Code format). */
object PairingCodes {
    const val LENGTH: Int = CrockfordCode.PAIRING_LENGTH
    private val formatted = Regex("^[0-9A-Za-z]{4}-[0-9A-Za-z]{4}-[0-9A-Za-z]{4}$")

    /** A scanned QR or pasted text that carries a pairing code (link or `XXXX-XXXX-XXXX`), normalized; else null. */
    fun fromScanOrPaste(raw: String): String? {
        val value = raw.trim()
        val isLink =
            value.startsWith("bento://join", ignoreCase = true) ||
                Regex("^https://[^/]+/join", RegexOption.IGNORE_CASE).containsMatchIn(value)
        if (!isLink && !formatted.matches(value)) return null
        val code = CrockfordCode.normalize(CrockfordCode.extract(value))
        return code.takeIf { it.length == LENGTH }
    }

    fun format(code: String): String = CrockfordCode.format(CrockfordCode.normalize(code))
}
