package fr.qwartz.mika.data.moi.phone

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
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
 * Le Téléphone sur l'API par personne (`protocole-moi.md` § 5) : les formes lues (l'inconnu ignoré, les défauts), les
 * paramètres des lectures, révoquer un téléphone, les refus.
 */
class PhoneMoiApiTest {
    private val server = MockWebServer()
    private val client = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).build()
    private lateinit var api: PhoneMoiApi

    @Before fun start() {
        server.start()
        val base = (ServerBase.parse(server.url("/").toString()) as ServerBase.Parsed.Ok).base
        api = PhoneMoiApi(MoiApi(client, { Credentials(base, "mw_secret") }, {}, Dispatchers.IO))
    }

    @After fun stop() = server.close()

    private fun ok(body: String) = server.enqueue(MockResponse.Builder().body(body).build())

    @Test fun `ses conversations se lisent, sa réponse qui compte et les défauts`() = runBlocking {
        ok(
            """{"items":[{"key":"whatsapp|611ae22e6d5c431f8b537e638278435d","app":"whatsapp","app_name":"WhatsApp","group":true,
               "title":"Rando dimanche","count":12,"last_at":1790790060000,"futur":1,
               "last":{"id":"p34","at":1790790060000,"own":false,"sender":"Thomas Girard","text":"on décale à 9h ?"},
               "her":{"state":"offered","id":7,"decided_at":0}},{"key":"messages|ab"}]}""",
        )
        val items = (api.conversations() as MoiApi.Result.Ok).value
        val rando = items[0]
        assertTrue(rando.group)
        assertEquals("WhatsApp", rando.appName)
        assertEquals("Thomas Girard", rando.last?.sender)
        assertEquals(HerReply(OfferStates.OFFERED, 7, 0), rando.her)
        // une forme incomplète : rien de plus que la clé
        assertNull(items[1].her)
        assertNull(items[1].last)
        assertFalse(items[1].group)
        val url = server.takeRequest().url
        assertEquals("/api/moi/phone/conversations", url.encodedPath)
        assertEquals("100", url.queryParameter("size"))
    }

    @Test fun `un fil, ses messages et ses propositions`() = runBlocking {
        ok(
            """{"key":"whatsapp|611ae22e6d5c431f8b537e638278435d","app":"whatsapp","app_name":"WhatsApp","group":false,"title":"",
               "messages":[{"id":"p33","at":5,"own":false,"sender":"Léa","text":"tu viens ?"},{"id":"p34","at":6,"own":true,"text":"oui"}],
               "more":true,"offers":[{"id":7,"state":"sent","at":7,"expires":9,"decided_at":8,"reason":"","reply_to":"p33","text":"J'arrive"}]}""",
        )
        val t = (api.thread("whatsapp|611ae22e6d5c431f8b537e638278435d") as MoiApi.Result.Ok).value
        assertTrue(t.more)
        assertEquals("", t.messages[1].sender)
        assertTrue(t.messages[1].own)
        assertEquals(PhoneOffer(7, OfferStates.SENT, 7, 9, 8, "", "p33", "J'arrive"), t.offers.single())
        val url = server.takeRequest().url
        assertEquals("/api/moi/phone/thread", url.encodedPath)
        assertEquals("whatsapp|611ae22e6d5c431f8b537e638278435d", url.queryParameter("conversation"))
        assertEquals("50", url.queryParameter("size"))
        ok("""{"key":"k","messages":[]}""")
        api.thread("k", size = PhoneLimits.MAX)
        assertEquals("100", server.takeRequest().url.queryParameter("size"))
    }

    @Test fun `sa position, connue ou non, des coordonnées entières ou illisibles`() = runBlocking {
        ok("""{"known":true,"coords":{"lat":50.636512,"lon":3},"label":"rue Nationale, Lille","accuracy_m":12,"at":1790790060000}""")
        val p = (api.position() as MoiApi.Result.Ok).value
        assertTrue(p.known)
        assertEquals(PhoneCoords(50.636512, 3.0), p.coords)
        assertEquals(12.0, p.accuracyM, 0.0)
        assertEquals("/api/moi/phone/position", server.takeRequest().url.encodedPath)
        ok("""{"known":true,"coords":null,"label":"","accuracy_m":0,"at":5}""")
        assertNull((api.position() as MoiApi.Result.Ok).value.coords)
        server.takeRequest()
        ok("""{"known":false}""")
        assertEquals(PhonePosition(), (api.position() as MoiApi.Result.Ok).value)
    }

    @Test fun `ses téléphones, et en révoquer un avec sa clé d'envoi`() = runBlocking {
        ok(
            """{"items":[{"id":3,"label":"Android · samsung SM-S931B","created_at":1,"last_used":2,"revoked":false,"push":true},
               {"id":2,"label":"Android · Google Pixel 7a","revoked":true}],"apk":true}""",
        )
        val phones = (api.phones() as MoiApi.Result.Ok).value
        assertTrue(phones.apk)
        assertEquals(PhoneDevice(3, "Android · samsung SM-S931B", 1, 2, false, true), phones.items[0])
        assertFalse(phones.items[1].push)
        assertEquals("/api/moi/phone/phones", server.takeRequest().url.encodedPath)
        ok("""{"ok":true,"message":"Révoqué : ce téléphone ne reçoit plus rien."}""")
        val done = (api.revoke(2, key = "cle-1") as MoiApi.Result.Ok).value
        assertEquals("Révoqué : ce téléphone ne reçoit plus rien.", done.message)
        val req = server.takeRequest()
        assertEquals("/api/moi/phone/revoke", req.url.encodedPath)
        assertEquals("cle-1", req.headers["Idempotency-Key"])
        assertEquals(2L, MikaJson.parseToJsonElement(req.body!!.utf8()).jsonObject["id"]!!.jsonPrimitive.long)
    }

    @Test fun `une conversation qui n'est pas à toi, un téléphone déjà révoqué`() = runBlocking {
        server.enqueue(MockResponse.Builder().code(404).body("""{"error":"Introuvable."}""").build())
        assertTrue((api.thread("whatsapp|autre") as MoiApi.Result.Failed).error.gone)
        server.enqueue(MockResponse.Builder().code(409).body("""{"error":"Ce téléphone est déjà révoqué."}""").build())
        val err = (api.revoke(2) as MoiApi.Result.Failed).error
        assertTrue(err.conflict)
        assertEquals("Ce téléphone est déjà révoqué.", err.message)
    }
}
