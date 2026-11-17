package fr.qwartz.mika.data.moi.carte

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId

/**
 * Les règles d'un voyage, portées de `frontendv2/src/screens/carte/format.ts`, `view.ts` et `map/cards.ts` (leurs tests :
 * `carte.test.ts`, mêmes cas) : l'ordre des arrêts et où un geste les met, ce dont son trajet dépend, « Sur la route »,
 * ce que la fenêtre d'un voyage envoie, ses miniatures.
 */
class TripRulesTest {
    private val zone = ZoneId.of("Europe/Paris")
    private val now = LocalDateTime.of(2026, 11, 5, 14, 0).atZone(zone).toInstant().toEpochMilli()

    private fun stop(id: String, name: String, lat: Double?, lon: Double?, kind: String = "", note: String = "", by: String = "toi") =
        TripStop(id, name, kind, lat, lon, note, by)

    private val trip = Trip(
        id = "640", title = "Les Alpes en cinq jours", start = "2027-04-03", mode = "voiture", avoid = emptyList(), updated = 1, mika = true,
        days = listOf(
            TripDay(1, "2027-04-03", listOf(
                stop("1", "Lille", 50.637, 3.063, "Ta position"),
                stop("2", "Reims", 49.258, 4.032, "À voir", note = "le portail de l'ange", by = "mika"),
                stop("3", "Dijon", 47.322, 5.041, "Dormir"),
            )),
            TripDay(2, "2027-04-04", listOf(
                stop("4", "Bourg-en-Bresse", 46.21, 5.23, by = "mika"),
                stop("5", "Annecy", 45.899, 6.129),
            )),
        ),
    )

    private fun leg(from: String, to: String, km: Int, s: Int, a: LatLon, b: LatLon) =
        TripLeg(from, to, km * 1000.0, s.toDouble(), encodePolyline6(listOf(a, b)))

    private val route = TripRoute(
        days = listOf(
            TripRouteDay(1, 502_000.0, 17_400.0, listOf(
                leg("1", "2", 207, 8100, LatLon(50.637, 3.063), LatLon(49.258, 4.032)),
                leg("2", "3", 295, 9300, LatLon(49.258, 4.032), LatLon(47.322, 5.041)),
            )),
            TripRouteDay(2, 268_000.0, 10_200.0, listOf(
                leg("3", "4", 152, 6000, LatLon(47.322, 5.041), LatLon(46.21, 5.23)),
                leg("4", "5", 116, 4200, LatLon(46.21, 5.23), LatLon(45.899, 6.129)),
            )),
        ),
        distanceM = 770_000.0, durationS = 27_600.0, hasToll = true, provider = "Valhalla (essai)",
    )

    private fun ids(t: Trip) = t.days.map { d -> d.stops.map { it.id } }

    private fun place(id: String = "l3", name: String = "Camping de l'Horizon", along: Double? = null, distance: Double? = 5830.0, lat: Double? = 45.856) =
        Place(id, name, "camp_site", "Camping", "dormir", lat, 6.169, "Sévrier", distance, along)

    @Test fun `les arrêts se numérotent d'un bout à l'autre, et le titre d'un jour va de son premier à son dernier`() {
        assertEquals(listOf(Triple("1", 1, 1), Triple("2", 1, 2), Triple("3", 1, 3), Triple("4", 2, 4), Triple("5", 2, 5)),
            orderedStops(trip).map { Triple(it.stop.id, it.day, it.n) })
        assertEquals("Lille → Dijon", dayTitle(trip.days[0].stops))
        assertEquals("Lille", dayTitle(listOf(trip.days[0].stops[0])))
        assertEquals("", dayTitle(emptyList()))
        assertEquals(5, stopCount(trip))
        assertEquals(2, hersCount(trip))
    }

