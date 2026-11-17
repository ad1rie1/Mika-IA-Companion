package fr.qwartz.mika.data.moi.mail

import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.hue
import fr.qwartz.mika.data.moi.initials
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId

/** Ce que Mail écrit d'un instant, d'une taille, d'une personne et d'un texte, comme le client web. */
class MailTextTest {
    private val paris = ZoneId.of("Europe/Paris")
    private fun at(y: Int, mo: Int, d: Int, h: Int, mi: Int = 0): Long =
        LocalDateTime.of(y, mo, d, h, mi).atZone(paris).toInstant().toEpochMilli()

    private val now = at(2026, 11, 17, 14, 5) // un mardi

    @Test fun `quand, en court, comme une liste de messagerie`() {
        assertEquals("13:31", MoiDates.short(at(2026, 11, 17, 13, 31), now, paris))
        assertEquals("00:05", MoiDates.short(at(2026, 11, 17, 0, 5), now, paris))
        assertEquals("hier", MoiDates.short(at(2026, 11, 16, 23, 59), now, paris))
        assertEquals("sam.", MoiDates.short(at(2026, 11, 14, 9), now, paris))
        assertEquals("28 oct.", MoiDates.short(at(2026, 10, 28, 9), now, paris))
        assertEquals("3 déc. 2025", MoiDates.short(at(2025, 12, 3, 9), now, paris))
        assertEquals("", MoiDates.short(0, now, paris))
    }

    @Test fun `le jour et l'heure`() {
        assertEquals("aujourd'hui 13:31", MoiDates.dayAndClock(at(2026, 11, 17, 13, 31), now, paris))
        assertEquals("hier 21:41", MoiDates.dayAndClock(at(2026, 11, 16, 21, 41), now, paris))
        assertEquals("28 oct. 13:31", MoiDates.dayAndClock(at(2026, 10, 28, 13, 31), now, paris))
    }

    @Test fun `les groupes de la liste`() {
        assertEquals("Aujourd'hui", MoiDates.group(at(2026, 11, 17, 8), now, paris))
        assertEquals("Aujourd'hui", MoiDates.group(at(2026, 11, 18, 8), now, paris))
        assertEquals("Hier", MoiDates.group(at(2026, 11, 16, 8), now, paris))
        assertEquals("Cette semaine", MoiDates.group(at(2026, 11, 12, 8), now, paris))
        assertEquals("Octobre", MoiDates.group(at(2026, 10, 2, 8), now, paris))
        assertEquals("Décembre 2025", MoiDates.group(at(2025, 12, 2, 8), now, paris))
        assertEquals("Plus ancien", MoiDates.group(0, now, paris))
    }

    @Test fun `les tailles`() {
        assertEquals("512 o", sizeLabel(512))
        assertEquals("212 Ko", sizeLabel(212 * 1024))
        assertEquals("1,8 Mo", sizeLabel((1.8 * 1024 * 1024).toLong()))
        assertEquals("2 Mo", sizeLabel(2L * 1024 * 1024))
    }

    @Test fun `les initiales et la teinte, celle du client web`() {
        assertEquals("CD", initials("Claire Dubois"))
        assertEquals("NT", initials("noreply@example.test"))
        assertEquals("ÉL", initials("élodie Lambert"))
        assertEquals("?", initials("!!!"))
        assertEquals(6, hue("lea@example.test"))
        assertEquals(0, hue("c.dubois@lumen-conseil.fr"))
        assertEquals(3, hue("Adrien"))
        assertEquals(3, hue("😀x"))
    }

    @Test fun `la sorte d'une pièce`() {
        assertEquals("PDF", attachmentKind("devis-2026-114.pdf", "application/pdf"))
        assertEquals("JPEG", attachmentKind("photo", "image/jpeg"))
        assertEquals("VND", attachmentKind("sans-extension", "application/vnd.ms-excel"))
        assertEquals("FICHIER", attachmentKind("x", ""))
    }

    @Test fun `le texte d'un mail, paragraphes et citations`() {
        val body = "Salut Adrien,\r\n\r\nMerci pour la trame.\nUne remarque.\n\nLe 3 nov., Claire a écrit :\n> Voici la trame.\n> > Et la mienne.\n>\n> Fin.\n\nBonne journée"
        assertEquals(
            listOf(
                BodyBlock(0, "Salut Adrien,"),
                BodyBlock(0, "Merci pour la trame.\nUne remarque."),
                BodyBlock(0, "Le 3 nov., Claire a écrit :"),
                BodyBlock(1, "Voici la trame."),
                BodyBlock(2, "Et la mienne."),
                BodyBlock(1, "Fin."),
                BodyBlock(0, "Bonne journée"),
            ),
            bodyBlocks(body),
        )
        assertTrue(bodyBlocks("  \n\n ").isEmpty())
    }
}
