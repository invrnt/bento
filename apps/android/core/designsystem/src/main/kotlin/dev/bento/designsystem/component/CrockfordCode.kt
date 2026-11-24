package dev.bento.designsystem.component

/**
 * Crockford Base32 codes as used for pairing (`XXXX-XXXX-XXXX`, 12 chars) and recovery (9 groups of 4, 36 chars).
 * Mirrors apps/web `pairingCode.ts` / `recoveryCode.ts`: I and L read as 1, O as 0, U and separators are dropped.
 */
public object CrockfordCode {
    public const val ALPHABET: String = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    public const val PAIRING_LENGTH: Int = 12
    public const val RECOVERY_LENGTH: Int = 36
    public const val GROUP_SIZE: Int = 4

    private val linkCode = Regex("[?#&]c=([^&#\\s]+)", RegexOption.IGNORE_CASE)
    private val bareParam = Regex("^c=([^&#\\s]+)", RegexOption.IGNORE_CASE)

    /** Maps one typed character to its canonical code character, or `null` when it is not part of a code. */
    public fun canonical(char: Char): Char? = when (val upper = char.uppercaseChar()) {
        'I', 'L' -> '1'
        'O' -> '0'
        else -> upper.takeIf { it in ALPHABET }
    }

    public fun normalize(input: String): String = buildString { input.forEach { ch -> canonical(ch)?.let(::append) } }

    /** Pulls the code out of `bento://join?v=1&c=…`, `https://…/join#v=1&c=…` or `c=…`; otherwise returns the input. */
    public fun extract(input: String): String {
        val raw = input.trim()
        if (!raw.contains("://") && !raw.contains("c=", ignoreCase = true)) return raw
        val match = linkCode.find(raw) ?: bareParam.find(raw) ?: return raw
        val value = match.groupValues[1]
        return runCatching { java.net.URLDecoder.decode(value, "UTF-8") }.getOrDefault(value)
    }

    /** Groups an already-normalized code: `ABCD-EFGH-JK`. */
    public fun format(code: String, groupSize: Int = GROUP_SIZE): String = code.chunked(groupSize).joinToString("-")

    /** Live input handling: accepts codes and pasted links, returns normalized characters capped at [length]. */
    public fun fromInput(input: String, length: Int): String = normalize(extract(input)).take(length)

    public fun isComplete(code: String, length: Int): Boolean = normalize(code).length == length

    /**
     * Normalizes an edit and keeps the cursor next to the same character: the new cursor counts the code characters
     * typed before the old one. A pasted link moves the cursor to the end.
     */
    public fun normalizeEdit(text: String, cursor: Int, length: Int): Pair<String, Int> {
        val extracted = extract(text)
        if (extracted != text.trim()) {
            val code = normalize(extracted).take(length)
            return code to code.length
        }
        val code = normalize(text).take(length)
        val before = normalize(text.substring(0, cursor.coerceIn(0, text.length))).length
        return code to before.coerceAtMost(code.length)
    }
}
