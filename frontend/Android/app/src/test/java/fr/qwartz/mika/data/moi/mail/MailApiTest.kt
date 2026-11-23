package fr.qwartz.mika.data.moi.mail

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.Work
import fr.qwartz.mika.data.moi.WorkSteps
import fr.qwartz.mika.data.moi.refusalText
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import okhttp3.RequestBody.Companion.toRequestBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

/**
 * Mail sur l'API par personne (`protocole-moi.md` § 3) : les formes lues (l'inconnu ignoré, les défauts), les
 * paramètres des listes, les corps des écritures en JSON et en `multipart`, la clé d'envoi, les refus en mots.
 */
class MailApiTest {
    private val server = MockWebServer()
    private val client = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).build()
    private lateinit var api: MailApi

    @Before fun start() {
        server.start()
        val base = (ServerBase.parse(server.url("/").toString()) as ServerBase.Parsed.Ok).base
        api = MailApi(MoiApi(client, { Credentials(base, "mw_secret") }, {}, Dispatchers.IO))
    }

    @After fun stop() = server.close()

    private fun ok(body: String = """{"ok":true,"message":"C'est fait."}""") =
        server.enqueue(MockResponse.Builder().body(body).build())

    /** La valeur d'un champ d'un corps `multipart` ; `null` s'il n'y est pas. */
    private fun part(text: String, name: String): String? =
        Regex("form-data; name=\"$name\"\r\n(?:[^\r\n]+\r\n)*\r\n(.*?)\r\n--", RegexOption.DOT_MATCHES_ALL).find(text)?.groupValues?.get(1)

    private fun sentJson(): JsonObject {
        val req = server.takeRequest()
        return MikaJson.parseToJsonElement(req.body!!.utf8()).jsonObject
    }

    @Test fun `ses boîtes se lisent, l'inconnu ignoré et les défauts posés`() = runBlocking {
        ok(
            """{"plugged":true,"read_on_open":"3s","nouveau":1,"boxes":[{"key":"pro","name":"Atelier","address":"a@x.fr",
               "level":"proprietaire","can_send":true,"drafts_waiting":2,"owner_name":"","futur":[1],
               "folders":[{"name":"INBOX","label":"Réception","role":"inbox","polled":true,"total":12,"unseen":3}]},
               {"key":"lea","name":"Perso","address":"l@x.fr"}]}""",
        )
        val got = (api.boxes() as MoiApi.Result.Ok).value
        assertEquals("3s", got.readOnOpen)
        assertEquals(3000L, ReadOnOpen.delayMs(got.readOnOpen))
        val pro = got.boxes[0]
        assertTrue(pro.own && pro.canSend)
        assertEquals(2, pro.draftsWaiting)
        assertEquals(3, unseenOf(pro))
        // une boîte sans niveau n'ouvre que la lecture
        assertEquals(Levels.READ, got.boxes[1].level)
        assertEquals("/api/moi/mail/boxes", server.takeRequest().url.encodedPath)
    }

    @Test fun `une page de messages porte la vue, et ce qu'elle a fait de chacun`() = runBlocking {
        ok(
            """{"total":32,"page":2,"size":25,"items":[{"ref":"pro:<a@x>","box":"pro","folder":"INBOX",
               "from":{"name":"Léa","address":"lea@x.fr"},"subject":"Devis","date":1790790060000,"seen":false,
               "attachments":1,"her":{"noticed":true,"needs_reply":true,"draft":"d1"},"triage":"read"},
               {"ref":"pro:<b@x>","box":"pro","her":null}]}""",
        )
        val page = (api.messages(messagesQuery(MailView.Folder("pro", "INBOX"), MailStates.NEEDS_REPLY, "devis", 2, 25)) as MoiApi.Result.Ok).value
        assertEquals(32, page.total)
        val first = page.items[0]
        assertFalse(first.seen)
        assertEquals("d1", first.her?.draft)
        assertTrue(first.her!!.needsReply)
        // ses consignes de tri : absentes, ni alerte ni dossier
        assertFalse(first.her!!.alert)
        assertEquals("", first.her!!.filed)
        assertNull(page.items[1].her)
        // son tri, au niveau du mail ; absent, rien à dire
        assertEquals("read", first.triage)
        assertEquals("", page.items[1].triage)
        val q = server.takeRequest().url
        assertEquals("/api/moi/mail/messages", q.encodedPath)
        assertEquals("pro", q.queryParameter("box"))
        assertEquals("INBOX", q.queryParameter("folder"))
        assertEquals("needs_reply", q.queryParameter("state"))
        assertEquals("devis", q.queryParameter("q"))
        assertEquals("2", q.queryParameter("page"))
    }

    @Test fun `un mail entier, sa référence passée telle quelle`() = runBlocking {
        ok(
            """{"ref":"pro:<a+b@x>","box":"pro","body":"Bonjour\n> cité","sent":true,"received":true,"complete":false,
               "attachments":[{"part":"0","name":"devis.pdf","mime":"application/pdf","size":217088}],
               "her":{"summary":"Un devis au-dessus du budget.","alert":true,"filed":"INBOX.Devis"},"triage":"waiting","images":{"remote":true}}""",
        )
        val m = (api.message("pro:<a+b@x>") as MoiApi.Result.Ok).value
        assertEquals("Un devis au-dessus du budget.", m.her?.summary)
        assertEquals("waiting", m.triage)
        assertTrue(m.her!!.alert)
        assertEquals("INBOX.Devis", m.her!!.filed)
        assertEquals("0", m.attachments.single().part)
        assertTrue(answerable(m))
        assertFalse(m.complete)
        assertEquals("pro:<a+b@x>", server.takeRequest().url.queryParameter("ref"))
    }

    @Test fun `où elle en est dans le mail entier - présent, null, ou absent d'un serveur d'avant`() = runBlocking {
        ok("""{"ref":"pro:<a@x>","her":{"asked":true},"work":{"step":"thinking","label":"","since":1790000004000,"started":1790000000000}}""")
        val m = (api.message("pro:<a@x>") as MoiApi.Result.Ok).value
        assertEquals(Work(WorkSteps.THINKING, "", 1_790_000_004_000, 1_790_000_000_000), m.work)
        ok("""{"ref":"pro:<a@x>","work":null}""")
        assertNull((api.message("pro:<a@x>") as MoiApi.Result.Ok).value.work)
        // un serveur d'avant l'ADR 0306 ne le dit pas
        ok("""{"ref":"pro:<a@x>"}""")
        assertNull((api.message("pro:<a@x>") as MoiApi.Result.Ok).value.work)
    }

    @Test fun `où elle en est se relit par sa route légère, la référence passée telle quelle`() = runBlocking {
        ok("""{"work":{"step":"tool","label":"Lire un mail","since":7,"started":5},"asked":true,"draft":""}""")
        val going = (api.work("pro:<a+b@x>") as MoiApi.Result.Ok).value
        assertEquals(MailWork(Work(WorkSteps.TOOL, "Lire un mail", 7, 5), asked = true, draft = ""), going)
        val url = server.takeRequest().url
        assertEquals("/api/moi/mail/work", url.encodedPath)
        assertEquals("pro:<a+b@x>", url.queryParameter("ref"))
        // son brouillon est arrivé
        ok("""{"work":null,"asked":false,"draft":"d7"}""")
        val arrived = (api.work("pro:<a@x>") as MoiApi.Result.Ok).value
        assertEquals("d7", arrived.draft)
        assertNull(arrived.work)
        ok("""{}""")
        assertEquals(MailWork(), (api.work("pro:<a@x>") as MoiApi.Result.Ok).value)
    }

    @Test fun `ses brouillons et ses correspondants`() = runBlocking {
        ok(
            """{"items":[{"id":"d1","box":"pro","state":"attend","decides":true,"in_reply_to":"pro:<a@x>",
               "original":{"subject":"Maquettes","from":"Léa"},"to":"lea@x.fr","to_people":[{"name":"Léa","address":"lea@x.fr"}],
               "preview":{"sender":"Atelier <a@x.fr>","to":"Léa <lea@x.fr>","text":"Salut","digest":"abc","blocked":""}}]}""",
        )
        val d = (api.drafts() as MoiApi.Result.Ok).value.single()
        assertTrue(d.waiting && d.decides)
        assertEquals("abc", d.preview?.digest)
        assertEquals("Maquettes", d.original?.subject)
        server.takeRequest()
        ok("""{"items":[{"address":"lea@x.fr","name":"Léa","received":3,"sent":1,"last":1}]}""")
        val c = (api.contacts("lé", 6) as MoiApi.Result.Ok).value.single()
        assertEquals("Léa", c.name)
        val url = server.takeRequest().url
        assertEquals("lé", url.queryParameter("q"))
        assertEquals("6", url.queryParameter("size"))
        assertNull(url.queryParameter("box"))
    }

    @Test fun `un mail nouveau part en JSON, avec sa clé d'envoi`() = runBlocking {
        ok()
        val got = api.send("pro", Outgoing("Léa <lea@x.fr>", "", "m@x.fr", "Bonjour", "Texte"), key = "cle-1")
        assertEquals("C'est fait.", (got as MoiApi.Result.Ok).value.message)
        val req = server.takeRequest()
        assertEquals("/api/moi/mail/send", req.url.encodedPath)
        assertEquals("cle-1", req.headers["Idempotency-Key"])
        val body = MikaJson.parseToJsonElement(req.body!!.utf8()).jsonObject
        assertEquals("pro", body["box"]!!.jsonPrimitive.content)
        assertEquals("Léa <lea@x.fr>", body["to"]!!.jsonPrimitive.content)
        assertEquals("", body["cc"]!!.jsonPrimitive.content)
        assertEquals("m@x.fr", body["bcc"]!!.jsonPrimitive.content)
        assertEquals("Texte", body["body"]!!.jsonPrimitive.content)
    }

    @Test fun `une réponse dit si elle cite le mail`() = runBlocking {
        ok()
        api.reply("pro:<a@x>", Outgoing("lea@x.fr", subject = "Re: Devis", body = "Merci"), quote = true)
        val body = sentJson()
        assertEquals("pro:<a@x>", body["ref"]!!.jsonPrimitive.content)
        assertEquals("true", body["quote"]!!.jsonPrimitive.content)
    }

    @Test fun `avec des fichiers, le même envoi part en multipart`() = runBlocking {
        ok()
        val piece = OutgoingPiece("devis.pdf", "application/pdf", 4) { "%PDF".toRequestBody() }
        api.forward("pro:<a@x>", Outgoing("m@x.fr", subject = "Tr : Devis", body = ""), attachments = true, files = listOf(piece), key = "cle-2")
        val req = server.takeRequest()
        assertEquals("/api/moi/mail/forward", req.url.encodedPath)
        assertEquals("cle-2", req.headers["Idempotency-Key"])
        assertTrue(req.headers["Content-Type"]!!.startsWith("multipart/form-data"))
        val text = req.body!!.utf8()
        assertEquals("pro:<a@x>", part(text, "ref"))
        assertEquals("m@x.fr", part(text, "to"))
        // un vrai vaut 1 ; un champ vide ne part pas (le corps d'un transfert peut l'être)
        assertEquals("1", part(text, "attachments"))
        assertNull(part(text, "body"))
        assertNull(part(text, "cc"))
        assertTrue(text.contains("name=\"files\"; filename=\"devis.pdf\""))
        assertTrue(text.contains("Content-Type: application/pdf"))
        assertTrue(text.contains("%PDF"))
    }

    @Test fun `ranger porte ses mails et son geste, déplacer, son dossier`() = runBlocking {
        ok()
        api.tidy(listOf("pro:<a@x>", "pro:<b@x>"), "archive")
        val body = sentJson()
        assertEquals(2, body["refs"]!!.jsonArray.size)
        assertEquals("archive", body["gesture"]!!.jsonPrimitive.content)
        assertNull(body["folder"])
        ok("""{"ok":true,"message":"2 mails déplacés dans « Clients ».","moved":2}""")
        val moved = (api.tidy(listOf("pro:<a@x>"), "move", "Clients") as MoiApi.Result.Ok).value
        assertEquals(2, moved.moved)
        assertEquals("Clients", sentJson()["folder"]!!.jsonPrimitive.content)
    }

    @Test fun `préremplir rend la demande, ou son brouillon qui attend`() = runBlocking {
        ok("""{"ok":true,"message":"Elle a déjà préparé une réponse.","draft":"d7","asked":false}""")
        val got = (api.prefill("pro:<a@x>") as MoiApi.Result.Ok).value
        assertEquals("d7", got.draft)
        val body = sentJson()
        assertNull(body["instruction"])
        ok("""{"ok":true,"message":"Demandé.","draft":"","asked":true}""")
        assertTrue((api.prefill("pro:<a@x>", "plus court") as MoiApi.Result.Ok).value.asked)
        assertEquals("plus court", sentJson()["instruction"]!!.jsonPrimitive.content)
    }

    @Test fun `décider de ses brouillons`() = runBlocking {
        ok()
        api.draftSend("d1", "abc", key = "cle-3")
        val req = server.takeRequest()
        assertEquals("/api/moi/mail/draft/send", req.url.encodedPath)
        assertEquals("cle-3", req.headers["Idempotency-Key"])
        val sent = MikaJson.parseToJsonElement(req.body!!.utf8()).jsonObject
        assertEquals("abc", sent["seen"]!!.jsonPrimitive.content)
        ok()
        api.draftEdit("d1", Outgoing("lea@x.fr", "m@x.fr", subject = "Re: Devis", body = "Ma version"), quote = false)
        val edited = sentJson()
        assertEquals("Ma version", edited["body"]!!.jsonPrimitive.content)
        assertEquals("false", edited["quote"]!!.jsonPrimitive.content)
        assertNull(edited["bcc"])
        ok()
        api.draftRefuse("d1", "trop long")
        assertEquals("trop long", sentJson()["note"]!!.jsonPrimitive.content)
        ok()
        api.draftRedo("d1", "plus court")
        assertEquals("plus court", sentJson()["instruction"]!!.jsonPrimitive.content)
    }

    @Test fun `un refus se dit en mots, champ par champ`() = runBlocking {
        server.enqueue(
            MockResponse.Builder().code(400)
                .body("""{"error":"« to » : 300 caractères au plus.","fields":{"to":"300 caractères au plus"}}""").build(),
        )
        val err = (api.send("pro", Outgoing("x", subject = "s", body = "b")) as MoiApi.Result.Failed).error
        assertEquals("À : 300 caractères au plus", refusalText(err.message, err.fields))
        server.enqueue(MockResponse.Builder().code(409).body("""{"error":"Cette boîte ne peut pas envoyer."}""").build())
        val conflict = (api.draftSend("d1", "abc") as MoiApi.Result.Failed).error
        assertTrue(conflict.conflict)
        assertEquals("Cette boîte ne peut pas envoyer.", conflict.message)
    }

    @Test fun `une pièce jointe a son adresse sur le serveur de la session`() {
        val url = api.fileUrl("pro:<a@x>", "1")!!
        assertEquals("/api/moi/mail/file", url.encodedPath)
        assertEquals("pro:<a@x>", url.queryParameter("ref"))
        assertEquals("1", url.queryParameter("part"))
        assertEquals(server.url("/").host, url.host)
    }
}
