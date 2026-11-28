package fr.qwartz.mika.data.moi.carte

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.yield
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Les règles de la Carte (Explorer, la vraie carte ou le plan), portées du web : leurs cas viennent de
 * `frontend/Web/src/screens/carte/requests.test.ts`, `carte.test.ts` et `map/map.test.ts`.
 */
class CarteRulesTest {
    private fun place(name: String, distance: Double? = null, id: String = "", lat: Double? = 45.9, lon: Double? = 6.1) =
        Place(id = id, name = name, kindFr = "Camping", category = "dormir", lat = lat, lon = lon, town = "Sévrier", distanceM = distance)

    @Test fun `une adresse, un chiffre, ou cinq caractères, jamais moins de trois`() {
        assertFalse(wantsAddress("12"))
        assertTrue(wantsAddress("12 r"))
        assertFalse(wantsAddress("Lyo")) // un nom court : l'index des lieux suffit
        assertTrue(wantsAddress("Rue R"))
        assertFalse(wantsAddress("   ab  "))
        // un numéro se demande toujours (sans adresses branchées, le serveur le dit : 503) ; un nom, seulement si les
        // adresses sont prêtes et que l'index n'a rien trouvé
        assertTrue(addressWanted("12 rue Royale", hasPlaces = true, addressesReady = false))
        assertTrue(addressWanted("rue Royale", hasPlaces = false, addressesReady = true))
        assertFalse(addressWanted("rue Royale", hasPlaces = true, addressesReady = true))
        assertFalse(addressWanted("rue Royale", hasPlaces = false, addressesReady = false))
        assertFalse(addressWanted("Lyo", hasPlaces = false, addressesReady = true))
    }

    @Test fun `un texte déjà cherché ne se redemande pas, deux demandes n'en font qu'une`() = runBlocking {
        val asked = mutableListOf<Pair<String, Int>>()
        val gate = CompletableDeferred<Unit>()
        val book = AddressBook(this, { q, limit ->
            asked += q to limit
            gate.await()
            MoiApi.Result.Ok(listOf(place(q)))
        })
        assertNull(book.peek("12 rue Royale"))
        val a = async { book.lookup("12 rue Royale") }
        val b = async { book.lookup("12  RUE royale ") }
        yield()
        gate.complete(Unit)
        val first = (a.await() as MoiApi.Result.Ok).value
        assertSame(first, (b.await() as MoiApi.Result.Ok).value)
        book.lookup("  12  RUE royale ")
        assertEquals(listOf("12 rue Royale" to ADDRESS_LIMIT), asked)
        assertEquals("12 rue Royale", book.peek("12 rue royale")?.single()?.name)
    }

    @Test fun `un refus (429) se dit à l'appelant et ne se garde pas, seuls les derniers textes restent`() = runBlocking {
        var calls = 0
        val book = AddressBook(this, { q, _ ->
            calls += 1
            if (calls == 1) MoiApi.Result.Failed(MoiError(429, "Trop de trajets ou d'adresses demandés d'affilée : attends une minute."))
            else MoiApi.Result.Ok(listOf(place(q)))
        }, keep = 2)
        assertEquals(429, ((book.lookup("12 rue Royale") as MoiApi.Result.Failed).error.code))
        assertNull(book.peek("12 rue Royale"))
        assertEquals(1, (book.lookup("12 rue Royale") as MoiApi.Result.Ok).value.size)
        assertEquals(2, calls)
        book.lookup("2 rue B")
        book.lookup("3 rue C")
        assertNull(book.peek("12 rue Royale")) // le plus ancien s'en va
        assertEquals("3 rue C", book.peek("3 rue C")?.single()?.name)
    }

