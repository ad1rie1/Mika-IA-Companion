package fr.qwartz.mika.data.phone

import fr.qwartz.mika.core.Clock
import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.db.Kv
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
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
 * L'envoi des messages du téléphone (ADR 0120) : sous le jeton de l'app, sans `Origin`, par lots ; accepté, le lot quitte
 * la file ; refusé (403), la file se vide et le refus se voit ; hors de portée, on garde et on n'insiste pas avant 10 min
 * — sauf retour du réseau, lecteur branché, app au premier plan. Coupé, rien ne part et la file se vide.
 */
class PhoneOutboxTest {
    private val server = MockWebServer()
    private val client = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).build()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val kv = MemoryKv()
    private var enabled = true
    private var online = true
    private var now = 1_800_000_000_000L
    private lateinit var base: ServerBase
    private var credentials: Credentials? = null
    private lateinit var outbox: PhoneOutbox
    private val clock = object : Clock {
        override fun wallMs() = now
        override fun elapsedMs() = now
    }

    private class MemoryKv : PhoneKv {
        val map = mutableMapOf<String, String>()
        override suspend fun get(key: String): String? = map[key]
        override suspend fun put(key: String, value: String?) {
            if (value == null) map.remove(key) else map[key] = value
        }
    }

    @Before fun setUp() {
        server.start()
        base = (ServerBase.parse(server.url("/").toString()) as ServerBase.Parsed.Ok).base
        credentials = Credentials(base, "mw_telephone")
        outbox = PhoneOutbox(kv, PhoneApi(client), { credentials }, { enabled }, { online }, clock, scope)
    }

    @After fun tearDown() {
        server.close()
        client.dispatcher.executorService.shutdown()
        scope.cancel()
    }

    private fun msg(i: Int) = PhoneMessage(
        id = PhoneKeys.hash("m$i"),
        app = "whatsapp",
        thread = PhoneKeys.hash("t"),
        title = "",
        group = false,
        sender = PhoneKeys.hash("s"),
        name = "Léa",
        text = "message $i",
        time = 1_791_000_000_000 + i,
        own = false,
    )

    private fun reply(code: Int, body: String = """{"accepted":1,"known":0,"dropped":0}""", retryAfter: String? = null) =
        MockResponse.Builder().code(code).addHeader("Content-Type", "application/json").body(body)
            .apply { if (retryAfter != null) addHeader("Retry-After", retryAfter) }
            .build()

    private fun taken(): RecordedRequest = server.takeRequest(5, TimeUnit.SECONDS)!!

    private fun body(r: RecordedRequest) = MikaJson.parseToJsonElement(r.body!!.utf8()) as JsonObject

    @Test fun `le lot part sous le jeton de l'app, sans Origin, et quitte la file`() = runBlocking {
        assertEquals(2, outbox.add(listOf(msg(1), msg(2))))
        assertEquals(2, outbox.status.value.queued)
        server.enqueue(reply(200, """{"accepted":2,"known":0,"dropped":0}"""))
        outbox.flush(PhoneOutbox.Trigger.MESSAGE)
        val r = taken()
        assertEquals("POST", r.method)
        assertEquals("/api/phone/inbox", r.url.encodedPath)
        assertEquals("Bearer mw_telephone", r.headers["Authorization"])
        assertNull(r.headers["Origin"])
        val messages = body(r).getValue("messages").jsonArray
        assertEquals(2, messages.size)
        val first = messages[0].jsonObject
        assertEquals(
            setOf("id", "app", "thread", "title", "group", "sender", "name", "text", "time", "own"),
            first.keys,
        )
        assertEquals(msg(1).id, first.getValue("id").jsonPrimitive.content)
        assertEquals("message 1", first.getValue("text").jsonPrimitive.content)
        assertEquals(1_791_000_000_001, first.getValue("time").jsonPrimitive.long)
        assertEquals(0, outbox.status.value.queued)
        assertEquals(now, outbox.status.value.sentAt)
        // la notification redit les mêmes messages : rien de neuf, rien ne repart
        assertEquals(0, outbox.add(listOf(msg(1), msg(2))))
    }

    @Test fun `plus de 200 messages partent en plusieurs lots`() = runBlocking {
        outbox.add((1..250).map { msg(it) })
        server.enqueue(reply(200))
        server.enqueue(reply(200))
        outbox.flush(PhoneOutbox.Trigger.MESSAGE)
        assertEquals(200, body(taken()).getValue("messages").jsonArray.size)
        assertEquals(50, body(taken()).getValue("messages").jsonArray.size)
        assertEquals(0, outbox.status.value.queued)
    }

    @Test fun `refusé par le serveur, la file se vide et le refus se voit`() = runBlocking {
        outbox.add(listOf(msg(1)))
        outbox.settle(9, Settlement.SENT)
        server.enqueue(reply(403, """{"error":"réservé à la propriétaire"}"""))
        outbox.flush(PhoneOutbox.Trigger.MESSAGE)
        taken()
        assertEquals(1, server.requestCount)
        assertTrue(outbox.status.value.refused)
        assertEquals(0, outbox.status.value.queued)
        // dans l'heure, ce qui arrive n'est pas gardé
        assertEquals(0, outbox.add(listOf(msg(2))))
        now += PhoneOutbox.REFUSED_HOLD_MS
        assertEquals(1, outbox.add(listOf(msg(3))))
        server.enqueue(reply(200))
        outbox.flush(PhoneOutbox.Trigger.FOREGROUND)
        taken()
        assertFalse(outbox.status.value.refused)
    }

    @Test fun `hors de portée, on garde et on n'insiste pas avant 10 min, sauf déclencheur fort`() = runBlocking {
        // un serveur éteint : la connexion est refusée, comme un serveur de la maison vu de la 4G
        val dead = MockWebServer().also { it.start() }
        val deadBase = (ServerBase.parse(dead.url("/").toString()) as ServerBase.Parsed.Ok).base
        dead.close()
        credentials = Credentials(deadBase, "mw_telephone")
        outbox.add(listOf(msg(1)))
        outbox.flush(PhoneOutbox.Trigger.MESSAGE)
        assertEquals(1, outbox.status.value.queued)

        // de retour à la maison, mais un simple message neuf 5 min plus tard : pas d'essai
        credentials = Credentials(base, "mw_telephone")
        now += 5 * 60_000
        outbox.add(listOf(msg(2)))
        outbox.flush(PhoneOutbox.Trigger.MESSAGE)
        assertEquals(0, server.requestCount)
        // le réseau revient : tout de suite, et tout ce qui attendait part
        server.enqueue(reply(200))
        outbox.flush(PhoneOutbox.Trigger.NETWORK)
        assertEquals(2, body(taken()).getValue("messages").jsonArray.size)
        assertEquals(0, outbox.status.value.queued)
    }

    @Test fun `après 10 min un simple message réessaie`() = runBlocking {
        outbox.add(listOf(msg(1)))
        server.enqueue(reply(503, """{"error":"occupé"}"""))
        outbox.flush(PhoneOutbox.Trigger.MESSAGE)
        taken()
        outbox.flush(PhoneOutbox.Trigger.MESSAGE)
        assertEquals(1, server.requestCount)
        now += PhoneOutbox.RETRY_MS
        server.enqueue(reply(200))
        outbox.flush(PhoneOutbox.Trigger.MESSAGE)
        taken()
        assertEquals(0, outbox.status.value.queued)
    }

    @Test fun `un serveur occupé dit quand revenir`() = runBlocking {
        outbox.add(listOf(msg(1)))
        server.enqueue(reply(429, """{"error":"trop de requêtes"}""", retryAfter = "60"))
        outbox.flush(PhoneOutbox.Trigger.MESSAGE)
        taken()
        now += 59_000
        outbox.flush(PhoneOutbox.Trigger.MESSAGE)
        assertEquals(1, server.requestCount)
        now += 1_000
        server.enqueue(reply(200))
        outbox.flush(PhoneOutbox.Trigger.MESSAGE)
        taken()
        assertEquals(0, outbox.status.value.queued)
    }

    @Test fun `un lot illisible est écarté, le suivant part`() = runBlocking {
        outbox.add((1..201).map { msg(it) })
        server.enqueue(reply(413, """{"error":"trop gros"}"""))
        server.enqueue(reply(200))
        outbox.flush(PhoneOutbox.Trigger.MESSAGE)
        taken()
        assertEquals(1, body(taken()).getValue("messages").jsonArray.size)
        assertEquals(0, outbox.status.value.queued)
    }

    @Test fun `session morte ou serveur trop ancien, on garde`() = runBlocking {
        outbox.add(listOf(msg(1)))
        server.enqueue(reply(401, """{"error":"non"}"""))
        outbox.flush(PhoneOutbox.Trigger.FOREGROUND)
        taken()
        assertEquals(1, outbox.status.value.queued)
        server.enqueue(reply(404, """{"error":"inconnu"}"""))
        outbox.flush(PhoneOutbox.Trigger.FOREGROUND)
        taken()
        assertEquals(1, outbox.status.value.queued)
        assertTrue(outbox.status.value.outdated)
    }

    @Test fun `le sort des propositions part avec les messages`() = runBlocking {
        outbox.settle(41, Settlement.SENT)
        outbox.settle(42, Settlement.COPIED, SettleReason.NO_ACTION)
        server.enqueue(reply(200, """{"settled":2,"unknown":0}"""))
        outbox.flush(PhoneOutbox.Trigger.MESSAGE)
        val r = taken()
        assertEquals("/api/phone/settled", r.url.encodedPath)
        assertEquals("Bearer mw_telephone", r.headers["Authorization"])
        assertNull(r.headers["Origin"])
        val items = body(r).getValue("items") as JsonArray
        assertEquals(41, items[0].jsonObject.getValue("id").jsonPrimitive.long)
        assertEquals("sent", items[0].jsonObject.getValue("result").jsonPrimitive.content)
        assertEquals("", items[0].jsonObject.getValue("reason").jsonPrimitive.content)
        assertEquals("copied", items[1].jsonObject.getValue("result").jsonPrimitive.content)
        assertEquals("no_action", items[1].jsonObject.getValue("reason").jsonPrimitive.content)
        assertNull(kv.map[Kv.PHONE_QUEUE]?.takeIf { "\"settled\":[{" in it })
    }

    @Test fun `coupé, rien ne part et la file se vide, et rien sans session ni réseau`() = runBlocking {
        outbox.add(listOf(msg(1)))
        online = false
        outbox.flush(PhoneOutbox.Trigger.FOREGROUND)
        credentials = null
        online = true
        outbox.flush(PhoneOutbox.Trigger.FOREGROUND)
        assertEquals(0, server.requestCount)
        assertEquals(1, outbox.status.value.queued)
        enabled = false
        assertEquals(0, outbox.add(listOf(msg(2))))
        outbox.flush(PhoneOutbox.Trigger.FOREGROUND)
        assertEquals(0, outbox.status.value.queued)
        assertNull(kv.map[Kv.PHONE_QUEUE])
        assertEquals(0, server.requestCount)
    }

    @Test fun `la file survit au processus`() = runBlocking {
        outbox.add(listOf(msg(1), msg(2)))
        val reborn = PhoneOutbox(kv, PhoneApi(client), { credentials }, { enabled }, { online }, clock, scope)
        reborn.init()
        assertEquals(2, reborn.status.value.queued)
        assertEquals(0, reborn.add(listOf(msg(2))))
    }
}
