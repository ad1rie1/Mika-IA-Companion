package fr.qwartz.mika.data.moi.carte

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId

/**
 * Les règles d'Itinéraire, portées de `frontend/Web/src/screens/carte/format.ts` et `view.ts` (leurs tests : `carte.test.ts`,
 * mêmes cas) : ses points, ce qui fait un itinéraire, tes choix face à ceux d'un trajet de Mika, ce qu'on en dit, son GPX.
 */
class RouteRulesTest {
    private val zone = ZoneId.of("Europe/Paris")
    private val now = LocalDateTime.of(2026, 11, 5, 14, 0).atZone(zone).toInstant().toEpochMilli()

    private val points = listOf(
        ItiPoint("Ma position · rue Nationale, Lille", "Ma position", 50.637, 3.063),
        ItiPoint("Annecy", "Annecy", 45.899, 6.129),
    )

    @Test fun `ses points, choisis, ou seulement tapés, leur lettre`() {
        assertEquals(listOf(NamedPoint("Ma position", 50.637, 3.063), NamedPoint("Annecy", 45.899, 6.129)), chosenPoints(points))
        assertEquals("Anne", chosenPoints(listOf(ItiPoint("Anne", "", 1.0, 2.0))).single().name) // sans nom : ce qu'on a tapé
        val typed = listOf(ItiPoint("Lille", "Lille", 50.637, 3.063), ItiPoint("Anne"))
        assertTrue(typedPoint(typed))
        assertFalse(typedPoint(listOf(typed[0], ItiPoint()))) // une étape vide n'attend rien
        assertEquals(listOf("A", "1", "2", "B"), (0 until 4).map { pointLetter(it, 4) })
        assertEquals("Itinéraire de Ma position à Annecy", routeTitle(chosenPoints(points)))
        assertEquals("Itinéraire", routeTitle(emptyList()))
        assertEquals("Ma position → Annecy", routeName(chosenPoints(points)))
        assertEquals(ItiPoint("Ma position · rue Nationale, Lille", "rue Nationale, Lille", 50.6, 3.0), herePoint(50.6, 3.0, " rue Nationale, Lille "))
        assertEquals(ItiPoint("Ma position", "Ma position", 50.6, 3.0), herePoint(50.6, 3.0, ""))
        assertEquals(ItiPoint("Annecy", "Annecy", null, null), pointOf(Place(name = "Annecy", lat = 120.0, lon = 6.1))) // hors de la Terre : pas choisi
    }

    @Test fun `ce qui fait un itinéraire, ses points choisis, son mode, ce qu'il évite en voiture`() {
        val key = itiKey(points, "voiture", listOf("peages"))
        assertEquals(key, itiKey(points, "voiture", listOf("peages")))
        assertNotEquals(key, itiKey(points.reversed(), "voiture", listOf("peages")))
        assertNotEquals(key, itiKey(points, "voiture", emptyList()))
        assertEquals(itiKey(points, "velo", listOf("peages")), itiKey(points, "velo", emptyList())) // à vélo, rien à éviter
        assertEquals(key, itiKey(listOf(points[0], ItiPoint(), points[1]), "voiture", listOf("peages"))) // une étape vide n'y compte pas
        assertEquals(itiKey(points, "voiture", listOf("peages", "ferries")), itiKey(points, "voiture", listOf("ferries", "peages")))
    }

    @Test fun `le trajet de Mika montre son mode et ses cases sans les faire tiens, un trajet que tu commences reprend les tiens`() {
        val own = RouteChoices("voiture", emptyList())
        assertEquals(RouteChoices("voiture", listOf("peages")), routeChoices(own, RegardRoute(mode = "voiture", avoid = listOf("peages"))))
        assertEquals(RouteChoices("voiture", emptyList()), own)
        // « Itinéraire jusqu'ici » depuis Explorer, juste après : la case est décochée
        assertEquals(RouteChoices("voiture", emptyList()), routeChoices(own, null))
        assertEquals("velo", routeChoices(own, RegardRoute(mode = "velo")).mode)
    }

    @Test fun `un regard qui ne dit pas ce qu'il évitait, ou un mode inconnu, tes choix`() {
        val own = RouteChoices("velo", listOf("ferries"))
        assertEquals(RouteChoices("voiture", listOf("ferries")), routeChoices(own, RegardRoute(mode = "voiture")))
        assertEquals(RouteChoices("velo", listOf("peages")), routeChoices(own, RegardRoute(mode = "fusee", avoid = listOf("peages", "inconnu"))))
        assertEquals(own, routeChoices(own, RegardRoute()))
    }

