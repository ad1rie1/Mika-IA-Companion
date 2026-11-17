package fr.qwartz.mika.data.moi.carte

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.RecordedRequest
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
 * Les itinéraires, les regards de Mika et tes voyages sur l'API par personne (`protocole-moi.md` § 10), sous le jeton de
 * ce téléphone : les formes lues, ce que chaque écriture envoie et sa clé d'envoi, les refus en mots (409, 404, 503), et
 * ce qui ne part pas (un identifiant qui n'est pas du serveur).
 */
class TripsApiTest {
    private val server = MockWebServer()
    private val client = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).build()
    private lateinit var trips: TripsApi
    private lateinit var carte: CarteApi

    @Before fun start() {
        server.start()
        val base = (ServerBase.parse(server.url("/").toString()) as ServerBase.Parsed.Ok).base
        val moi = MoiApi(client, { Credentials(base, "mw_secret") }, {}, Dispatchers.IO)
        trips = TripsApi(moi)
        carte = CarteApi(moi)
    }

    @After fun stop() {
        server.close()
    }

    private fun ok(body: String) = server.enqueue(MockResponse.Builder().body(body).build())
    private fun body(req: RecordedRequest): JsonObject = MikaJson.parseToJsonElement(req.body!!.utf8()).jsonObject

    @Test fun `un itinéraire, ses points, son mode, ce qu'il évite, ses tronçons et ses consignes`() = runBlocking {
        val shape = encodePolyline6(listOf(LatLon(50.637, 3.063), LatLon(45.899, 6.129)))
        ok(
            """{"distance_m":751000,"duration_s":25500,"legs":[{"distance_m":751000,"duration_s":25500,"shape":"$shape",
               "steps":[{"text":"Prendre l'A1 vers Paris","distance_m":2100,"duration_s":120}]}],
               "has_toll":true,"has_highway":true,"has_ferry":false,"provider":"FOSSGIS (Valhalla)"}""",
        )
        val r = (carte.route(listOf(LatLon(50.637, 3.063), LatLon(45.899, 6.129)), "voiture", listOf("peages", "ferries")) as MoiApi.Result.Ok).value
        assertEquals(751_000.0, r.distanceM, 0.0)
        assertTrue(r.hasToll)
        assertEquals("Prendre l'A1 vers Paris", r.legs.single().steps.single().text)
        assertEquals(2, safeDecode(r.legs.single().shape).size)
        val req = server.takeRequest().url
        assertEquals("/api/moi/carte/itineraire", req.encodedPath)
        assertEquals("50.637000,3.063000;45.899000,6.129000", req.queryParameter("points"))
        assertEquals("voiture", req.queryParameter("mode"))
        assertEquals("peages,ferries", req.queryParameter("avoid"))
        // à vélo, rien à éviter : la clé ne part pas
        ok("""{"distance_m":1,"duration_s":1,"legs":[]}""")
        carte.route(listOf(LatLon(50.0, 3.0), LatLon(49.0, 4.0)), "velo")
        assertNull(server.takeRequest().url.queryParameter("avoid"))
        server.enqueue(MockResponse.Builder().code(503).body("""{"error":"Les itinéraires ne sont pas encore prêts sur ce serveur."}""").build())
        val refused = (carte.route(listOf(LatLon(50.0, 3.0), LatLon(49.0, 4.0)), "pied") as MoiApi.Result.Failed).error
        assertEquals("Les itinéraires ne sont pas encore prêts sur ce serveur.", refused.message)
    }

    @Test fun `un regard de Mika, ses lieux, son trajet tel qu'elle l'a gardé, oublié, 404, un seq inventé ne part pas`() = runBlocking {
        ok(
            """{"kind":"look","title":"Lille → Annecy","what":"trajet","places":[{"name":"Lille","lat":50.637,"lon":3.063},
               {"name":"Annecy","lat":45.899,"lon":6.129,"kind_fr":null}],"route":{"mode":"voiture","distance_m":751000,
               "duration_s":25500,"shape":null,"avoid":["peages"]},"trip":"","at":1793000000000}""",
        )
        val r = (carte.regard("812") as MoiApi.Result.Ok).value
        assertTrue(r.isRoute)
        assertEquals(listOf("Lille", "Annecy"), r.places.map { it.name })
        assertEquals("", r.places[1].kindFr) // un null du serveur : le défaut
        assertEquals(listOf("peages"), r.route!!.avoid)
        assertNull(r.route!!.shape)
        assertEquals("/api/moi/carte/regards/812", server.takeRequest().url.encodedPath)
        // un regard d'avant ne dit pas ce qu'il évitait : `null`, et ce sont tes choix
        ok("""{"kind":"map","title":"Le lac","what":"","places":[],"route":{"mode":"pied"},"trip":"640","at":1}""")
        val map = (carte.regard("813") as MoiApi.Result.Ok).value
        assertNull(map.route!!.avoid)
        assertEquals("640", map.trip)
        server.takeRequest()
        server.enqueue(MockResponse.Builder().code(404).body("""{"error":"Introuvable."}""").build())
        assertTrue((carte.regard("814") as MoiApi.Result.Failed).error.gone)
        server.takeRequest()
        // un seq qui n'est pas du serveur : refusé ici, sans réseau
        assertTrue((carte.regard("../voyages") as MoiApi.Result.Failed).error.gone)
        assertEquals(3, server.requestCount)
    }

    @Test fun `tes voyages, la liste, un voyage, du jour 1 au dernier`() = runBlocking {
        ok(
            """{"trips":[{"id":"640","title":"Les Alpes","start":"2027-04-03","mode":"voiture","avoid":["peages"],"days":5,
               "stops":12,"updated":1793000000000,"mika":true}]}""",
        )
        val list = (trips.list() as MoiApi.Result.Ok).value
        assertEquals(12, list.single().stops)
        assertTrue(list.single().mika)
        val req = server.takeRequest()
        assertEquals("/api/moi/voyages", req.url.encodedPath)
        assertEquals("Bearer mw_secret", req.headers["Authorization"])
        ok(
            """{"id":"640","title":"Les Alpes","start":"2027-04-03","mode":"voiture","avoid":[],"updated":5,"mika":true,
               "days":[{"n":1,"date":"2027-04-03","stops":[{"id":"641","name":"Lille","kind":"Ta position","lat":50.6,
               "lon":3.06,"note":"","by":"toi"},{"id":"642","name":"Reims","kind":"","lat":null,"lon":null,"note":"vingt minutes","by":"mika"}]}]}""",
        )
        val t = (trips.read("640") as MoiApi.Result.Ok).value
        assertEquals(listOf("641", "642"), t.days.single().stops.map { it.id })
        assertTrue(t.days.single().stops[1].hers)
        assertNull(t.days.single().stops[1].lat)
        assertEquals("/api/moi/voyages/640", server.takeRequest().url.encodedPath)
        // un identifiant qui n'est pas du serveur : 404, sans réseau
        assertTrue((trips.read("640/supprimer") as MoiApi.Result.Failed).error.gone)
        assertEquals(2, server.requestCount)
    }

    @Test fun `créer, changer, supprimer, ce que le corps nomme, et la clé d'envoi de chaque geste`() = runBlocking {
        ok("""{"ok":true,"message":"Voyage créé.","id":"640"}""")
        val made = (trips.create(TripValues("Les Alpes", "", "voiture", listOf("peages", "ferries")), "cle-1") as MoiApi.Result.Ok).value
        assertEquals("640", made.id)
        val req = server.takeRequest()
        assertEquals("POST", req.method)
        assertEquals("/api/moi/voyages", req.url.encodedPath)
        assertEquals("cle-1", req.headers["Idempotency-Key"])
        assertNull(req.headers["Origin"])
        val sent = body(req)
        assertEquals("Les Alpes", sent["title"]!!.jsonPrimitive.content)
        assertEquals("", sent["start"]!!.jsonPrimitive.content)
        assertEquals(listOf("peages", "ferries"), sent["avoid"]!!.jsonArray.map { it.jsonPrimitive.content })
        // seulement ce qui a changé : une date vidée part vide, le reste ne part pas
        ok("""{"ok":true,"message":"Voyage modifié."}""")
        trips.change("640", TripValues(start = ""), "cle-2")
        val changed = server.takeRequest()
        assertEquals("/api/moi/voyages/640", changed.url.encodedPath)
        assertEquals(setOf("start"), body(changed).keys)
        ok("""{"ok":true,"message":"Voyage supprimé."}""")
        trips.remove("640", "cle-3")
        val removed = server.takeRequest()
        assertEquals("/api/moi/voyages/640/supprimer", removed.url.encodedPath)
        assertEquals("cle-3", removed.headers["Idempotency-Key"])
        // la borne des voyages : 409, en mots
        server.enqueue(MockResponse.Builder().code(409).body("""{"error":"Tu as déjà 50 voyages : supprimes-en un d'abord."}""").build())
        val full = (trips.create(TripValues("Un de plus"), "cle-4") as MoiApi.Result.Failed).error
        assertTrue(full.conflict)
        assertEquals("Tu as déjà 50 voyages : supprimes-en un d'abord.", full.message)
    }

    @Test fun `ses arrêts, ajouter, déplacer, noter, retirer, la situation a changé, 409`() = runBlocking {
        ok("""{"ok":true,"message":"Arrêt ajouté.","id":"650","deduped":false}""")
        val added = (trips.addStop("640", NewStop("Camping de l'Horizon", 45.866, 6.141, "Camping", 2, -1), "k1") as MoiApi.Result.Ok).value
        assertEquals("650", added.id)
        val add = server.takeRequest()
        assertEquals("/api/moi/voyages/640/arrets", add.url.encodedPath)
        val sent = body(add)
        assertEquals(45.866, sent["lat"]!!.jsonPrimitive.double, 0.0)
        assertEquals(2, sent["day"]!!.jsonPrimitive.int)
        assertEquals(-1, sent["index"]!!.jsonPrimitive.int)
        assertNull(sent["note"]) // sans note : rien
        // redit avec la même clé : le serveur dit qu'il l'avait déjà
        ok("""{"ok":true,"message":"Déjà fait.","id":"650","deduped":true}""")
        assertTrue((trips.addStop("640", NewStop("Camping", 45.0, 6.0, note = "réserver"), "k1") as MoiApi.Result.Ok).value.deduped)
        assertEquals("réserver", body(server.takeRequest())["note"]!!.jsonPrimitive.content)
        ok("""{"ok":true,"message":"Arrêt déplacé."}""")
        trips.moveStop("640", "650", 1, 0, "k2")
        val move = server.takeRequest()
        assertEquals("/api/moi/voyages/640/arrets/650", move.url.encodedPath)
        assertEquals(setOf("day", "index"), body(move).keys)
        ok("""{"ok":true,"message":"Note enregistrée."}""")
        trips.noteStop("640", "650", "", "k3")
        assertEquals("", body(server.takeRequest())["note"]!!.jsonPrimitive.content)
        ok("""{"ok":true,"message":"Arrêt retiré."}""")
        trips.removeStop("640", "650", "k4")
        assertEquals("/api/moi/voyages/640/arrets/650/retirer", server.takeRequest().url.encodedPath)
        server.enqueue(MockResponse.Builder().code(409).body("""{"error":"La situation a changé entre-temps. Relis, puis recommence."}""").build())
        val changed = (trips.moveStop("640", "650", 2, -1, "k5") as MoiApi.Result.Failed).error
        assertTrue(changed.conflict)
        assertTrue(refused(changed)) // refusé : la clé est usée
        // un arrêt qui n'est pas du serveur ne part pas
        assertTrue((trips.removeStop("640", "x", "k6") as MoiApi.Result.Failed).error.gone)
        assertEquals(6, server.requestCount)
    }

    @Test fun `son trajet, l'ordre d'un jour, les lieux le long du trajet, son GPX`() = runBlocking {
        ok(
            """{"days":[{"n":1,"distance_m":207000,"duration_s":8100,"legs":[{"from":"641","to":"642","distance_m":207000,
               "duration_s":8100,"shape":"","steps":[]}]}],"distance_m":207000,"duration_s":8100,"has_toll":false,
               "has_highway":true,"has_ferry":false,"provider":"Valhalla"}""",
        )
        val r = (trips.route("640") as MoiApi.Result.Ok).value
        assertEquals("642", r.days.single().legs.single().to)
        assertEquals("/api/moi/voyages/640/trajet", server.takeRequest().url.encodedPath)
        ok("""{"ok":true,"message":"Ordre appliqué.","order":["641","643","642"]}""")
        val order = (trips.optimize("640", 1, "k1") as MoiApi.Result.Ok).value
        assertEquals(listOf("641", "643", "642"), order.order)
        val opt = server.takeRequest()
        assertEquals("/api/moi/voyages/640/ordre", opt.url.encodedPath)
        assertEquals(1, body(opt)["day"]!!.jsonPrimitive.int)
        ok("""{"places":[{"id":"l3","name":"Monastère royal de Brou","kind_fr":"Monument","lat":46.2,"lon":5.24,"distance_m":2500,"along_m":600000}],"route":false}""")
        val along = (trips.along("640", cat = "voir") as MoiApi.Result.Ok).value
        assertFalse(along.route)
        assertEquals(600_000.0, along.places.single().alongM!!, 0.0)
        val q = server.takeRequest().url
        assertEquals("/api/moi/voyages/640/sur-la-route", q.encodedPath)
        assertEquals("voir", q.queryParameter("cat"))
        assertEquals("0", q.queryParameter("day"))
        assertEquals("10000", q.queryParameter("corridor"))
        assertEquals("12", q.queryParameter("limit"))
        assertEquals("/api/moi/voyages/640/gpx", trips.gpxUrl("640")!!.encodedPath)
        assertNull(trips.gpxUrl("../640"))
    }
}