    @Test fun `glisser, la place parmi les autres arrêts du jour, comme l'API la lit`() {
        assertEquals(0, dropIndex(trip, "3", 1, "1")) // Dijon avant Lille
        assertEquals(1, dropIndex(trip, "1", 1, "3")) // Lille avant Dijon : parmi Reims, Dijon
        assertEquals(-1, dropIndex(trip, "2", 2, null)) // à la fin du jour 2
        assertEquals(listOf("2", "1", "3"), movedTrip(trip, "1", 1, 1).days[0].stops.map { it.id })
        assertEquals(listOf(listOf("1", "2", "3"), listOf("4"), listOf("5")), ids(movedTrip(trip, "5", 3, -1)))
        // un jour vidé à la fin disparaît
        val two = trip.copy(days = listOf(trip.days[0], TripDay(2, "", listOf(trip.days[1].stops[0]))))
        assertEquals(1, movedTrip(two, "4", 1, -1).days.size)
        // un arrêt inconnu : le voyage tel quel
        assertEquals(trip, movedTrip(trip, "inconnu", 1, 0))
    }

    @Test fun `monter, descendre, une place plus haut ou plus bas, d'un jour à l'autre au bord`() {
        assertEquals(1 to 0, stepMove(trip, "2", -1))
        assertEquals(2 to 0, stepMove(trip, "3", 1)) // le dernier du jour 1 passe en tête du jour 2
        assertEquals(1 to -1, stepMove(trip, "4", -1)) // le premier du jour 2 passe à la fin du jour 1
        assertNull(stepMove(trip, "1", -1))
        assertNull(stepMove(trip, "inconnu", 1))
        // le dernier, avec d'autres dans son jour : un jour de plus ; seul dans le sien : il ne descend pas
        assertEquals(3 to 0, stepMove(trip, "5", 1))
        assertNull(stepMove(movedTrip(trip, "4", 1, -1), "5", 1))
    }

    @Test fun `un lieu croisé le long du trajet s'ajoute avant l'arrêt qu'on atteint après lui`() {
        assertEquals(1 to 1, alongPlace(trip, route, 100_000.0)) // entre Lille et Reims
        assertEquals(2 to 0, alongPlace(trip, route, 600_000.0)) // entre Dijon et Bourg
        assertEquals(2 to -1, alongPlace(trip, route, 900_000.0)) // après l'arrivée
        assertEquals(1 to 1, alongPlace(trip, null, 50_000.0)) // sans itinéraires : à vol d'oiseau
        assertEquals(2 to -1, alongPlace(trip, route, null))
    }

    @Test fun `le tracé d'un voyage, ses tronçons calculés, sinon ses arrêts reliés`() {
        assertEquals(4, tripLines(route).size)
        assertEquals(emptyList<List<LatLon>>(), tripLines(null))
        val routed = tripScene(trip, route, AlongState("640"))
        assertEquals(4, routed.lines.size)
        assertFalse(routed.lines.any { it.straight })
        val straight = tripScene(trip, null, AlongState("640"))
        assertEquals(1, straight.lines.size)
        assertTrue(straight.lines[0].straight)
        // ses arrêts numérotés, les siens en rose ; un arrêt sans coordonnées ne se pose pas, mais garde son numéro
        val pins = tripPins(trip.copy(days = listOf(trip.days[0].copy(stops = listOf(stop("9", "?", null, null)) + trip.days[0].stops))))
        assertEquals(listOf("2", "3", "4"), pins.map { it.label })
        assertEquals(listOf(false, true, false), pins.map { it.mika })
        assertEquals("1" to "4", legsByStop(route)["2"]!!.from to legsByStop(route)["4"]!!.to) // le tronçon qui arrive à chacun
        assertEquals("2 h 15 · 207 km", legWords(legsByStop(route)["2"]!!))
    }

    @Test fun `une poignée lâchée où elle était ne change rien, rien ne part`() {
        assertTrue(noopMove(trip, "2", 1, dropIndex(trip, "2", 1, "3"))) // Reims, devant Dijon : sa place
        assertTrue(noopMove(trip, "2", 1, 1))
        assertTrue(noopMove(trip, "3", 1, -1)) // déjà le dernier du jour
        assertFalse(noopMove(trip, "2", 1, 0))
        assertFalse(noopMove(trip, "3", 2, 0)) // au jour suivant
        assertFalse(noopMove(trip, "5", 3, -1)) // un jour de plus
        assertTrue(noopMove(trip, "inconnu", 1, 0))
    }

