package fr.qwartz.mika.data.moi.carte

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

/**
 * Les fiches, les événements et les photos sur l'API par personne (ADR 0259, `protocole-moi.md` § 10) : les exemples du
 * contrat des clients (`output/carte-avis/SUIVI.md`, copiés tels quels dans `test/resources/carte/contrat/`) se lisent
 * entiers ; ce que chaque appel envoie, sous le jeton du téléphone ; un identifiant d'une autre forme ne part pas ; une
 * photo ne se demande qu'à ce serveur ; les refus du serveur arrivent en mots.
 */
class CarteFichesApiTest {
    private val server = MockWebServer()
    private val client = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).build()
    private lateinit var base: ServerBase
    private lateinit var api: CarteApi

    @Before fun start() {
        server.start()
        base = (ServerBase.parse(server.url("/").toString()) as ServerBase.Parsed.Ok).base
        api = CarteApi(MoiApi(client, { Credentials(base, "mw_secret") }, {}, Dispatchers.IO))
    }

    @After fun stop() = server.close()

    private fun contract(name: String): String =
        requireNotNull(javaClass.classLoader?.getResource("carte/contrat/$name")) { "carte/contrat/$name" }.readText()

    private fun ok(body: String) = server.enqueue(MockResponse.Builder().body(body).build())
    private fun refuse(code: Int, body: String) = server.enqueue(MockResponse.Builder().code(code).body(body).build())

    // ── Les exemples du contrat ─────────────────────────────────────────

    @Test fun `une liste notée, les champs de toujours, puis ceux qu'on sait seulement`() {
        val found = MikaJson.decodeFromString(PlacesFound.serializer(), contract("lieux.json"))
        val (rated, plain) = found.places
        assertEquals("n4021153781", rated.osm)
        assertEquals("open", rated.openState)
        assertEquals("Ouvert · ferme à 22:30", rated.openText)
        assertEquals(4.8, rated.rating!!, 0.0)
        assertEquals(15235L, rated.reviews)
        assertEquals("€€", rated.price)
        assertEquals("p:3f1c9a0e5b7d2c4e6f8a1b3c5d7e9f02", rated.photo)
        assertEquals(listOf("terrasse", "vegetarien", "emporter"), rated.tags)
        // absents quand on ne les sait pas : leur défaut, jamais un zéro inventé
        assertEquals("w45911888", plain.osm)
        assertNull(plain.rating)
        assertNull(plain.reviews)
        assertEquals("", plain.photo)
        assertEquals("", plain.openState)
        assertTrue(plain.tags.isEmpty())
        val cover = found.reviews!!
        assertTrue(cover.ready)
        assertEquals(1, cover.loaded)
        assertEquals(1795155120000L, cover.oldest)
        assertNull(found.here)
    }

    @Test fun `une fiche complète, chaque source et ce qu'il faut citer`() {
        val f = MikaJson.decodeFromString(PlaceFiche.serializer(), contract("fiche.json"))
        assertEquals("Magmatic", f.place.name)
        val osm = f.osm!!
        assertEquals("© les contributeurs d'OpenStreetMap", osm.attribution)
        assertEquals("https://www.openstreetmap.org/copyright", osm.licenceUrl)
        assertEquals("tous les jours : 12:00–14:30, 19:00–22:30", osm.hoursText)
        assertEquals(3, osm.facts.size)
        val t = f.tourism!!
        assertEquals("DATAtourisme · Hello Lille, mis à jour le 3 juin 2025", t.attribution)
        assertEquals("Licence Ouverte 2.0", t.licence)
        assertEquals("CC BY-NC-ND 4.0", t.photos.single().licence)
        assertEquals("datatourisme", t.photos.single().source)
        val r = f.reviews!!
        assertTrue(r.found)
        assertEquals("Google Maps", r.sourceLabel)
        assertEquals(15235L, r.count)
        assertEquals("30–50 €", r.priceRange)
        val review = r.reviews.single()
        assertEquals("Camille R.", review.author)
        assertEquals("https://www.google.com/maps/contrib/100000000000000000001", review.authorUrl)
        assertEquals("il y a 2 semaines", review.relative)
        assertEquals("https://www.google.com/maps/contrib/100000000000000000001", r.photos.single().creditUrl)
        assertEquals(800, r.photos.single().width)
        assertEquals("https://maps.google.com/?cid=1234567890", r.url)
        val e = f.events.single()
        assertEquals("e:450c81b3-6ffa-3d4e-9c1b-2a7f0e5d8c41", e.id)
        assertEquals(false, e.free)
        assertEquals(listOf("spectacles"), e.themes)
    }

    @Test fun `une liste d'événements, tous leurs champs, et la couverture au même rayon`() {
        val found = MikaJson.decodeFromString(EventsFound.serializer(), contract("evenements.json"))
        val e = found.events.single()
        assertEquals("sam. 21 nov. · 19:00–22:00", e.whenText)
        assertEquals("L'Aéronef, Lille", e.place)
        assertEquals(780.0, e.distanceM!!, 0.0)
        assertEquals(LatLon(50.636554, 3.074244), e.at)
        assertEquals("", e.photo)
        val cover = found.coverage!!
        assertEquals(11, cover.cells)
        assertEquals(9, cover.loaded)
        assertTrue(cover.note.startsWith("Cette zone n'est lue qu'en partie"))
    }

    @Test fun `une fiche d'événement, ses dates, son lieu, qui l'a écrite`() {
        val f = MikaJson.decodeFromString(EventFiche.serializer(), contract("evenement.json"))
        assertEquals("w84451082", f.venuePlace)
        assertEquals("Maison natale de Charles de Gaulle", f.venue)
        assertEquals(3, f.merged)
        assertEquals(0, f.moreDates)
        assertEquals(listOf("mer.", "jeu.", "ven.", "sam.", "dim.", "lun."), f.dates.single().days)
        assertEquals("DATAtourisme · Hello Lille, mis à jour le 2 octobre 2026", f.attribution)
        assertNull(f.event.distanceM)
        assertEquals(false, f.event.free)
    }

    @Test fun `un null là où une valeur est attendue prend son défaut, une clé neuve s'ignore`() {
        val f = MikaJson.decodeFromString(
            PlaceFiche.serializer(),
            """{"place":{"id":"l1","name":"X","cuisine":null,"tags":null,"neuf":1},"osm":null,"tourism":null,"reviews":null,"events":null}""",
        )
        assertEquals("", f.place.cuisine)
        assertTrue(f.place.tags.isEmpty())
        assertNull(f.osm)
        assertNull(f.reviews)
        assertTrue(f.events.isEmpty())
    }

    @Test fun `un regard d'événements, ses événements, ses lieux vides`() {
        val r = MikaJson.decodeFromString(
            Regard.serializer(),
            """{"kind":"look","title":"Concerts ce week-end","what":"evenements","places":[],"route":null,"trip":"","at":1,
               "events":[{"id":"e:450c81b3-6ffa-3d4e-9c1b-2a7f0e5d8c41","name":"Éclats du rire !","start":"2026-11-21T19:00:00+01:00",
                          "end":"","when_text":"sam. 21 nov. · 19:00","place":"L'Aéronef, Lille","lat":50.636554,"lon":3.074244}]}""",
        )
        assertTrue(r.isEvents)
        assertFalse(r.isRoute)
        assertEquals("Éclats du rire !", r.events.single().name)
        val mini = regardMini("812", r)
        assertEquals(MiniOpen(tab = "evenements", look = "812"), mini.opens)
        assertEquals(listOf(true), mini.scene.pins.map { it.mika })
        assertEquals("Mika a cherché · 1 événement", mini.sub)
    }

    // ── Ce que chaque appel envoie ──────────────────────────────────────

    @Test fun `une liste filtrée autour de moi, ses filtres et here, sous le jeton`() = runBlocking {
        ok(contract("lieux.json"))
        val query = PlacesQuery(
            cat = "manger",
            near = LatLon(50.6371, 3.0638),
            limit = 30,
            filters = PlaceFilters(open = true, features = listOf("terrasse", "vegan"), cuisine = "  pizza  ", minRating = 4.0, sort = SORT_RATING),
            here = true,
        )
        val got = (api.list(query) as MoiApi.Result.Ok).value
        assertEquals(2, got.places.size)
        val req = server.takeRequest()
        assertEquals("/api/moi/carte/lieux", req.url.encodedPath)
        assertEquals("Bearer mw_secret", req.headers["Authorization"])
        val u = req.url
        assertEquals("manger", u.queryParameter("cat"))
        assertEquals("50.637100,3.063800", u.queryParameter("near"))
        assertEquals("1", u.queryParameter("open_now"))
        assertEquals("terrasse,vegan", u.queryParameter("features"))
        assertEquals("pizza", u.queryParameter("cuisine"))
        assertEquals("4", u.queryParameter("min_rating"))
        assertEquals("rating", u.queryParameter("sort"))
        assertEquals("1", u.queryParameter("here"))
        assertEquals("30", u.queryParameter("limit"))
        assertNull(u.queryParameter("bbox"))
    }

    @Test fun `rien qui ne dise rien ne part, l'ordre par défaut, une note 0, here sans ma position`() {
        val zone = Bounds(3.0, 50.6, 3.1, 50.7)
        val p = placesParams(PlacesQuery(q = "pizza", bbox = zone, filters = PlaceFilters(minRating = 0.0), here = true))
        assertNull(p["sort"])
        assertNull(p["min_rating"])
        // un point de la carte qu'on regarde n'est pas toi : here ne part qu'avec near
        assertNull(p["here"])
        assertNull(p["open_now"])
        assertEquals("", p["features"])
        assertEquals("3.00000,50.60000,3.10000,50.70000", p["bbox"])
        assertEquals("4.5", ratingParam(4.5))
        assertEquals("5", ratingParam(7.0))
        assertNull(ratingParam(Double.NaN))
        // la cuisine est bornée comme au serveur
        assertEquals(CUISINE_MAX, placesParams(PlacesQuery(filters = PlaceFilters(cuisine = "x".repeat(90))))["cuisine"]!!.length)
    }

    @Test fun `near=ici, ta position que le serveur garde, et son refus en mots`() = runBlocking {
        val ici = placesParams(PlacesQuery(cat = "manger", near = LatLon(50.0, 3.0), here = true, ici = true))
        assertEquals("ici", ici["near"])
        // « ici » est déjà ta position : here ne part pas
        assertNull(ici["here"])
        assertEquals("ici", eventsParams(EventsQuery(ici = true, radius = 12000))["near"])
        assertEquals("12000", eventsParams(EventsQuery(ici = true, radius = 12000))["radius"])
        val lieux = contract("lieux.json").trim().removeSuffix("}")
        ok("""$lieux, "here": {"lat": 50.6365, "lon": 3.0635, "label": "rue Nationale, Lille", "at": 1795155120000}}""")
        val got = (api.list(PlacesQuery(cat = "manger", ici = true)) as MoiApi.Result.Ok).value
        assertEquals("rue Nationale, Lille", got.here?.label)
        assertEquals(50.6365, got.here?.lat!!, 0.0)
        assertEquals("ici", server.takeRequest().url.queryParameter("near"))
        refuse(
            409,
            """{"error":"Ta position n'est pas connue ici : ton téléphone ne l'a pas donnée (Téléphone › Position, l'application ouverte), ou tu as cessé de la partager.","fields":{"near":"ta position n'est pas connue"}}""",
        )
        val refused = (api.events(EventsQuery(ici = true)) as MoiApi.Result.Failed).error
        assertTrue(refused.conflict)
        assertTrue(refused.message.startsWith("Ta position n'est pas connue ici"))
        assertEquals(mapOf("near" to "ta position n'est pas connue"), refused.fields)
    }

    @Test fun `la fiche d'un lieu, par son objet OSM ou son lieu de l'office`() = runBlocking {
        ok(contract("fiche.json"))
        val f = (api.place("n4021153781") as MoiApi.Result.Ok).value
        assertEquals("Magmatic", f.place.name)
        assertEquals("/api/moi/carte/lieu/n4021153781", server.takeRequest().url.encodedPath)
        ok(contract("fiche.json"))
        api.place("t:6b0e2f4a-8c1d-3e5f-9a7b-0c2d4e6f8a10")
        assertEquals("/api/moi/carte/lieu/t:6b0e2f4a-8c1d-3e5f-9a7b-0c2d4e6f8a10", server.takeRequest().url.encodedPath)
    }

    @Test fun `un identifiant d'une autre forme ne part pas`() = runBlocking {
        for (bad in listOf("../voyages", "l12/../x", "n12?x=1", "e:pas-un-uuid", "", "a:3", "T:6B0E2F4A-8C1D-3E5F-9A7B-0C2D4E6F8A10")) {
            val got = api.place(bad)
            assertTrue(bad, got is MoiApi.Result.Failed && (got as MoiApi.Result.Failed).error.gone)
            assertTrue(bad, api.refresh(bad) is MoiApi.Result.Failed)
        }
        for (bad in listOf("e:", "n4021153781", "e:450c81b3-6ffa-3d4e-9c1b-2a7f0e5d8c4")) {
            assertTrue(bad, api.event(bad) is MoiApi.Result.Failed)
        }
        assertEquals(0, server.requestCount)
    }

    @Test fun `Actualiser, un POST, le message et la fiche relue`() = runBlocking {
        val fiche = contract("fiche.json").trim().removePrefix("{")
        ok("""{"ok":true,"message":"Fiche relue.",$fiche""")
        val got = (api.refresh("n4021153781") as MoiApi.Result.Ok).value
        assertEquals("Fiche relue.", got.message)
        assertEquals("Magmatic", got.fiche.place.name)
        assertTrue(got.fiche.reviews!!.found)
        val req = server.takeRequest()
        assertEquals("POST", req.method)
        assertEquals("/api/moi/carte/lieu/n4021153781/actualiser", req.url.encodedPath)
    }

    @Test fun `les refus arrivent en mots, tels que le serveur les dit`() = runBlocking {
        refuse(503, """{"error":"Le quota du mois de Google (fiches avec avis) est atteint : il revient le 1er décembre à 09:00."}""")
        val quota = (api.refresh("n4021153781") as MoiApi.Result.Failed).error
        assertEquals(503, quota.code)
        assertEquals("Le quota du mois de Google (fiches avec avis) est atteint : il revient le 1er décembre à 09:00.", quota.message)
        refuse(429, """{"error":"Trop de fiches et d'événements demandés d'affilée : attends une minute."}""")
        assertEquals(
            "Trop de fiches et d'événements demandés d'affilée : attends une minute.",
            (api.place("l22871") as MoiApi.Result.Failed).error.message,
        )
        refuse(400, """{"error":"« min_rating » : une note de 0 à 5.","fields":{"min_rating":"de 0 à 5"}}""")
        val bad = (api.list(PlacesQuery(q = "x")) as MoiApi.Result.Failed).error
        assertEquals(mapOf("min_rating" to "de 0 à 5"), bad.fields)
        refuse(400, """{"error":"Une période d'au plus 366 jours.","fields":{"end":"un an au plus"}}""")
        assertEquals("Une période d'au plus 366 jours.", (api.events(EventsQuery(q = "x")) as MoiApi.Result.Failed).error.message)
        // sans un mot du serveur : le sien, jamais un code nu
        refuse(429, "")
        assertEquals("Trop d'essais d'un coup : attends un peu.", (api.event("e:450c81b3-6ffa-3d4e-9c1b-2a7f0e5d8c41") as MoiApi.Result.Failed).error.message)
    }

    @Test fun `les événements, autour d'un point à son rayon, ou dans une zone`() = runBlocking {
        ok(contract("evenements.json"))
        val query = EventsQuery(
            near = LatLon(50.6365, 3.0635),
            radius = 12000,
            start = "2026-11-21",
            end = "2026-11-22",
            themes = listOf("concerts", "fetes"),
            free = true,
        )
        val got = (api.events(query) as MoiApi.Result.Ok).value
        assertEquals(1, got.events.size)
        val u = server.takeRequest().url
        assertEquals("/api/moi/carte/evenements", u.encodedPath)
        assertEquals("50.636500,3.063500", u.queryParameter("near"))
        assertEquals("12000", u.queryParameter("radius"))
        assertEquals("2026-11-21", u.queryParameter("start"))
        assertEquals("2026-11-22", u.queryParameter("end"))
        assertEquals("concerts,fetes", u.queryParameter("themes"))
        assertEquals("1", u.queryParameter("free"))
        assertEquals("50", u.queryParameter("limit"))
        // dans une zone : pas de rayon ; une date illisible ne part pas ; le rayon reste dans ses bornes
        val zone = eventsParams(EventsQuery(bbox = Bounds(3.0, 50.6, 3.1, 50.7), radius = 12000, start = "2026-02-30", end = "demain"))
        assertNull(zone["radius"])
        assertNull(zone["start"])
        assertNull(zone["end"])
        assertEquals("100000", eventsParams(EventsQuery(near = LatLon(50.0, 3.0), radius = 900_000))["radius"])
        assertEquals("500", eventsParams(EventsQuery(near = LatLon(50.0, 3.0), radius = 10))["radius"])
    }

    @Test fun `la fiche d'un événement`() = runBlocking {
        ok(contract("evenement.json"))
        val f = (api.event("e:9a03e72c-35c0-3b1d-8e4f-6a2b0c1d3e5f") as MoiApi.Result.Ok).value
        assertEquals("Hello Lille", f.author)
        assertEquals("/api/moi/carte/evenement/e:9a03e72c-35c0-3b1d-8e4f-6a2b0c1d3e5f", server.takeRequest().url.encodedPath)
    }

    @Test fun `une photo se refait depuis sa référence, sur ce serveur seulement`() {
        val ref = "p:3f1c9a0e5b7d2c4e6f8a1b3c5d7e9f02"
        val url = api.photoUrl(ref)!!
        assertTrue(base.sameOrigin(url))
        assertEquals("/api/moi/carte/photo/$ref", url.encodedPath)
        // jamais le chemin d'une réponse, une adresse du dehors, ou une forme fausse
        for (bad in listOf(
            "/api/moi/carte/photo/$ref",
            "https://lh3.googleusercontent.com/abc",
            "p:3F1C9A0E5B7D2C4E6F8A1B3C5D7E9F02",
            "p:3f1c9a0e5b7d2c4e6f8a1b3c5d7e9f0",
            "p:../../voyages",
            "",
            null,
        )) {
            assertNull(bad, api.photoUrl(bad))
        }
        // hors session : rien
        val signedOut = CarteApi(MoiApi(client, { null }, {}, Dispatchers.IO))
        assertNull(signedOut.photoUrl(ref))
    }
}
