package dev.bento.feature.onboarding

import dev.bento.api.BentoJson
import dev.bento.api.generated.VaultStatusResponse
import dev.bento.testing.TrustFixtures
import java.util.Locale
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class OnboardingLogicTest {
    private fun vault(state: String, reason: String? = null) =
        BentoJson.decodeFromString(VaultStatusResponse.serializer(), TrustFixtures.vault(state = state, reason = reason))

    @Test
    fun gateDecisions() {
        assertEquals(Gate.FirstRun, decideGate(vault("signed_out"), localChosen = false))
        assertEquals(Gate.App, decideGate(vault("signed_out"), localChosen = true))
        assertEquals(Gate.Reconnect, decideGate(vault("signed_out", "session_closed"), localChosen = false))
        assertEquals(Gate.Removed, decideGate(vault("signed_out", "device_removed"), localChosen = false))
        assertEquals(Gate.FirstRun, decideGate(vault("no_vault"), localChosen = false))
        assertEquals(Gate.App, decideGate(vault("no_vault"), localChosen = true))
        assertEquals(Gate.Locked, decideGate(vault("locked"), localChosen = false))
        assertEquals(Gate.Removed, decideGate(vault("locked", "device_removed"), localChosen = false))
        assertEquals(Gate.App, decideGate(vault("ready"), localChosen = false))
        assertEquals(Gate.App, decideGate(vault("bootstrapping"), localChosen = false))
        assertEquals(Gate.App, decideGate(vault("local_only"), localChosen = false))
        assertEquals(Gate.App, decideGate(null, localChosen = false))
    }

    @Test
    fun phoneNumbers() {
        val co = PhoneNumbers.preselect("co", null)
        assertEquals("57", co.dialCode)
        assertEquals("ES", PhoneNumbers.preselect(null, null, Locale.forLanguageTag("es-ES")).iso)
        assertEquals("US", PhoneNumbers.preselect("", "us").iso)
        assertEquals("3001234567", PhoneNumbers.nationalDigits("300 123-4567", co))
        assertEquals("3001234567", PhoneNumbers.nationalDigits("+57 300 123 4567", co))
        assertEquals("3001234567", PhoneNumbers.nationalDigits("0300 123 4567", co))
        assertEquals("300 123 4567", PhoneNumbers.formatNational("3001234567"))
        assertEquals("+573001234567", PhoneNumbers.e164(co, "300 123 4567"))
        assertTrue(PhoneNumbers.isPlausible(co, "3001234567"))
        assertFalse(PhoneNumbers.isPlausible(co, "123"))
        assertEquals("🇨🇴", co.flag)
        assertEquals("Colombia", co.name(Locale.forLanguageTag("es")))
        assertTrue(PhoneNumbers.search("+57", Locale.forLanguageTag("es")).any { it.iso == "CO" })
        assertTrue(PhoneNumbers.search("alem", Locale.forLanguageTag("es")).any { it.iso == "DE" })
        assertTrue(PhoneNumbers.countries.size > 200)
    }

    @Test
    fun telegramCodesInClipboardText() {
        assertEquals("12345", telegramCodeIn("Código de inicio de sesión: 12345. No lo compartas"))
        assertEquals("123456", telegramCodeIn("123456"))
        assertNull(telegramCodeIn("1234"))
        assertNull(telegramCodeIn("12345 y 67890"))
        assertNull(telegramCodeIn("+573001234567"))
    }

    @Test
    fun loginProblems() {
        val map = mapOf(
            "telegram_code_invalid" to SignInProblem.CodeInvalid,
            "telegram_login_expired" to SignInProblem.Expired,
            "telegram_password_invalid" to SignInProblem.PasswordInvalid,
            "telegram_phone_invalid" to SignInProblem.PhoneInvalid,
            "telegram_flood_wait" to SignInProblem.FloodWait,
            "telegram_not_available" to SignInProblem.NotAvailable,
            "telegram_network" to SignInProblem.Network,
            "network_error" to SignInProblem.Network,
            "whatever" to SignInProblem.Generic
        )
        map.forEach { (code, problem) ->
            assertEquals(code, problem, TelegramSignInViewModel.problemOf(dev.bento.feature.recovery.ApiProblem(code)))
        }
    }

    @Test
    fun codeLengthAndDeliveryShapeTheCodeStep() {
        assertEquals("123456", telegramCodeIn("Tu código: 123456", length = 6))
        assertNull(telegramCodeIn("Tu código: 12345", length = 6))
        assertEquals("1234", telegramCodeIn("1234", length = 4))
        assertEquals(dev.bento.strings.R.string.onboarding_code_body_sms, codeBody("sms"))
        assertEquals(dev.bento.strings.R.string.onboarding_code_body_call, codeBody("flash_call"))
        assertEquals(dev.bento.strings.R.string.onboarding_code_body_email, codeBody("email"))
        assertEquals(dev.bento.strings.R.string.onboarding_code_body, codeBody("app"))
        assertEquals(dev.bento.strings.R.string.onboarding_code_body, codeBody(null))
    }

    @Test
    fun creationRowsFollowTheBackendSteps() {
        assertEquals(CreationRow.entries.map { RowState.Running }, CreationRow.entries.map { CreatingState().row(it) })
        val midway = CreatingState(steps = mapOf("files" to "done", "sync" to "running", "inbox" to "pending", "header" to "pending"))
        assertEquals(RowState.Running, midway.row(CreationRow.Channels))
        assertEquals(1, midway.channelsDone)
        assertEquals(RowState.Pending, midway.row(CreationRow.Keys))
        assertEquals(RowState.Pending, midway.row(CreationRow.Device))
        val header = CreatingState(steps = mapOf("files" to "done", "sync" to "done", "inbox" to "done", "header" to "failed"))
        assertEquals(RowState.Done, header.row(CreationRow.Channels))
        assertEquals(RowState.Failed, header.row(CreationRow.Keys))
        assertEquals(RowState.Failed, header.copy(failed = true).row(CreationRow.Device))
        assertEquals(RowState.Done, midway.copy(done = true).row(CreationRow.Device))
    }
}
