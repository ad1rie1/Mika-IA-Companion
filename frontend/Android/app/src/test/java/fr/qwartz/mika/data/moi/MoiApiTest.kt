package fr.qwartz.mika.data.moi

import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

/**
 * L'API par personne sous le jeton du téléphone (ADR 0235) : le jeton et jamais d'`Origin`, une clé d'envoi par
 * écriture, les refus du serveur en mots (et par champ), un 401 qui fait vérifier la session, le réseau dit à part.
 */
class MoiApiTest {
    private val server = MockWebServer()
    private val client = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).build()
    private var credentials: Credentials? = null
    private var unauthorized = 0
    private lateinit var api: MoiApi

    @Before fun start() {
        server.start()
        val base = (ServerBase.parse(server.url("/").toString()) as ServerBase.Parsed.Ok).base
        credentials = Credentials(base, "mw_secret")
        api = MoiApi(client, { credentials }, { unauthorized++ }, Dispatchers.IO)
    }

    @After fun stop() = server.close()

    @Test fun `une lecture porte le jeton, jamais d'Origin, et lit sa forme`() = runBlocking {
        server.enqueue(MockResponse.Builder().body("""{"username":"adrien","name":"Adrien","operator":true,"counts":{"mail":2},"inconnu":1}""").build())
        val got = api.get("", reader = Me.serializer())
        val me = (got as MoiApi.Result.Ok).value
        assertEquals("Adrien", me.shown)
        assertEquals(2, me.counts.mail)
        val req = server.takeRequest()
        assertEquals("/api/moi", req.url.encodedPath)
        assertEquals("Bearer mw_secret", req.headers["Authorization"])
        assertNull(req.headers["Origin"])
        assertNull(req.headers["Idempotency-Key"])
    }

    @Test fun `une écriture porte sa clé d'envoi et son corps JSON`() = runBlocking {
        server.enqueue(MockResponse.Builder().body("""{"ok":true,"message":"C'est fait."}""").build())
        val got = api.post("/account/name", buildJsonObject { put("name", JsonPrimitive("Moi")) }, key = "cle-1")
        assertEquals("C'est fait.", (got as MoiApi.Result.Ok).value.message)
        val req = server.takeRequest()
        assertEquals("POST", req.method)
        assertEquals("/api/moi/account/name", req.url.encodedPath)
        assertEquals("cle-1", req.headers["Idempotency-Key"])
        assertEquals("""{"name":"Moi"}""", req.body?.utf8())
    }

    @Test fun `un refus dit son message et ses champs`() = runBlocking {
        server.enqueue(MockResponse.Builder().code(400).body("""{"error":"Le nom est trop long.","fields":{"name":"60 caractères au plus"}}""").build())
        val err = (api.post("/account/name") as MoiApi.Result.Failed).error
        assertEquals(400, err.code)
        assertEquals("Le nom est trop long.", err.message)
        assertEquals(mapOf("name" to "60 caractères au plus"), err.fields)
    }

    @Test fun `un refus sans corps lisible dit quand même quelque chose`() = runBlocking {
        server.enqueue(MockResponse.Builder().code(409).body("<html>").build())
        val err = (api.get("/mail/boxes") as MoiApi.Result.Failed).error
        assertTrue(err.conflict)
        assertTrue(err.message.isNotBlank())
    }

    @Test fun `un 401 fait vérifier la session`() = runBlocking {
        server.enqueue(MockResponse.Builder().code(401).body("""{"error":"Authentification requise."}""").build())
        api.get("")
        assertEquals(1, unauthorized)
    }

    @Test fun `hors session, rien ne part`() = runBlocking {
        credentials = null
        val err = (api.get("") as MoiApi.Result.Failed).error
        assertEquals(401, err.code)
        assertEquals(0, server.requestCount)
    }

    @Test fun `une forme inattendue est un refus, pas une exception`() = runBlocking {
        server.enqueue(MockResponse.Builder().body("""{"counts":"beaucoup"}""").build())
        val got = api.get("", reader = Me.serializer())
        assertTrue(got is MoiApi.Result.Failed)
    }

    @Test fun `le réseau se dit à part`() = runBlocking {
        server.close()
        val err = (api.get("") as MoiApi.Result.Failed).error
        assertTrue(err.network)
    }

    @Test fun `les paramètres vides ne partent pas`() = runBlocking {
        server.enqueue(MockResponse.Builder().body("{}").build())
        api.get("/mail/messages", mapOf("box" to "pro", "q" to "", "state" to null))
        assertEquals("box=pro", server.takeRequest().url.encodedQuery)
    }
}
