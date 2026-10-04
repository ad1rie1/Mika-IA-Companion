package fr.qwartz.mika.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class RedactTest {
    @Test fun `un jeton n'atteint jamais un journal`() {
        val line = Redact.secrets("échec avec Authorization: Bearer mw_AbC-123_xyz pour mw_Zz9")
        assertFalse(line.contains("AbC-123"))
        assertFalse(line.contains("Zz9"))
        assertEquals("échec avec Authorization: Bearer … pour mw_…", line)
    }
}