    @Test fun `un arrêt retiré, une note changée se montrent de suite, un déplacement se dit à un lecteur d'écran`() {
        val without = removedTrip(trip, "4")
        assertEquals(listOf(listOf("1", "2", "3"), listOf("5")), ids(without))
        assertEquals(1, removedTrip(without, "5").days.size) // le dernier jour vidé s'en va
        assertEquals("Reims : jour 1, arrêt 2 sur 3.", movedWords(trip, "2"))
        assertEquals("Dijon : jour 2, arrêt 1 sur 3.", movedWords(movedTrip(trip, "3", 2, 0), "3"))
        assertEquals("", movedWords(trip, "inconnu"))
        val noted = notedTrip(trip, "1", "réserver avant le 15")
        assertEquals("réserver avant le 15", stopOf(noted, "1")!!.note)
        assertEquals("", stopOf(notedTrip(trip, "2", ""), "2")!!.note) // vidée : effacée
        assertEquals(stopOf(trip, "3"), stopOf(noted, "3"))
    }

    @Test fun `le trajet dépend de l'ordre des arrêts, de leurs jours, du mode et de ce qu'il évite — pas d'une note ni du titre`() {
        val key = tripRouteKey(trip)
        assertEquals(key, tripRouteKey(trip.copy(title = "Autre", updated = 9)))
        assertEquals(key, tripRouteKey(trip.copy(days = trip.days.map { d -> d.copy(stops = d.stops.map { it.copy(note = "réserver") }) })))
        assertNotEquals(key, tripRouteKey(movedTrip(trip, "1", 1, 1)))
        assertNotEquals(key, tripRouteKey(movedTrip(trip, "3", 2, 0))) // même ordre, un autre jour : ses tronçons changent de jour
        assertNotEquals(key, tripRouteKey(trip.copy(mode = "velo")))
        assertNotEquals(key, tripRouteKey(trip.copy(avoid = listOf("peages"))))
        assertEquals(tripRouteKey(trip.copy(avoid = listOf("peages", "ferries"))), tripRouteKey(trip.copy(avoid = listOf("ferries", "peages"))))
        assertEquals(5, routableStops(trip))
        assertEquals(0, routableStops(trip.copy(days = listOf(TripDay(1, "", listOf(stop("1", "Lille", null, null)))))))
    }

    @Test fun `Sur la route, ses lieux en épingles secondaires, à part des arrêts, sans numéro, le jour d'abord`() {
        val along = AlongState("640", cat = "dormir", places = listOf(place(along = 100_000.0, distance = 3000.0), place(id = "l9", name = "Gîte", lat = null, along = 600_000.0)))
        val pins = alongPins(trip, route, along)
        assertEquals(1, pins.size)
        assertEquals(ScenePin("along:0", 45.856, 6.169, minor = true, title = "Camping de l'Horizon · jour 1 · Camping · Sévrier · à 3 km de la route"), pins[0])
        assertEquals("", pins[0].label)
        assertEquals("along:4", alongPinId(4))
        assertEquals(4, alongIndexOf("along:4"))
        assertNull(alongIndexOf("4"))
        assertNull(alongIndexOf("l3"))
        // la liste ne les montre pas (en recherche, refusée, moins de deux arrêts, fermée) : la carte non plus
        assertTrue(alongPins(trip, route, along.copy(loading = true)).isEmpty())
        assertTrue(alongPins(trip, route, along.copy(error = "Trop de demandes.")).isEmpty())
        assertTrue(alongPins(trip.copy(days = listOf(TripDay(1, "", listOf(trip.days[0].stops[0])))), route, along).isEmpty())
        assertTrue(alongPins(trip, route, along.copy(cat = "")).isEmpty())
        // les épingles secondaires d'abord, puis les arrêts
        assertEquals(listOf("along:0", "1", "2", "3", "4", "5"), tripScene(trip, route, along).pins.map { it.id })
        assertEquals("jour 2 · sur la route", alongFacts(trip, route, place(along = 600_000.0, distance = 90.0).copy(kindFr = "", town = "")))
        assertEquals("jour 2 · Camping · Sévrier · à 2,5 km de la route", alongFacts(trip, route, place(along = 600_000.0, distance = 2500.0)))
    }

