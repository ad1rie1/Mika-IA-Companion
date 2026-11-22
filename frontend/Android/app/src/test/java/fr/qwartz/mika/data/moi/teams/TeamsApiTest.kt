package fr.qwartz.mika.data.moi.teams

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.refusalText
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
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
 * Teams sur l'API par personne (`protocole-moi.md` § 4) : les formes lues (l'inconnu ignoré, les défauts), les
 * paramètres des lectures, les corps des écritures, la clé d'envoi, les refus en mots.
 */
class TeamsApiTest {
    private val server = MockWebServer()
    private val client = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).build()
    private lateinit var api: TeamsApi

    @Before fun start() {
        server.start()
        val base = (ServerBase.parse(server.url("/").toString()) as ServerBase.Parsed.Ok).base
        api = TeamsApi(MoiApi(client, { Credentials(base, "mw_secret") }, {}, Dispatchers.IO))
    }

    @After fun stop() = server.close()

    private fun ok(body: String = """{"ok":true,"message":"C'est fait."}""") =
        server.enqueue(MockResponse.Builder().body(body).build())

    private fun sentJson(): JsonObject = MikaJson.parseToJsonElement(server.takeRequest().body!!.utf8()).jsonObject

    @Test fun `ses comptes se lisent, l'inconnu ignoré et les défauts posés`() = runBlocking {
        ok(
            """{"plugged":true,"enabled":true,"nouveau":1,"accounts":[{"key":"principal","name":"Atelier","level":"proprietaire",
               "enabled":true,"last_batch":1790790060000,"self_name":"Adrien Moreau","extension_key":{"hint":"mk_3f","created_at":1},
               "drafts_waiting":2,"owner_name":"","common":false,"futur":[1]},{"key":"lea","name":"Perso"}]}""",
        )
        val got = (api.accounts() as MoiApi.Result.Ok).value
        val mine = got.accounts[0]
        assertTrue(mine.own)
        assertEquals("Adrien Moreau", mine.selfName)
        assertEquals("mk_3f", mine.extensionKey?.hint)
        assertEquals(2, mine.draftsWaiting)
        // un compte sans niveau n'ouvre que la lecture
        assertEquals(Levels.READ, got.accounts[1].level)
        assertFalse(got.accounts[1].own)
        assertNull(got.accounts[1].extensionKey)
        assertEquals("/api/moi/teams/accounts", server.takeRequest().url.encodedPath)
    }

    @Test fun `ses conversations portent le compte et la recherche, et sa réponse en chemin`() = runBlocking {
        ok(
            """{"items":[{"key":"19:lumen","account":"principal","title":"Projet Lumen","kind":"group","last_at":1790790060000,
               "messages":12,"last":{"ref":"m9","author":"Karim Haddad","author_id":"8:k","at":1790790060000,"text":"la démo tourne",
               "own":false,"mentions_me":true},"her":{"state":"attend","draft":"r1"}},{"key":"a~19:x","account":"a"}]}""",
        )
        val items = (api.conversations(account = "principal", q = " lumen ") as MoiApi.Result.Ok).value
        assertEquals("r1", items[0].her?.draft)
        assertTrue(items[0].last!!.mentionsMe)
        assertEquals(Kinds.OTHER, items[1].kind)
        assertNull(items[1].last)
        val url = server.takeRequest().url
        assertEquals("/api/moi/teams/conversations", url.encodedPath)
        assertEquals("principal", url.queryParameter("account"))
        assertEquals("lumen", url.queryParameter("q"))
        assertEquals("100", url.queryParameter("size"))
        ok("""{"items":[]}""")
        api.conversations()
        val all = server.takeRequest().url
        assertNull(all.queryParameter("account"))
        assertNull(all.queryParameter("q"))
    }

    @Test fun `un fil, ses plus anciens, ses réponses et tes messages en attente`() = runBlocking {
        ok(
            """{"key":"19:marc","account":"principal","title":"Marc Delmas","kind":"dm","more":true,
               "messages":[{"ref":"t1","author":"Marc Delmas","author_id":"8:marc","at":5,"text":"Salut"}],
               "replies":[{"id":"r1","account":"principal","conversation":"19:marc","in_reply_to":"t1","state":"attend",
               "mode":"validation","expires":9,"answered":false,"body":"Oui","sent_text":"","to_fill":false,
               "preview":{"text":"Oui\n— Mika","digest":"d1","blocked":""}}],
               "pending":[{"id":"p1","body":"ok","at":6,"state":"en_file","by":"user_1"}],"under_way":true,"asked":false}""",
        )
        val t = (api.thread("19:marc") as MoiApi.Result.Ok).value
        assertTrue(t.more && t.underWay)
        assertEquals("d1", t.replies.single().preview?.digest)
        assertEquals(OwnStates.QUEUED, t.pending!!.single().state)
        val first = server.takeRequest().url
        assertEquals("/api/moi/teams/thread", first.encodedPath)
        assertEquals("19:marc", first.queryParameter("conversation"))
        assertNull(first.queryParameter("before"))
        assertEquals("50", first.queryParameter("size"))
        // un moteur qui ne dit pas `pending` : `null`, pas une liste vide (l'écran ne s'y fie pas)
        ok("""{"key":"19:marc","messages":[]}""")
        val older = (api.thread("19:marc", before = 1790790060000) as MoiApi.Result.Ok).value
        assertNull(older.pending)
        assertEquals("1790790060000", server.takeRequest().url.queryParameter("before"))
    }

    @Test fun `un message qui en cite un autre porte sa citation, sans citation null`() = runBlocking {
        ok(
            """{"key":"19:lumen","kind":"group","messages":[
               {"ref":"t1","author":"Karim Haddad","author_id":"8:k","at":5,"text":"La démo tourne ?","quote":null},
               {"ref":"t2","author":"Léa Martin","author_id":"8:l","at":6,"text":"Chez moi, oui.",
                "quote":{"author":"Karim Haddad","author_id":"8:orgid:k","preview":"La démo tourne ?","at":5,"ref":"t1","futur":1}},
               {"ref":"t3","author":"Léa Martin","at":7,"text":"Et là ?",
                "quote":{"author":"Marc Delmas","author_id":"8:orgid:m","preview":"un vieux message","at":4,"ref":""}},
               {"ref":"t4","author":"Marc Delmas","at":8,"text":"d'avant l'ADR 0305"}]}""",
        )
        val m = (api.thread("19:lumen") as MoiApi.Result.Ok).value.messages
        assertNull(m[0].quote)
        assertEquals(TeamsQuote(author = "Karim Haddad", authorId = "8:orgid:k", preview = "La démo tourne ?", at = 5, ref = "t1"), m[1].quote)
        assertEquals("Chez moi, oui.", m[1].text)
        // le message cité n'est pas chez elle : sa référence est vide
        assertEquals("", m[2].quote!!.ref)
        assertNull(m[3].quote)
    }

    @Test fun `ses réponses dans tes comptes`() = runBlocking {
        ok(
            """{"items":[{"id":"r1","account":"principal","conversation":"19:marc","title":"Marc Delmas","state":"refuse",
               "answered":true,"note":"Répondu autrement","asked":true,"preview":null}]}""",
        )
        val r = (api.replies() as MoiApi.Result.Ok).value.single()
        assertTrue(r.answered && r.asked)
        assertNull(r.preview)
        assertEquals("/api/moi/teams/replies", server.takeRequest().url.encodedPath)
    }

    @Test fun `ton message part avec sa clé d'envoi, « en réponse à » seulement s'il y en a un`() = runBlocking {
        ok("""{"ok":true,"message":"En file : l'extension de ce compte l'enverra dans Teams."}""")
        val got = api.send("19:marc", "Je regarde ça", key = "cle-1")
        assertEquals("En file : l'extension de ce compte l'enverra dans Teams.", (got as MoiApi.Result.Ok).value.message)
        val req = server.takeRequest()
        assertEquals("/api/moi/teams/send", req.url.encodedPath)
        assertEquals("cle-1", req.headers["Idempotency-Key"])
        val body = MikaJson.parseToJsonElement(req.body!!.utf8()).jsonObject
        assertEquals("19:marc", body["conversation"]!!.jsonPrimitive.content)
        assertEquals("Je regarde ça", body["body"]!!.jsonPrimitive.content)
        assertNull(body["reply_to"])
        ok()
        api.send("19:marc", "ok", replyTo = "t1")
        assertEquals("t1", sentJson()["reply_to"]!!.jsonPrimitive.content)
    }

    @Test fun `préremplir, demandé, déjà demandé, ou une réponse en chemin`() = runBlocking {
        ok("""{"ok":true,"message":"Demandé : elle la préparera à son prochain moment de travail.","draft":"","asked":true}""")
        val asked = (api.prefill("t1", key = "cle-2") as MoiApi.Result.Ok).value
        assertTrue(asked.asked)
        val req = server.takeRequest()
        assertEquals("/api/moi/teams/prefill", req.url.encodedPath)
        assertEquals("cle-2", req.headers["Idempotency-Key"])
        val body = MikaJson.parseToJsonElement(req.body!!.utf8()).jsonObject
        assertEquals("t1", body["message"]!!.jsonPrimitive.content)
        assertNull(body["instruction"])
        ok("""{"ok":true,"message":"Une réponse est déjà en chemin.","draft":"r1","asked":false}""")
        val pending = (api.prefill("t1", "plus court") as MoiApi.Result.Ok).value
        assertEquals("r1", pending.draft)
        assertEquals("Une réponse est déjà en chemin.", pending.message)
        assertEquals("plus court", sentJson()["instruction"]!!.jsonPrimitive.content)
    }

    @Test fun `décider de ses réponses`() = runBlocking {
        ok()
        api.replySend("r1", "d1", key = "cle-3")
        val req = server.takeRequest()
        assertEquals("/api/moi/teams/reply/send", req.url.encodedPath)
        assertEquals("cle-3", req.headers["Idempotency-Key"])
        val sent = MikaJson.parseToJsonElement(req.body!!.utf8()).jsonObject
        assertEquals("r1", sent["id"]!!.jsonPrimitive.content)
        assertEquals("d1", sent["seen"]!!.jsonPrimitive.content)
        ok()
        api.replyEdit("r1", "Ma version")
        assertEquals("Ma version", sentJson()["body"]!!.jsonPrimitive.content)
        ok()
        api.replyRefuse("r1", "pas besoin")
        assertEquals("pas besoin", sentJson()["note"]!!.jsonPrimitive.content)
        ok()
        api.replyRedo("r1", "plus court")
        assertEquals("plus court", sentJson()["instruction"]!!.jsonPrimitive.content)
    }

    @Test fun `un refus se dit en mots, champ par champ`() = runBlocking {
        server.enqueue(
            MockResponse.Builder().code(400)
                .body("""{"error":"« conversation » : 400 caractères au plus.","fields":{"conversation":"400 caractères au plus"}}""").build(),
        )
        val err = (api.send("x".repeat(401), "ok") as MoiApi.Result.Failed).error
        assertEquals("Discussion : 400 caractères au plus", refusalText(err.message, err.fields))
        server.enqueue(MockResponse.Builder().code(409).body("""{"error":"Teams est désactivé : elle n'y prépare rien."}""").build())
        val off = (api.prefill("t1") as MoiApi.Result.Failed).error
        assertTrue(off.conflict)
        assertEquals("Teams est désactivé : elle n'y prépare rien.", off.message)
        server.enqueue(MockResponse.Builder().code(404).body("""{"error":"Introuvable."}""").build())
        assertTrue((api.thread("autre~19:x") as MoiApi.Result.Failed).error.gone)
    }
}