    @Test fun `ton geste (un mode, une case), seul ce qu'il touche change, sur le trajet montré comme dans tes choix`() {
        var own = RouteChoices("voiture", emptyList())
        // tu coches « autoroutes » sur le trajet de Mika, qui évitait les péages
        val shown = withChoice(RouteChoices("voiture", listOf("peages")), RouteChoice.Avoid("autoroutes", true))
        own = withChoice(own, RouteChoice.Avoid("autoroutes", true))
        assertEquals(listOf("peages", "autoroutes"), shown.avoid)
        assertEquals(listOf("autoroutes"), own.avoid) // ses péages évités ne deviennent pas ton choix
        own = withChoice(own, RouteChoice.Mode("velo"))
        assertEquals(RouteChoices("velo", listOf("autoroutes")), own)
        assertEquals(emptyList<String>(), withChoice(own, RouteChoice.Avoid("autoroutes", false)).avoid)
        assertEquals(own, withChoice(own, RouteChoice.Mode("fusee")))
        assertEquals(own, withChoice(own, RouteChoice.Avoid("inconnu", true)))
        assertEquals("À vélo, le trajet évite d'office péages et autoroutes.", avoidNote("velo"))
        assertEquals("", avoidNote("voiture"))
    }

    @Test fun `ce qu'on en dit, la durée, la distance, ce qu'il traverse, l'arrivée, ce qu'on demande à Mika`() {
        val r = Itinerary(751_000.0, 25_500.0, hasToll = true, provider = "FOSSGIS (Valhalla)")
        assertEquals("en voiture, avec péages · arrivée vers 21:05 si tu pars maintenant", routeFacts(r, "voiture", now, zone))
        assertEquals("en voiture, sans péage · arrivée vers 21:05 si tu pars maintenant", routeFacts(r.copy(hasToll = false), "voiture", now, zone))
        assertEquals("à vélo, avec un ferry · arrivée vers 21:05 si tu pars maintenant", routeFacts(r.copy(hasToll = false, hasFerry = true), "velo", now, zone))
        assertTrue(routeSource(r).startsWith("Calculé par FOSSGIS (Valhalla), relayé par ce serveur"))
        assertEquals("Regarde ce trajet : Lille → Annecy (7 h 05, 751 km en voiture). ", askAboutRoute(listOf("Lille", "Annecy"), 751_000.0, 25_500.0, "voiture"))
        assertEquals("Regarde ce trajet : Lille → Annecy. ", askAboutRoute(listOf("Lille", "Annecy"), null, null, "voiture"))
    }

    @Test fun `le tracé entier, ses tronçons bout à bout, leurs consignes`() {
        val a = LatLon(50.0, 3.0)
        val b = LatLon(49.0, 4.0)
        val c = LatLon(48.0, 5.0)
        val r = Itinerary(legs = listOf(
            Leg(shape = encodePolyline6(listOf(a, b)), steps = listOf(Step("Prendre l'A1"))),
            Leg(shape = encodePolyline6(listOf(b, c)), steps = listOf(Step("Continuer sur l'A26"))),
        ))
        assertEquals(listOf(a, b, c), routeTrack(r))
        assertEquals(listOf("Prendre l'A1", "Continuer sur l'A26"), routeSteps(r).map { it.text })
    }

    @Test fun `le GPX d'un itinéraire, ses points en route, son tracé en trace, ses noms échappés`() {
        val gpx = routeGpx(
            "Lille → <Annecy>",
            listOf(NamedPoint("Lille", 50.637, 3.063), NamedPoint("A & B", 45.899, 6.129)),
            listOf(LatLon(50.637, 3.063), LatLon(48.0, 4.5), LatLon(45.899, 6.129)),
        )
        assertTrue(gpx.startsWith("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<gpx version=\"1.1\""))
        assertTrue(gpx.contains("<name>Lille → &lt;Annecy&gt;</name>"))
        assertTrue(gpx.contains("<rtept lat=\"45.899000\" lon=\"6.129000\"><name>A &amp; B</name></rtept>"))
        assertEquals(3, Regex("<trkpt ").findAll(gpx).count())
        assertTrue(gpx.trimEnd().endsWith("</gpx>"))
        assertFalse(routeGpx("x", emptyList(), emptyList()).contains("<trk>"))
        assertTrue(routeGpx("l'été \"là\"", emptyList(), emptyList()).contains("<name>l&apos;été &quot;là&quot;</name>"))
        assertEquals("Lille-Annecy.gpx", fileName("Lille → Annecy", "gpx"))
        assertEquals("Sevrier-Ecully.gpx", fileName("Sévrier → Écully", "gpx"))
        assertEquals("itineraire.gpx", fileName("", "gpx"))
        assertEquals("itineraire.gpx", fileName("→", "gpx"))
    }
}