    @Test fun `un voyage qui quitte la voiture n'envoie plus ce qu'il évite, en voiture, seulement s'il a changé`() {
        val t = Trip(id = "1", title = "Les Alpes", start = "2027-04-03", mode = "voiture", avoid = listOf("peages"))
        fun form(title: String = t.title, start: String = t.start, mode: String = t.mode, avoid: List<String> = t.avoid) = TripForm(title, start, mode, avoid)
        // à vélo : les cases (cachées, mais toujours cochées) ne partent pas
        assertEquals(TripValues(mode = "velo"), tripChanges(t, form(mode = "velo", avoid = listOf("peages", "ferries"))))
        assertTrue(tripChanges(t.copy(mode = "velo"), form(mode = "velo", avoid = emptyList())).isEmpty)
        // en voiture : ce qu'il évite, dans l'ordre de l'API, s'il a changé
        assertEquals(TripValues(avoid = listOf("peages", "ferries")), tripChanges(t, form(avoid = listOf("ferries", "peages"))))
        assertTrue(tripChanges(t.copy(avoid = listOf("ferries", "peages")), form(avoid = listOf("peages", "ferries"))).isEmpty)
        assertEquals(TripValues(avoid = emptyList()), tripChanges(t, form(avoid = emptyList())))
        // revenu à la voiture : ce qu'on coche part avec le mode
        assertEquals(TripValues(mode = "voiture", avoid = listOf("autoroutes")), tripChanges(t.copy(mode = "pied", avoid = emptyList()), form(mode = "voiture", avoid = listOf("autoroutes"))))
        // le titre se lit sans ses espaces ; une date vidée part vide (plus de date)
        assertEquals(TripValues(start = ""), tripChanges(t, form(title = "  Les Alpes  ", start = "")))
    }

    @Test fun `Nouveau voyage, ce qu'il évite, pour un voyage en voiture seulement, d'un lieu, son titre`() {
        assertEquals(TripValues("Les Alpes", "", "voiture", listOf("peages", "ferries")), newTripValues(TripForm(" Les Alpes ", "", "voiture", listOf("ferries", "peages"))))
        assertEquals(TripValues("La Loire", "2027-05-01", "velo", null), newTripValues(TripForm("La Loire", "2027-05-01", "velo", listOf("peages"))))
        assertEquals("Autour de Sévrier", tripTitleFor(place()))
        assertEquals("Autour de Camping de l'Horizon", tripTitleFor(place().copy(town = "")))
        // un lieu en arrêt : borné comme l'API ; sans coordonnées, il ne s'ajoute pas
        val s = stopOfPlace(place(), day = 2, index = 1, note = "  arriver avant 17 h ")!!
        assertEquals(NewStop("Camping de l'Horizon", 45.856, 6.169, "Camping", 2, 1, "arriver avant 17 h"), s)
        assertEquals("Lieu", stopOfPlace(place(name = ""), 1, -1)!!.name)
        assertNull(stopOfPlace(place(lat = null), 1, -1))
        assertEquals(placeIntent(place()), placeIntent(place(id = "l77"))) // l'identifiant d'index change, pas le lieu
    }