    @Test fun `la légende dit jusqu'où la recherche est allée`() {
        assertEquals("autour de ta position", searchReach(true, listOf(place("a", 40.0), place("b", 19_000.0))))
        assertEquals("autour de ta position", searchReach(true, listOf(place("a", 20_000.0))))
        // l'index s'est élargi jusqu'à chercher partout
        assertEquals(
            "les plus proches que l'index connaisse · jusqu'à 695 km",
            searchReach(true, listOf(place("a", 1_200.0), place("b", 695_400.0), place("c", 90.0))),
        )
        assertEquals("autour de ta position", searchReach(true, emptyList()))
        assertEquals("autour de ta position", searchReach(true, listOf(place("a", null))))
        assertEquals("dans cette zone", searchReach(false, listOf(place("a", 695_400.0))))
        assertEquals("2 lieux · dans cette zone", searchLegend(false, listOf(place("a"), place("b"))))
        assertEquals("1 lieu · autour de ta position", searchLegend(true, listOf(place("a", 10.0))))
    }

    @Test fun `le titre d'une recherche, la ligne d'un lieu, la phrase pour Mika`() {
        val info = CarteInfo(categories = listOf(Category("dormir", "Dormir"), Category("manger", "Manger")))
        assertEquals("Dormir · camping", searchTitle(info, " camping ", "dormir"))
        assertEquals("Camping", searchTitle(info, "Camping", ""))
        assertEquals("Dormir", searchTitle(info, "", "dormir"))
        assertEquals("Lieux", searchTitle(null, "", ""))
        val horizon = place("Camping de l'Horizon", 5_830.0)
        assertEquals("Camping · Sévrier · à 5,8 km de toi", placeLine(horizon, Where.HERE))
        assertEquals("Camping · Sévrier · à 5,8 km", placeLine(horizon, Where.ZONE))
        assertEquals("Camping · Sévrier", placeLine(horizon.copy(distanceM = null), Where.HERE))
        assertEquals("Tu connais « Camping de l'Horizon » (Camping, Sévrier) ? ", askAboutPlace(horizon))
        assertEquals("Tu connais « 12 Rue Royale » ? ", askAboutPlace(Place(name = "12 Rue Royale")))
    }

    @Test fun `le lieu choisi, et ce qu'Explorer montre sur la carte`() {
        val places = listOf(place("A", id = "l1"), place("B"), place("C", id = "l3", lat = null))
        val addresses = listOf(place("12 Rue Royale", id = "a:1"))
        assertEquals("p1", placeId(places[1], 1))
        assertEquals("B", selectedPlace(places, addresses, "p1")?.name)
        assertEquals("12 Rue Royale", selectedPlace(places, addresses, "a0")?.name)
        assertNull(selectedPlace(places, addresses, "a3"))
        assertNull(selectedPlace(places, addresses, null))
        val scene = explorerScene(places, addresses, "l1", LatLon(45.9, 6.12))
        // un lieu sans coordonnées ne se pose pas ; le choisi est cerclé ; ta position, quand on cherche autour de toi
        assertEquals(listOf("l1", "p1", "a0"), scene.pins.map { it.id })
        assertEquals(listOf(true, false, false), scene.pins.map { it.selected })
        assertEquals(SceneHere(45.9, 6.12), scene.here)
        assertNull(explorerScene(places, addresses, null, null).here)
        assertEquals("45.900000,6.100000", pointText(LatLon(45.9, 6.1)))
        assertEquals("6.10000,45.80000,6.20000,45.90000", bboxText(Bounds(6.1, 45.8, 6.2, 45.9)))
    }

    @Test fun `la vraie carte se montre quand le fond est prêt et couvre la scène`() {
        val fond = MapFond(ready = true, tiles = "/t/{z}/{x}/{y}", bounds = listOf(-5.2, 41.3, 9.6, 51.1))
        val annecy = Scene(pins = listOf(ScenePin("a", 45.9, 6.1)))
        assertTrue(liveWanted(fond, annecy, refused = false))
        assertTrue(liveWanted(fond, Scene.EMPTY, refused = false)) // une scène vide : le fond de carte
        assertFalse(liveWanted(fond, annecy, refused = true)) // refusée ici (ses tuiles, MapLibre) : le plan
        assertFalse(liveWanted(fond.copy(ready = false), annecy, refused = false))
        assertFalse(liveWanted(null, annecy, refused = false))
        assertFalse(liveWanted(fond, Scene(pins = listOf(ScenePin("m", 40.4, -3.7))), refused = false)) // Madrid
        // la Position : sa position seule compte, et sans elle rien ne se montre
        assertTrue(liveWanted(fond, Scene(here = SceneHere(50.6, 3.0)), refused = false, needsHere = true))
        assertFalse(liveWanted(fond, Scene.EMPTY, refused = false, needsHere = true))
        assertFalse(liveWanted(fond, Scene(here = SceneHere(40.4, -3.7)), refused = false, needsHere = true))
    }

