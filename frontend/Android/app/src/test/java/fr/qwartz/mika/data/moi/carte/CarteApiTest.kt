package fr.qwartz.mika.data.moi.carte

import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import okhttp3.Request
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

/**
 * La Carte sur l'API par personne (`protocole-moi.md` § 10) : ce qui est branché, le fond de carte, les lieux et les
 * adresses, sous le jeton de ce téléphone ; les refus en mots (503, 429) ; et le client de MapLibre, qui ne parle qu'à
 * ce serveur.
 */
class CarteApiTest {
    private val server = MockWebServer()
    private val other = MockWebServer()
    private val client = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).build()
    private lateinit var base: ServerBase
    private lateinit var api: CarteApi

    @Before fun start() {
        server.start()
        other.start()
        base = (ServerBase.parse(server.url("/").toString()) as ServerBase.Parsed.Ok).base
        api = CarteApi(MoiApi(client, { Credentials(base, "mw_secret") }, {}, Dispatchers.IO))
    }

    @After fun stop() {
        server.close()
        other.close()
    }

    private fun ok(body: String) = server.enqueue(MockResponse.Builder().body(body).build())

    @Test fun `ce qui est branché, et les catégories dans l'ordre de l'écran`() = runBlocking {
        ok(
            """{"places":{"ready":true,"count":182345,"built":1793000000000},"addresses":{"ready":false},
               "routing":{"ready":true,"provider":"Valhalla (FOSSGIS)","modes":["voiture","velo","pied"],"avoid":["peages"]},
               "categories":[{"id":"dormir","label":"Dormir"},{"id":"manger","label":"Manger"}],"neuf":1}""",
        )
        val info = (api.info() as MoiApi.Result.Ok).value
        assertTrue(info.places.ready)
        assertEquals(182345L, info.places.count)
        assertFalse(info.addresses.ready)
        assertEquals("Valhalla (FOSSGIS)", info.routing.provider)
        assertEquals(listOf("dormir", "manger"), info.categories.map { it.id })
        val req = server.takeRequest()
        assertEquals("/api/moi/carte", req.url.encodedPath)
        assertEquals("Bearer mw_secret", req.headers["Authorization"])
        assertNull(req.headers["Origin"])
    }

    @Test fun `le fond de carte, prêt, ou pourquoi pas`() = runBlocking {
        ok(
            """{"ready":true,"reason":"","kind":"vecteur","minzoom":0,"maxzoom":15,"bounds":[-5.2,41.3,9.6,51.1],
               "attribution":"© OpenStreetMap","tiles":"/api/moi/carte/fond/tiles/{z}/{x}/{y}?v=1a2b3c4d5e6f",
               "glyphs":"/api/moi/carte/fond/fonts/{fontstack}/{range}.pbf?v=1a2b3c4d5e6f",
               "sprite":"/api/moi/carte/fond/sprites/~1a2b3c4d5e6f/v4"}""",
        )
        val fond = (api.fond() as MoiApi.Result.Ok).value
        assertTrue(fond.ready)
        assertEquals(Bounds(-5.2, 41.3, 9.6, 51.1), fond.zone)
        assertEquals("/api/moi/carte/fond/sprites/~1a2b3c4d5e6f/v4", fond.sprite)
        assertEquals("/api/moi/carte/fond", server.takeRequest().url.encodedPath)
        // aucune carte réglée : `ready` faux et la raison, rien d'autre
        ok("""{"ready":false,"reason":"La carte n'est pas branchée sur ce serveur."}""")
        val none = (api.fond() as MoiApi.Result.Ok).value
        assertFalse(none.ready)
        assertEquals("La carte n'est pas branchée sur ce serveur.", none.reason)
        assertNull(none.glyphs)
        assertNull(none.zone)
    }

    @Test fun `les lieux, le texte, la catégorie, autour d'un point ou dans une zone`() = runBlocking {
        ok(
            """{"places":[{"id":"l12","name":"Camping de l'Horizon","kind":"camp_site","kind_fr":"Camping","category":"dormir",
               "lat":45.866,"lon":6.141,"town":"Sévrier","distance_m":5830.4,"along_m":null}]}""",
        )
        val got = (api.places(q = "  camping ", cat = "dormir", near = LatLon(45.899, 6.129), limit = 30) as MoiApi.Result.Ok).value
        val p = got.single()
        assertEquals("Camping", p.kindFr)
        assertEquals(5830.4, p.distanceM!!, 0.0)
        assertNull(p.alongM)
        assertEquals(LatLon(45.866, 6.141), p.at)
        val req = server.takeRequest()
        assertEquals("/api/moi/carte/lieux", req.url.encodedPath)
        assertEquals("camping", req.url.queryParameter("q"))
        assertEquals("dormir", req.url.queryParameter("cat"))
        assertEquals("45.899000,6.129000", req.url.queryParameter("near"))
        assertNull(req.url.queryParameter("bbox"))
        assertEquals("30", req.url.queryParameter("limit"))
        // dans une zone, sans texte ni catégorie : seuls la zone et le nombre partent
        ok("""{"places":[]}""")
        api.places(bbox = Bounds(6.0, 45.8, 6.3, 46.0))
        val zone = server.takeRequest().url
        assertEquals("6.00000,45.80000,6.30000,46.00000", zone.queryParameter("bbox"))
        assertEquals(setOf("bbox", "limit"), zone.queryParameterNames)
    }

    @Test fun `une adresse, seul le texte part, pas prête, le message du serveur`() = runBlocking {
        ok("""{"places":[{"id":"a:0","name":"12 Rue Royale 74000 Annecy","kind":"address","category":"adresse","lat":45.9,"lon":6.12,"town":"Annecy"}]}""")
        val got = (api.addresses(" 12 rue Royale ") as MoiApi.Result.Ok).value
        assertEquals("adresse", got.single().category)
        val req = server.takeRequest().url
        assertEquals("/api/moi/carte/adresses", req.encodedPath)
        assertEquals("12 rue Royale", req.queryParameter("q"))
        assertEquals("5", req.queryParameter("limit"))
        server.enqueue(MockResponse.Builder().code(503).body("""{"error":"La recherche d'adresses n'est pas encore prête sur ce serveur."}""").build())
        val refused = (api.addresses("12 rue Royale") as MoiApi.Result.Failed).error
        assertEquals(503, refused.code)
        assertEquals("La recherche d'adresses n'est pas encore prête sur ce serveur.", refused.message)
        server.enqueue(MockResponse.Builder().code(429).body("""{"error":"Trop de trajets ou d'adresses demandés d'affilée : attends une minute."}""").build())
        assertEquals(429, (api.places(q = "camping") as MoiApi.Result.Failed).error.code)
    }

    @Test fun `MapLibre ne parle qu'à ce serveur, le jeton vers lui, rien ailleurs`() {
        var session: Pair<ServerBase, String>? = base to "mw_secret"
        val maps = MapHttp.client(client) { session }
        server.enqueue(MockResponse.Builder().body("tuile").build())
        maps.newCall(Request.Builder().url(server.url("/api/moi/carte/fond/tiles/5/16/11?v=1")).build()).execute().use {
            assertEquals(200, it.code)
        }
        assertEquals("Bearer mw_secret", server.takeRequest().headers["Authorization"])
        // une autre adresse (une planche par défaut, un style qui la nommerait) : refusée ici, sans réseau
        maps.newCall(Request.Builder().url(other.url("/sprites/v4/light.json")).build()).execute().use {
            assertEquals(403, it.code)
            assertEquals(SameServerOnly.REFUSED, it.body.string())
        }
        assertEquals(0, other.requestCount)
        // hors session : rien ne part, pas même vers son serveur
        session = null
        maps.newCall(Request.Builder().url(server.url("/api/moi/carte/fond/tiles/5/16/11")).build()).execute().use {
            assertEquals(403, it.code)
        }
        assertEquals(1, server.requestCount)
    }

    @Test fun `une redirection vers une autre adresse ne se suit pas (R4-05)`() {
        val maps = MapHttp.client(client) { base to "mw_secret" }
        // un mandataire qui passe en HTTPS, une interception en clair : « la tuile est ailleurs »
        val elsewhere = other.url("/tiles/5/16/11.pbf").toString()
        server.enqueue(MockResponse.Builder().code(302).setHeader("Location", elsewhere).build())
        server.enqueue(MockResponse.Builder().code(301).setHeader("Location", elsewhere).build())
        for (status in listOf(302, 301)) {
            maps.newCall(Request.Builder().url(server.url("/api/moi/carte/fond/tiles/5/16/11?v=1")).build()).execute().use {
                // MapLibre reçoit la redirection telle quelle : une tuile en échec, rien de demandé ailleurs
                assertEquals(status, it.code)
            }
        }
        assertEquals(2, server.requestCount)
        assertEquals(0, other.requestCount)
    }
}
