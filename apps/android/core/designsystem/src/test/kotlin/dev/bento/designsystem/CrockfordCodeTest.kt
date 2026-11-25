package dev.bento.designsystem

import dev.bento.designsystem.component.CrockfordCode
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CrockfordCodeTest {
    @Test
    fun normalizesAmbiguousCharacters() {
        assertEquals("11001", CrockfordCode.normalize("iLoO1"))
        assertEquals("ABCD", CrockfordCode.normalize("ab-c d"))
        assertEquals("", CrockfordCode.normalize("uU*_"))
    }

    @Test
    fun extractsCodesFromLinks() {
        assertEquals("7KQ2-M9XW-D4PH", CrockfordCode.extract("bento://join?v=1&c=7KQ2-M9XW-D4PH"))
        assertEquals("7kq2m9xwd4ph", CrockfordCode.extract("https://bento.example/join#v=1&c=7kq2m9xwd4ph"))
        assertEquals("ABCD", CrockfordCode.extract("c=ABCD"))
        assertEquals("ABCD-EFGH", CrockfordCode.extract("ABCD-EFGH"))
        assertEquals("7KQ2 M9XW", CrockfordCode.extract("bento://join?c=7KQ2%20M9XW"))
    }

    @Test
    fun formatsAndCapsInput() {
        assertEquals("7KQ2M9XWD4PH", CrockfordCode.fromInput("https://x/join#v=1&c=7kq2-m9xw-d4ph-extra", 12))
        assertEquals("ABCD-EFGH-JK", CrockfordCode.format("ABCDEFGHJK"))
        assertTrue(CrockfordCode.isComplete("7KQ2-M9XW-D4PH", 12))
        assertFalse(CrockfordCode.isComplete("7KQ2-M9XW", 12))
        assertEquals(36, CrockfordCode.fromInput("A".repeat(40), CrockfordCode.RECOVERY_LENGTH).length)
    }

    @Test
    fun keepsTheCursorOnTheSameCharacter() {
        // Typing "u" (not in the alphabet) at position 2 of "ABCD" drops it and keeps the cursor at 2.
        assertEquals("ABCD" to 2, CrockfordCode.normalizeEdit("ABuCD", 3, 12))
        // Typing "o" becomes "0" and the cursor advances past it.
        assertEquals("AB0CD" to 3, CrockfordCode.normalizeEdit("ABoCD", 3, 12))
        // A pasted link moves the cursor to the end.
        assertEquals("7KQ2M9XWD4PH" to 12, CrockfordCode.normalizeEdit("bento://join?c=7KQ2-M9XW-D4PH", 5, 12))
    }
}
