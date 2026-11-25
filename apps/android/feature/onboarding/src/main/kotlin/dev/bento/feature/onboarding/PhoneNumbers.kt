package dev.bento.feature.onboarding

import java.text.Collator
import java.util.Locale

/** A country of the phone picker: ISO 3166 code, calling code, localized name and flag. */
data class Country(val iso: String, val dialCode: String) {
    fun name(
        locale: Locale = Locale.getDefault()
    ): String = Locale.Builder().setRegion(iso).build().getDisplayCountry(locale).ifBlank { iso }

    /** Regional-indicator flag emoji (decorative). */
    val flag: String get() = iso.uppercase(Locale.ROOT).map { Character.toChars(0x1F1E6 + (it - 'A')).concatToString() }.joinToString("")
}

/**
 * Phone entry for Telegram sign-in (product/android.md §4.1 step 2): a country picker preselected from the SIM or
 * the locale, the national number formatted while typing, and E.164 for `POST /account/login/phone`.
 * Formatting is deliberately simple (groups of 3-4); Telegram validates the number.
 */
object PhoneNumbers {
    private val codes: Map<String, String> = DIAL_CODES.split(' ').associate { entry ->
        val (iso, code) = entry.split(':')
        iso to code
    }

    val countries: List<Country> = codes.map { (iso, code) -> Country(iso, code) }

    fun country(iso: String?): Country? = iso?.uppercase(Locale.ROOT)?.let { key -> codes[key]?.let { Country(key, it) } }

    /** SIM country first, then network, then the locale; Colombia when nothing is known (the product's first market). */
    fun preselect(simIso: String?, networkIso: String?, locale: Locale = Locale.getDefault()): Country =
        country(simIso) ?: country(networkIso) ?: country(locale.country) ?: Country("CO", "57")

    fun sorted(locale: Locale = Locale.getDefault()): List<Country> {
        val collator = Collator.getInstance(locale)
        return countries.sortedWith { a, b -> collator.compare(a.name(locale), b.name(locale)) }
    }

    fun search(query: String, locale: Locale = Locale.getDefault()): List<Country> {
        val q = query.trim().removePrefix("+").lowercase(locale)
        if (q.isEmpty()) return sorted(locale)
        return sorted(locale).filter {
            it.name(locale).lowercase(locale).contains(q) || it.dialCode.startsWith(q) || it.iso.lowercase() == q
        }
    }

    /** Only digits, without a trunk `0` that some people type out of habit, at most 15 minus the country code. */
    fun nationalDigits(input: String, country: Country): String {
        val digits = input.filter(Char::isDigit)
        val withoutCode = if (input.trim().startsWith("+") &&
            digits.startsWith(country.dialCode)
        ) {
            digits.removePrefix(country.dialCode)
        } else {
            digits
        }
        return withoutCode.trimStart('0').take(MAX_E164 - country.dialCode.length)
    }

    /** "300 123 4567": groups of 3 then the remainder, readable while typing. */
    fun formatNational(digits: String): String = when {
        digits.length <= 3 -> digits
        digits.length <= 6 -> "${digits.take(3)} ${digits.drop(3)}"
        else -> "${digits.take(3)} ${digits.substring(3, 6)} ${digits.drop(6)}"
    }

    fun e164(country: Country, national: String): String = "+${country.dialCode}${national.filter(Char::isDigit)}"

    fun isPlausible(country: Country, national: String): Boolean =
        national.filter(Char::isDigit).length in MIN_NATIONAL..(MAX_E164 - country.dialCode.length)

    private const val MAX_E164 = 15
    private const val MIN_NATIONAL = 6
}

// ISO 3166-1 alpha-2 : ITU calling code (NANP members share +1; Kazakhstan shares +7 with Russia).
private const val DIAL_CODES =
    "AF:93 AL:355 DZ:213 AD:376 AO:244 AG:1 AR:54 AM:374 AW:297 AU:61 AT:43 AZ:994 BS:1 BH:973 BD:880 BB:1 BY:375 " +
        "BE:32 BZ:501 BJ:229 BT:975 BO:591 BA:387 BW:267 BR:55 BN:673 BG:359 BF:226 BI:257 KH:855 CM:237 CA:1 CV:238 " +
        "CF:236 TD:235 CL:56 CN:86 CO:57 KM:269 CG:242 CD:243 CR:506 CI:225 HR:385 CU:53 CW:599 CY:357 CZ:420 DK:45 " +
        "DJ:253 DM:1 DO:1 EC:593 EG:20 SV:503 GQ:240 ER:291 EE:372 SZ:268 ET:251 FJ:679 FI:358 FR:33 GF:594 PF:689 " +
        "GA:241 GM:220 GE:995 DE:49 GH:233 GR:30 GL:299 GD:1 GP:590 GU:1 GT:502 GN:224 GW:245 GY:592 HT:509 HN:504 " +
        "HK:852 HU:36 IS:354 IN:91 ID:62 IR:98 IQ:964 IE:353 IL:972 IT:39 JM:1 JP:81 JO:962 KZ:7 KE:254 KI:686 " +
        "XK:383 KW:965 KG:996 LA:856 LV:371 LB:961 LS:266 LR:231 LY:218 LI:423 LT:370 LU:352 MO:853 MG:261 MW:265 " +
        "MY:60 MV:960 ML:223 MT:356 MH:692 MQ:596 MR:222 MU:230 YT:262 MX:52 FM:691 MD:373 MC:377 MN:976 ME:382 " +
        "MA:212 MZ:258 MM:95 NA:264 NR:674 NP:977 NL:31 NC:687 NZ:64 NI:505 NE:227 NG:234 KP:850 MK:389 NO:47 OM:968 " +
        "PK:92 PW:680 PS:970 PA:507 PG:675 PY:595 PE:51 PH:63 PL:48 PT:351 PR:1 QA:974 RE:262 RO:40 RU:7 RW:250 " +
        "KN:1 LC:1 VC:1 WS:685 SM:378 ST:239 SA:966 SN:221 RS:381 SC:248 SL:232 SG:65 SX:1 SK:421 SI:386 SB:677 " +
        "SO:252 ZA:27 KR:82 SS:211 ES:34 LK:94 SD:249 SR:597 SE:46 CH:41 SY:963 TW:886 TJ:992 TZ:255 TH:66 TL:670 " +
        "TG:228 TO:676 TT:1 TN:216 TR:90 TM:993 UG:256 UA:380 AE:971 GB:44 US:1 UY:598 UZ:998 VU:678 VA:39 VE:58 " +
        "VN:84 YE:967 ZM:260 ZW:263"
