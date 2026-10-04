package fr.qwartz.mika.data.net

import org.junit.Assert.assertEquals
import org.junit.Test

class TimestampTest {
    private val now = 1_759_572_000_000L

    @Test fun `des millisecondes restent telles quelles`() {
        assertEquals(1_759_572_000_123L, Timestamps.normalize(1_759_572_000_123.0, now))
        assertEquals(1_759_572_000_123L, Timestamps.normalize(1_759_572_000_123.7, now))
    }

    @Test fun `des secondes, des microsecondes ou des nanosecondes sont ramenées en millisecondes`() {
        assertEquals(1_759_572_000_000L, Timestamps.normalize(1_759_572_000.0, now))
        assertEquals(1_759_572_000_500L, Timestamps.normalize(1_759_572_000.5, now))
        assertEquals(1_759_572_000_123L, Timestamps.normalize(1_759_572_000_123_456.0, now))
        assertEquals(1_759_572_000_123L, Timestamps.normalize(1_759_572_000_123_456_789.0, now))
    }

    @Test fun `rien, zéro ou négatif vaut maintenant`() {
        assertEquals(now, Timestamps.normalize(null, now))
        assertEquals(now, Timestamps.normalize(0.0, now))
        assertEquals(now, Timestamps.normalize(-5.0, now))
        assertEquals(now, Timestamps.normalize(Double.NaN, now))
    }
}
