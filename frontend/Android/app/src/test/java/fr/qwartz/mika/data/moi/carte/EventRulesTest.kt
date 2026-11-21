package fr.qwartz.mika.data.moi.carte

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.moi.Tone
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.util.TimeZone

/**
 * Carte › Événements (ADR 0259) : quand chercher (aujourd'hui, ce week-end, cette semaine, des dates), les groupes par
 * jour et la ligne d'un événement, le jour d'un voyage où il tombe, son prix et ses thèmes, la fiche d'un événement et
 * qui l'a écrite.
 */
class EventRulesTest {
    private val paris: ZoneId = ZoneId.of("Europe/Paris")

    /** Midi, à Paris, ce jour-là. */
    private fun at(iso: String): Long = LocalDate.parse(iso).atTime(12, 0).atZone(paris).toInstant().toEpochMilli()

    /** Le vendredi 20 novembre 2026. */
    private val friday = at("2026-11-20")
    private val themes = listOf(Category("concerts", "Concerts"), Category("spectacles", "Spectacles"), Category("expositions", "Expositions"))

    private fun ev(id: String, start: String, whenText: String = "", free: Boolean? = null, price: String = "") =
        EventItem(id = id, name = id, start = start, whenText = whenText, free = free, price = price)

    /**
     * R2-A09 : les dates des événements sont à l'heure de Paris ; un téléphone réglé sur un autre fuseau (en voyage, un
     * réglage) cherche et nomme les jours de Paris — pas les siens.
     */
    @Test fun `les jours se comptent à l'heure de Paris, quel que soit le fuseau du téléphone`() {
        val before = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("America/New_York"))
            // 00:30 le dimanche 22 à Paris, 18:30 le samedi 21 à New York
            val night = Instant.parse("2026-11-21T23:30:00Z").toEpochMilli()
            assertEquals(DayRange("2026-11-22", "2026-11-22"), whenRange(WhenKind.TODAY, night))
            assertEquals(DayRange("2026-11-22", "2026-11-22"), whenRange(WhenKind.WEEKEND, night))
            assertEquals("Aujourd'hui · dimanche 22 novembre", dayHeading("2026-11-22", night))
            assertEquals(listOf("Demain · lundi 23 novembre"), eventDays(listOf(ev("a", "2026-11-23")), night).map { it.title })
        } finally {
            TimeZone.setDefault(before)
        }
    }

    @Test fun `aujourd'hui, ce week-end, cette semaine, chaque jour de la semaine`() {
        assertEquals(DayRange("2026-11-20", "2026-11-20"), whenRange(WhenKind.TODAY, friday, paris))
        assertEquals(DayRange("2026-11-21", "2026-11-22"), whenRange(WhenKind.WEEKEND, friday, paris))
        assertEquals(DayRange("2026-11-20", "2026-11-22"), whenRange(WhenKind.WEEK, friday, paris))
        // un lundi : la semaine jusqu'au dimanche, le week-end qui vient
        assertEquals(DayRange("2026-11-16", "2026-11-22"), whenRange(WhenKind.WEEK, at("2026-11-16"), paris))
        assertEquals(DayRange("2026-11-21", "2026-11-22"), whenRange(WhenKind.WEEKEND, at("2026-11-16"), paris))
        // un samedi : lui et demain
        assertEquals(DayRange("2026-11-21", "2026-11-22"), whenRange(WhenKind.WEEKEND, at("2026-11-21"), paris))
        assertEquals(DayRange("2026-11-21", "2026-11-22"), whenRange(WhenKind.WEEK, at("2026-11-21"), paris))
        // un dimanche : lui seul pour le week-end, la semaine qui vient pour la semaine
        assertEquals(DayRange("2026-11-22", "2026-11-22"), whenRange(WhenKind.WEEKEND, at("2026-11-22"), paris))
        assertEquals(DayRange("2026-11-22", "2026-11-29"), whenRange(WhenKind.WEEK, at("2026-11-22"), paris))
    }

    @Test fun `des dates, remises dans l'ordre, une seule, aucune`() {
        assertEquals(DayRange("2026-11-21", "2026-11-28"), whenRange(WhenKind.DATES, friday, paris, DayRange("2026-11-28", "2026-11-21")))
        assertEquals(DayRange("2026-12-05", "2026-12-05"), whenRange(WhenKind.DATES, friday, paris, DayRange("", "2026-12-05")))
        assertEquals(DayRange("2026-11-20", "2026-11-26"), whenRange(WhenKind.DATES, friday, paris, DayRange("2026-02-30", "")))
        assertEquals("du 21 au 28 nov.", rangeWords(DayRange("2026-11-21", "2026-11-28"), friday, paris))
        assertEquals("du 30 nov. au 2 déc.", rangeWords(DayRange("2026-11-30", "2026-12-02"), friday, paris))
        assertEquals("5 déc.", rangeWords(DayRange("2026-12-05", "2026-12-05"), friday, paris))
    }

    @Test fun `les jours de la liste, leur tête, leur ordre, une date illisible à la fin`() {
        val events = listOf(
            ev("b", "2026-11-21T19:00:00+01:00", "sam. 21 nov. · 19:00–22:00"),
            ev("x", "bientôt"),
            ev("a", "2026-11-20T20:00:00+01:00", "ven. 20 nov. · 20:00"),
            ev("c", "2026-11-23", "du mar. au dim. · 13:00–19:00"),
            ev("b2", "2026-11-21", "sam. 21 nov."),
        )
        val days = eventDays(events, friday, paris)
        assertEquals(listOf("2026-11-20", "2026-11-21", "2026-11-23", ""), days.map { it.day })
        assertEquals(listOf("Aujourd'hui · vendredi 20 novembre", "Demain · samedi 21 novembre", "Lundi 23 novembre", "Plus tard"), days.map { it.title })
        // dans un jour, l'ordre du serveur
        assertEquals(listOf("b", "b2"), days[1].events.map { it.id })
        assertEquals("Mardi 1er décembre", dayHeading("2026-12-01", friday, paris))
        assertEquals("Vendredi 1er janvier 2027", dayHeading("2027-01-01", friday, paris))
    }

    @Test fun `sous la tête de son jour, son quand ne redit pas le jour`() {
        assertEquals("19:00–22:00", whenInDay(ev("b", "2026-11-21T19:00:00+01:00", "sam. 21 nov. · 19:00–22:00")))
        assertEquals("du mar. au dim. · 13:00–19:00", whenInDay(ev("c", "2026-11-23", "du mar. au dim. · 13:00–19:00")))
        assertEquals("10:00", whenInDay(ev("d", "2026-11-01", "dim. 1er nov. · 10:00")))
        val e = ev("b", "2026-11-21T19:00:00+01:00", "sam. 21 nov. · 19:00–22:00").copy(themes = listOf("spectacles", "concerts"), place = "L'Aéronef, Lille")
        assertEquals("Spectacles · 19:00–22:00 · L'Aéronef, Lille", eventLine(e, themes, inDay = true))
        assertEquals("Spectacles · sam. 21 nov. · 19:00–22:00 · L'Aéronef, Lille", eventLine(e, themes, inDay = false))
        assertEquals("Spectacles, Concerts", themeWords(e.themes, themes))
        assertEquals("", themeWords(listOf("inconnu"), themes))
    }

    @Test fun `son prix, gratuit sans le redire, ses tarifs, ou rien`() {
        assertEquals("Gratuit", priceWords(ev("a", "", free = true)))
        assertEquals("Gratuit pour tous", priceWords(ev("a", "", free = true, price = "gratuit pour tous")))
        assertEquals("Gratuit · Libre participation", priceWords(ev("a", "", free = true, price = "Libre participation")))
        assertEquals("12/8€", priceWords(ev("a", "", free = false, price = "12/8€")))
        assertEquals("", priceWords(ev("a", "", free = null)))
    }

    @Test fun `le jour d'un voyage où tombe un événement`() {
        val e = ev("a", "2026-11-21T19:00:00+01:00")
        assertEquals(2, eventTripDay("2026-11-20", 3, e))
        assertEquals(1, eventTripDay("2026-11-21", 1, e))
        assertEquals(-1, eventTripDay("2026-11-22", 3, e))
        assertEquals(-1, eventTripDay("2026-11-18", 2, e))
        assertEquals(-1, eventTripDay("", 3, e))
        assertEquals(-1, eventTripDay("2026-11-20", 3, ev("x", "bientôt")))
    }

    @Test fun `la phrase pour Mika, et l'événement comme lieu d'un voyage`() {
        val e = ev("a", "2026-11-21", "sam. 21 nov. · 19:00").copy(name = "Éclats du rire !", place = "L'Aéronef, Lille", lat = 50.63, lon = 3.07)
        assertEquals("Tu as vu « Éclats du rire ! » (sam. 21 nov. · 19:00, L'Aéronef, Lille) ? ", askAboutEvent(e))
        val p = eventAsPlace(e)
        assertEquals("Éclats du rire !", p.name)
        assertEquals(LatLon(50.63, 3.07), p.at)
        assertEquals(listOf("a"), eventPins(listOf(e, ev("sans", "")), sel = "a", mika = false).map { it.id })
        assertTrue(eventPins(listOf(e), sel = "a", mika = true).single().let { it.selected && it.mika })
    }

    @Test fun `la fiche d'un événement, ses dates, son lieu nommé, qui l'a écrite`() {
        val f = MikaJson.decodeFromString(
            EventFiche.serializer(),
            requireNotNull(javaClass.classLoader?.getResource("carte/contrat/evenement.json")).readText(),
        )
        val shown = eventShown(f, hint = f.event.copy(distanceM = 1200.0))
        assertEquals(listOf(TagKind.WHEN, TagKind.PRICE, TagKind.DISTANCE), shown.tags.map { it.kind })
        assertEquals("à 1,2 km", shown.tags.last().text)
        assertEquals(Tone.NEUTRAL, shown.tags[1].tone)
        // l'exemple du contrat d'après R1 : sa prochaine séance, et la fin de la période en mots
        assertEquals(listOf("du mer. au lun. · 10:00–18:00 · jusqu'au 4 janv."), shown.dates)
        assertEquals("", shown.moreDates)
        assertEquals("Maison natale de Charles de Gaulle", shown.venue)
        assertEquals("w84451082", shown.venueId)
        // la commune déjà dans l'adresse ne se redit pas
        assertEquals(Fact("Adresse", "9 rue Princesse, 59800 Lille"), shown.rows.first())
        assertEquals("DATAtourisme · Hello Lille, mis à jour le 2 octobre 2026", shown.attribution)
        assertEquals(LinkText("Licence Ouverte 2.0", "https://www.etalab.gouv.fr/licence-ouverte-open-licence/"), shown.licence)
        assertEquals("3 fiches de l'office réunies", shown.merged)
        // un lieu qui n'a pas la forme d'une fiche ne s'ouvre pas ; sans attribution, la source quand même
        val other = eventShown(f.copy(venuePlace = "../x", attribution = "", moreDates = 2, merged = 1))
        assertNull(other.venueId)
        assertEquals(TOURISM_SOURCE, other.attribution)
        assertEquals("Et 2 autres dates.", other.moreDates)
        assertEquals("", other.merged)
        assertEquals(Tone.OK, eventTags(ev("g", "", free = true)).single().tone)
        assertEquals("Expositions · Lille", eventSub(f.event, f.town, themes))
    }
}
