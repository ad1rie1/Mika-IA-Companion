package fr.qwartz.mika.data.net

import org.junit.Assert.assertEquals
import org.junit.Test

class OutboxPolicyTest {
    @Test fun `rien à évincer sous les deux bornes`() {
        assertEquals(0, OutboxPolicy.evictions(listOf(10L, 20L), 5, maxCount = 3, maxBytes = 100))
    }

    @Test fun `la vingt et unième évince la plus ancienne`() {
        assertEquals(1, OutboxPolicy.evictions(List(20) { 1L }, 1))
    }

    @Test fun `le budget en octets évince par la tête jusqu'à faire de la place`() {
        assertEquals(2, OutboxPolicy.evictions(listOf(40L, 40L, 10L), 60, maxCount = 10, maxBytes = 100))
    }

    @Test fun `une entrée seule tient toujours, la file vidée au pire`() {
        assertEquals(3, OutboxPolicy.evictions(listOf(1L, 1L, 1L), 1000, maxCount = 10, maxBytes = 100))
        assertEquals(0, OutboxPolicy.evictions(emptyList(), 1000, maxCount = 10, maxBytes = 100))
    }
}