    @Test fun `une miniature ne devient une vraie carte que si le fond couvre tous ses points (R4-06)`() {
        // un fond limité à la France (sans la Corse) : Barcelone n'y est pas
        val france = MapFond(ready = true, tiles = "/t/{z}/{x}/{y}", bounds = listOf(-5.2, 42.3, 8.3, 51.1))
        val lille = ScenePin("1", 50.63, 3.06, label = "1")
        val lyon = ScenePin("2", 45.76, 4.84, label = "2")
        val barcelone = ScenePin("3", 41.39, 2.17, label = "3")
        // Lille → Barcelone : un écran se montrerait (un point couvert), la miniature garde son plan
        val outside = Scene(pins = listOf(lille, barcelone))
        assertTrue(liveWanted(france, outside, refused = false))
        assertFalse(miniWanted(france, outside, refused = false))
        // tout dans la zone : la vraie carte
        val inside = Scene(pins = listOf(lille, lyon), lines = listOf(SceneLine(listOf(LatLon(50.63, 3.06), LatLon(45.76, 4.84)))))
        assertTrue(miniWanted(france, inside, refused = false))
        // un tracé qui finit hors de la zone, même avec ses épingles dedans : le plan
        val leaving = inside.copy(lines = listOf(SceneLine(listOf(LatLon(50.63, 3.06), LatLon(40.4, -3.7)))))
        assertFalse(miniWanted(france, leaving, refused = false))
        // refusée, fond pas prêt, rien à épingler (un voyage sans arrêt, une note plus là) : le plan
        assertFalse(miniWanted(france, inside, refused = true))
        assertFalse(miniWanted(france.copy(ready = false), inside, refused = false))
        assertFalse(miniWanted(null, inside, refused = false))
        assertFalse(miniWanted(france, Scene.EMPTY, refused = false))
        // un fond sans zone couvre tout
        assertTrue(miniWanted(france.copy(bounds = null), outside, refused = false))
    }

    @Test fun `pourquoi un plan, en mots`() {
        val fond = MapFond(ready = true, tiles = "/t")
        assertEquals("la carte du serveur se lit…", planWhy(null, null, null))
        assertEquals("Le serveur ne répond pas.", planWhy(null, MoiError(0, "Le serveur ne répond pas."), null))
        assertEquals("La carte n'est pas encore prête sur ce serveur.", planWhy(MapFond(reason = "La carte n'est pas encore prête sur ce serveur."), null, null))
        assertEquals("aucune carte n'est réglée sur ce serveur.", planWhy(MapFond(), null, null))
        assertEquals("ses tuiles ne se lisent pas sur ce serveur en ce moment.", planWhy(fond, null, LiveFailure.TILES))
        assertEquals("elle ne se charge pas sur ce téléphone.", planWhy(fond, null, LiveFailure.LOAD))
        assertEquals("elle ne se dessine pas sur ce téléphone.", planWhy(fond, null, LiveFailure.STYLE))
        assertEquals("ces lieux sont hors de la zone qu'elle couvre.", planWhy(fond, null, null))
        assertEquals("ta position est hors de la zone qu'elle couvre.", planWhy(fond, null, null, here = true))
    }

    @Test fun `des tuiles en échec de suite font revenir le plan, une lue remet le compte à zéro`() {
        val watch = TileWatch(limit = 3)
        assertFalse(watch.error())
        assertFalse(watch.error())
        watch.ok()
        assertFalse(watch.error())
        assertFalse(watch.error())
        assertTrue(watch.error()) // la troisième d'affilée
        assertTrue(watch.failed)
        assertFalse(watch.error()) // une seule fois
        watch.ok()
        assertTrue(watch.failed) // une tuile lue après coup ne rend pas la carte
        watch.reset() // un autre fond servi
        assertFalse(watch.failed)
        assertEquals(4, TILE_FAILURES)
    }
}
