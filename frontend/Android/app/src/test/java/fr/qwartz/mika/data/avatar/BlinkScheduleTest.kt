package fr.qwartz.mika.data.avatar

import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

class BlinkScheduleTest {
    @Test fun `l'attente reste entre 2 et 6 secondes et demie, et ne se répète pas`() {
        val random = Random(42)
        val gaps = List(500) { BlinkSchedule.nextGapMs(random) }
        assertTrue(gaps.all { it in BlinkSchedule.MIN_GAP_MS..BlinkSchedule.MAX_GAP_MS })
        // Un rythme fixe se repère : des centaines de valeurs différentes.
        assertTrue(gaps.toSet().size > 300)
        // Rarement aux extrêmes : la moyenne tombe au milieu.
        val mean = gaps.average()
        assertTrue(mean in 3_800.0..4_800.0)
    }

    @Test fun `fatiguée, elle cligne moins souvent`() {
        val calm = Random(7).let { r -> List(300) { BlinkSchedule.nextGapMs(r) }.average() }
        val tired = Random(7).let { r -> List(300) { BlinkSchedule.nextGapMs(r, tired = true) }.average() }
        assertTrue(tired > calm * 1.4)
    }

    @Test fun `un clignement sur sept environ est double`() {
        val random = Random(3)
        val doubles = List(2_000) { BlinkSchedule.isDouble(random) }.count { it }
        assertTrue(doubles in 200..400)
    }
}
