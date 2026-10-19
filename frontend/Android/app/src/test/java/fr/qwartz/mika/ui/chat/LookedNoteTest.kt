package fr.qwartz.mika.ui.chat

import fr.qwartz.mika.ui.chat.LookedNote.FixAge
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId

/** De quand datait la position qu'elle a regardée, telle que sa petite bulle le dit (ADR 0119). */
class LookedNoteTest {
    private val zone = ZoneId.of("Europe/Paris")
    private fun at(y: Int, mo: Int, d: Int, h: Int, mi: Int = 0) =
        LocalDateTime.of(y, mo, d, h, mi).atZone(zone).toInstant().toEpochMilli()

    private val reply = at(2026, 10, 19, 14, 30)

    @Test fun `une position fraîche, ou de quand on ne sait pas - rien à dire`() {
        assertEquals(FixAge.Fresh, LookedNote.age(reply, reply, zone))
        assertEquals(FixAge.Fresh, LookedNote.age(reply - LookedNote.FRESH_MS + 1, reply, zone))
        assertEquals(FixAge.Fresh, LookedNote.age(0, reply, zone))
        // une mesure « après » sa réponse (horloges décalées) n'est pas vieille
        assertEquals(FixAge.Fresh, LookedNote.age(reply + 60_000, reply, zone))
    }

    @Test fun `plus tôt le même jour - son heure, écrite et dite`() {
        assertEquals(FixAge.SameDay("14:28", "14 h 28"), LookedNote.age(reply - LookedNote.FRESH_MS, reply, zone))
        assertEquals(FixAge.SameDay("09:05", "9 h 05"), LookedNote.age(at(2026, 10, 19, 9, 5), reply, zone))
    }

    @Test fun `un autre jour - le jour aussi, l'année si elle diffère`() {
        assertEquals(
            FixAge.OtherDay("18/10", "18 octobre", "23:50", "23 h 50"),
            LookedNote.age(at(2026, 10, 18, 23, 50), at(2026, 10, 19, 0, 10), zone),
        )
        assertEquals(
            FixAge.OtherDay("31/12/2025", "31 décembre 2025", "22:00", "22 h 00"),
            LookedNote.age(at(2025, 12, 31, 22), at(2026, 1, 1, 9), zone),
        )
    }
}
