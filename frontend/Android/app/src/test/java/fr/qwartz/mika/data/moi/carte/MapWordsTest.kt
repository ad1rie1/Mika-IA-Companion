package fr.qwartz.mika.data.moi.carte

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZonedDateTime

/** Les mots d'une carte : les mêmes cas que `frontendv2/src/map/words.test.ts`. */
class MapWordsTest {
    private val zone = ZoneId.of("Europe/Paris")
    private val now = ZonedDateTime.of(2026, 11, 5, 14, 0, 0, 0, zone).toInstant().toEpochMilli()

    @Test fun `les distances, des mètres, une décimale sous 10 km, des milliers insécables`() {
        assertEquals("850 m", km(847.0))
        assertEquals("5,8 km", km(5_830.0))
        assertEquals("7 km", km(7_000.0))
        assertEquals("58 km", km(58_015.0))
        assertEquals("1 388 km", km(1_388_400.0))
        assertEquals("", km(null))
        assertEquals("", km(-1.0))
    }

    @Test fun `les durées, minutes, puis heures et minutes`() {
        assertEquals("1 min", duration(20.0))
        assertEquals("45 min", duration(45 * 60.0))
        assertEquals("7 h 05", duration(7 * 3600 + 5 * 60.0))
        assertEquals("16 h", duration(16 * 3600.0))
        assertEquals("", duration(null))
    }

    @Test fun `le mode et ce qu'un trajet évite`() {
        assertEquals("à vélo", modeWords("velo"))
        assertEquals("péages acceptés", avoidWords(emptyList()))
        assertEquals("", avoidWords(emptyList(), "pied"))
        assertEquals("sans autoroute", avoidWords(listOf("autoroutes")))
        assertEquals("sans péage, autoroute ni ferry", avoidWords(listOf("peages", "autoroutes", "ferries")))
        // une seule table des options d'un trajet en voiture, dans l'ordre de l'API
        assertEquals(AVOIDS, AVOID_LABELS.keys.toList())
        assertEquals(listOf("les péages", "les autoroutes", "les ferries"), AVOID_LABELS.values.toList())
        assertEquals(MODES, MODE_LABELS.keys.toList())
    }

    @Test fun `les jours d'un voyage`() {
        assertEquals(java.time.DayOfWeek.SATURDAY, isoDay("2027-04-03")?.dayOfWeek)
        assertNull(isoDay("2027-02-30"))
        assertEquals("2027-04-03", isoOf(LocalDate.of(2027, 4, 3)))
        assertEquals("sam. 21 novembre", dayLabel("2026-11-21", now, zone))
        assertEquals("sam. 3 avril 2027", dayLabel("2027-04-03", now, zone))
        assertEquals("du sam. 3 au mer. 7 avril 2027", tripDates("2027-04-03", 5, now, zone))
        assertEquals("sam. 21 et dim. 22 novembre", tripDates("2026-11-21", 2, now, zone))
        assertEquals("sam. 31 octobre et dim. 1er novembre · passé", tripDates("2026-10-31", 2, now, zone))
        assertTrue(tripPast("2026-10-31", 2, now, zone))
        assertEquals("du lun. 30 novembre au mer. 2 décembre", tripDates("2026-11-30", 3, now, zone))
        assertEquals("", tripDates("", 3, now, zone))
    }

    @Test fun `les jours d'un voyage en court, pour le menu « Ajouter au voyage »`() {
        assertEquals("3–7 avr. 2027", tripSpan("2027-04-03", 5, now, zone))
        val january = ZonedDateTime.of(2027, 1, 10, 12, 0, 0, 0, zone).toInstant().toEpochMilli()
        assertEquals("3–7 avr.", tripSpan("2027-04-03", 5, january, zone))
        assertEquals("30 mars–2 avr. 2027", tripSpan("2027-03-30", 4, now, zone))
        assertEquals("21–22 nov.", tripSpan("2026-11-21", 2, now, zone))
        assertEquals("21 nov.", tripSpan("2026-11-21", 1, now, zone))
        assertEquals("21 nov.", tripSpan("2026-11-21", 0, now, zone))
        assertEquals("30 nov.–2 déc.", tripSpan("2026-11-30", 3, now, zone))
        assertEquals("30 déc.–2 janv. 2027", tripSpan("2026-12-30", 4, now, zone))
        assertEquals("31 oct.–1er nov.", tripSpan("2026-10-31", 2, now, zone))
        assertEquals("", tripSpan("", 3, now, zone))
    }

    @Test fun `l'arrivée, le pluriel et ce qu'est un lieu`() {
        assertEquals("arrivée vers 15:35 si tu pars maintenant", arrival(now, 95 * 60.0, zone))
        assertEquals("", arrival(now, 0.0, zone))
        assertEquals("1 jour", plural(1, "jour"))
        assertEquals("3 lieux", plural(3, "lieu", "lieux"))
        assertEquals("1 388 lieux", plural(1388, "lieu", "lieux"))
        assertEquals("Camping · Sévrier", placeWhat(Place(kindFr = "Camping", town = "Sévrier")))
        assertEquals("Adresse · Paris", placeWhat(Place(category = "adresse", town = "Paris")))
        assertEquals("", placeWhat(Place()))
    }
}
