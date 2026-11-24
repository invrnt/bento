package dev.bento.feature.recovery

import dev.bento.api.ApiErrors
import dev.bento.api.ApiException
import dev.bento.testing.TrustFixtures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RecoveryLogicTest {
    private val code = TrustFixtures.RECOVERY_CODE

    @Test
    fun groupsAndLastGroup() {
        val groups = RecoveryCodes.groups(RecoveryCodes.format(code))
        assertEquals(9, groups.size)
        assertEquals("YPRT", RecoveryCodes.lastGroup(code))
        assertEquals("K7QM-3XRA-9TQW-PEBZ-0F4H-CNDV-8GMJ-2KS6-YPRT", RecoveryCodes.format(code))
    }

    @Test
    fun lastGroupMatchIsCaseAndAliasInsensitive() {
        assertTrue(RecoveryCodes.matchesLastGroup(code, "yprt"))
        assertTrue(RecoveryCodes.matchesLastGroup("${code.dropLast(4)}10AB", "lOab")) // l→1, O→0
        assertFalse(RecoveryCodes.matchesLastGroup(code, "YPRX"))
        assertFalse(RecoveryCodes.matchesLastGroup("", "YPRT"))
    }

    @Test
    fun scannedKitPayloads() {
        assertEquals(code, RecoveryCodes.fromScan("bento-recovery:${RecoveryCodes.format(code)}"))
        assertEquals(code, RecoveryCodes.fromScan("BENTO-RECOVERY:$code"))
        assertNull(RecoveryCodes.fromScan("bento://join?v=1&c=K7Q2-MXR9-T4WA"))
        assertNull(RecoveryCodes.fromScan("bento-recovery:SHORT"))
        assertNull(RecoveryCodes.fromScan(code))
    }

    @Test
    fun checksumProblemsAreTypos() {
        assertTrue(RecoveryCodes.isChecksumProblem("recovery_checksum_invalid"))
        assertTrue(RecoveryCodes.isChecksumProblem("validation_failed"))
        assertFalse(RecoveryCodes.isChecksumProblem("recovery_code_invalid"))
    }

    @Test
    fun apiProblemsCarryCodeAndFloodWait() {
        val http = ApiErrors.from(429, """{"error":{"code":"telegram_flood_wait","message":"x","details":{"retry_after_seconds":180}}}""")
        val problem = ApiProblem.from(http)
        assertEquals("telegram_flood_wait", problem.code)
        assertEquals(180L, problem.retryAfterSeconds)
        assertEquals(ApiProblem.NETWORK, ApiProblem.from(ApiException.Network(java.io.IOException("x"))).code)
        assertTrue(ApiProblem.from(ApiException.Stalled()).isNetwork)
        assertEquals(ApiProblem.ENGINE, ApiProblem.from(ApiException.EngineUnavailable()).code)
    }

    @Test
    fun unlockErrorMapping() {
        assertEquals(UnlockError.Checksum, RecoveryEntryViewModel.unlockError(ApiProblem("recovery_checksum_invalid")))
        assertEquals(UnlockError.Invalid, RecoveryEntryViewModel.unlockError(ApiProblem("recovery_code_invalid")))
        assertEquals(UnlockError.Failed, RecoveryEntryViewModel.unlockError(ApiProblem(ApiProblem.NETWORK)))
    }

    @Test
    fun datesAreLocalized() {
        assertEquals("24 de noviembre de 2026", TrustDates.long("2026-11-24T10:00:00+00:00", java.util.Locale.forLanguageTag("es-ES")))
        assertNull(TrustDates.long("not a date"))
    }
}