    @Test fun `les mots d'un voyage et ce qu'on demande à Mika`() {
        assertEquals("Tu peux m'aider à préparer notre voyage « Les Alpes en cinq jours » ? ", askAboutTrip(trip.title))
        assertEquals("3–4 avr. 2027 · en voiture · péages acceptés", tripHead(trip, now, short = true, zone = zone))
        assertEquals("sam. 3 et dim. 4 avril 2027 · à vélo", tripHead(trip.copy(mode = "velo"), now, zone = zone))
        assertEquals("sans date · en voiture · sans péage", tripHead(trip.copy(start = "", avoid = listOf("peages")), now, zone = zone))
        assertEquals("sam. 3 avril 2027 · 502 km · 4 h 50", dayFacts(trip.days[0], route, now, zone))
        assertEquals("", dayFacts(TripDay(3), route, now, zone))
    }

    @Test fun `la miniature d'un voyage, d'un regard, et ce qu'elles ouvrent`() {
        val mini = tripMini(trip)
        assertEquals("Voyage · Les Alpes en cinq jours", mini.title)
        assertEquals("2 jours · 5 arrêts · 2 de Mika", mini.sub)
        assertEquals(MiniOpen(trip = "640"), mini.opens)
        assertEquals(1L, mini.version)
        assertTrue(mini.scene.lines.single().straight) // aucune demande d'itinéraire : ses arrêts reliés
        val shape = encodePolyline6(listOf(LatLon(50.637, 3.063), LatLon(48.0, 4.5), LatLon(45.899, 6.129)))
        val looked = Regard(kind = "look", title = "Lille → Annecy", what = "trajet",
            places = listOf(Place(name = "Lille", lat = 50.637, lon = 3.063), Place(name = "Annecy", lat = 45.899, lon = 6.129)),
            route = RegardRoute(mode = "voiture", distanceM = 751_000.0, durationS = 25_500.0, shape = shape))
        val r = regardMini("812", looked)
        assertEquals(MiniOpen(tab = "itineraire", look = "812"), r.opens)
        assertEquals("Mika a calculé le trajet · 751 km · 7 h 05 en voiture", r.sub)
        assertEquals(listOf("A", "B"), r.scene.pins.map { it.label })
        assertTrue(r.scene.pins.all { it.mika })
        assertEquals(3, r.scene.lines.single().points.size)
        assertTrue(r.scene.lines.single().mika)
        // des lieux cherchés : Explorer ; une carte qui montre un voyage : le voyage
        val places = Regard(kind = "look", title = "campings", what = "lieux", places = listOf(Place(id = "l1", name = "A", lat = 45.0, lon = 6.0)))
        assertEquals(MiniOpen(tab = "explorer", look = "9"), regardMini("9", places).opens)
        assertEquals("Mika a cherché · 1 lieu", regardMini("9", places).sub)
        assertEquals(MiniOpen(trip = "640"), regardMini("10", places.copy(kind = "map", trip = "640")).opens)
        // une carte qui relie ses lieux sans tracé : reliés à vol d'oiseau, en rose
        val linked = regardLine(Regard(kind = "map", places = looked.places, route = RegardRoute(mode = "pied")))
        assertTrue(linked.single().straight && linked.single().mika)
        assertTrue(regardLine(places).isEmpty())
        // une note pas encore lue, plus là
        assertEquals("Voyage · Les Alpes", pendingMini(MiniRef.trip("640"), "Les Alpes").title)
        assertEquals(MiniOpen(tab = "explorer", look = "812"), noteOpen(MiniRef(MapNoteKind.LOOK, "812")))
        assertTrue(goneMini(MiniRef(MapNoteKind.MAP, "3")).gone)
        assertEquals("Ce voyage n'existe plus.", goneMini(MiniRef.trip("640")).sub)
    }

    @Test fun `quatre miniatures vivantes au plus, une qui sort de la vue rend sa place`() {
        val pool = MiniPool()
        assertTrue((1..4).all { pool.take("m$it") })
        assertFalse(pool.take("m5"))
        assertTrue(pool.take("m2")) // elle l'a déjà
        pool.give("m2")
        assertTrue(pool.take("m5"))
        assertEquals(4, pool.size)
    }
}
