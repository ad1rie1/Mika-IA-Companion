package fr.qwartz.mika.data.moi.agenda

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
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
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

/**
 * L'Agenda sur l'API par personne (`protocole-moi.md` § 13) : les exemples du protocole lus tels quels (l'inconnu
 * ignoré, les défauts), ce que chaque lecture demande, le corps de chaque écriture — sous le jeton, sans CSRF ni
 * `Origin`, avec sa clé d'envoi —, le tableau d'un agenda sans ses mots, le partage (`kind: agenda`), un refus en mots.
 */
class AgendaApiTest {
    private val server = MockWebServer()
    private val client = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).build()
    private lateinit var api: AgendaApi

    @Before fun start() {
        server.start()
        val base = (ServerBase.parse(server.url("/").toString()) as ServerBase.Parsed.Ok).base
        api = AgendaApi(MoiApi(client, { Credentials(base, "mw_secret") }, {}, Dispatchers.IO))
    }

    @After fun stop() = server.close()

    private fun ok(body: String) = server.enqueue(MockResponse.Builder().body(body).build())

    private fun body(r: RecordedRequest): JsonObject = MikaJson.parseToJsonElement(r.body!!.utf8()).jsonObject

    @Test fun `ses agendas se lisent tels que le protocole les dit`() = runBlocking {
        ok(
            """{"plugged": true, "zone": "Europe/Paris", "colors": [{"code": "indigo", "label": "Indigo"}], "reminders": [],
               "calendars": [{"key": "moi:user_1~mon-agenda", "account": "moi:user_1", "name": "Mon agenda", "provider_name": "",
                 "kind": "systeme", "kind_label": "Système", "level": "proprietaire", "owner_name": "", "group": "mine",
                 "color": "", "provider_color": "", "primary": true, "hidden": false, "enabled": true, "reminder": "30",
                 "reminder_set": "", "writable": true, "read_only": false,
                 "can": {"write": true, "respond": true, "settings": true, "share": true, "rights": true, "remind": true, "rename": true},
                 "synced_at": 0, "provider_reminders": {"max": 0, "email": false, "defaults": []}, "error": "",
                 "shares": [{"person": "user_2", "name": "Léa Moreau", "level": "lire"}], "nouveau": 1},
                {"key": "mika", "account": "", "name": "L'agenda de Mika", "kind": "mika", "level": "lire", "group": "mika", "color": "rose"}]}""",
        )
        val got = (api.calendars() as MoiApi.Result.Ok).value
        assertEquals("Europe/Paris", got.zone)
        val mine = got.calendars[0]
        assertTrue(mine.owned)
        assertTrue(mine.can.rename)
        assertEquals("30", mine.reminder)
        assertEquals(listOf(AgendaShare("user_2", "Léa Moreau", "lire")), mine.shares)
        assertEquals(AgendaGroups.MIKA, got.calendars[1].group)
        assertEquals("/api/moi/agenda/calendars", server.takeRequest().url.encodedPath)
    }

    @Test fun `une periode demande ses jours et ses agendas, une occurrence se lit telle que le protocole la dit`() = runBlocking {
        ok(
            """{"start": "2026-11-23", "end": "2026-11-29", "zone": "Europe/Paris", "her": [], "proposals": [],
               "items": [{"event": 42, "occurrence": "20261125T130000Z", "uid": "u", "calendar": "moi:user_1~mon-agenda",
                 "title": "Point hebdo", "masked": false, "start": 1795957200000, "end": 1795959000000, "all_day": false,
                 "first_day": "", "last_day": "", "zone": "Europe/Paris", "location": "", "description": "", "conference": "",
                 "status": "confirme", "busy": true, "private": false, "recurring": true, "rule": "FREQ=WEEKLY",
                 "organizer": {"address": "claire@lumen.fr", "name": "Claire", "person": "", "response": "", "optional": false, "me": false},
                 "participants": [], "response": "oui", "invitation": false, "organized": false,
                 "added": {"by": "elle", "conversation": "chat:user_1:812", "at": 1795900000000}, "remind": "", "forgotten": false,
                 "reminders": [{"method": "notification", "minutes": 10}], "reminders_default": false,
                 "can": {"edit": false, "delete": true, "respond": true, "duplicate": true, "remind": true}}]}""",
        )
        val p = (api.period("2026-11-23", "2026-11-29", listOf("moi:user_1~mon-agenda", "mika")) as MoiApi.Result.Ok).value
        val i = p.items.single()
        assertEquals(42, i.event)
        assertEquals("FREQ=WEEKLY", i.rule)
        assertEquals("elle", i.added?.by)
        assertEquals(listOf(Alert(Alert.NOTIFICATION, 10)), i.reminders)
        assertFalse(i.can.edit)
        val url = server.takeRequest().url
        assertEquals("/api/moi/agenda/period", url.encodedPath)
        assertEquals("2026-11-23", url.queryParameter("start"))
        assertEquals("2026-11-29", url.queryParameter("end"))
        assertEquals("moi:user_1~mon-agenda,mika", url.queryParameter("calendars"))
    }

    @Test fun `une proposition se lit, son remind nul compris`() = runBlocking {
        ok(
            """{"items": [{"id": 7, "op": "ajouter", "calendar": "c", "summary": "Le dîner", "at": 1, "starts": 2, "decides": true,
               "conversation": "chat:user_1:9", "invitation": "", "target": null,
               "draft": {"title": "Dîner", "start": 10, "end": 20, "all_day": false, "zone": "Europe/Paris", "location": "",
                         "description": "", "rule": "", "invite": ["lea@x.fr"]},
               "change": null, "scope": "", "answer": "", "comment": "", "why": "", "remind": null,
               "preview": {"text": "agenda_create …", "digest": "abc", "blocked": ""}}]}""",
        )
        val p = (api.proposals() as MoiApi.Result.Ok).value.items.single()
        assertNull(p.remind)
        assertNull(p.target)
        assertEquals("abc", p.preview?.digest)
        assertEquals(listOf("lea@x.fr"), p.draft?.invite)
    }

    @Test fun `creer envoie l'agenda et les champs, sous le jeton, sans CSRF, avec sa cle d'envoi`() = runBlocking {
        ok("""{"ok": true, "message": "Ajouté.", "made": {"calendar": "c", "uid": "u", "event": 51}}""")
        val got = api.create(
            "c",
            EventFields(title = "Coiffeur", start = "2026-11-24T18:00", end = "2026-11-24T18:30", allDay = false, zone = "Europe/Paris", invite = listOf("a@x.fr"), reminders = listOf(Alert(Alert.EMAIL, 60))),
            "cle-1",
        )
        assertEquals(51, (got as MoiApi.Result.Ok).value.made?.event)
        val r = server.takeRequest()
        assertEquals("/api/moi/agenda/event/create", r.url.encodedPath)
        assertEquals("Bearer mw_secret", r.headers["Authorization"])
        assertEquals("cle-1", r.headers["Idempotency-Key"])
        assertNull(r.headers["X-CSRFToken"])
        assertNull(r.headers["Origin"])
        val b = body(r)
        assertEquals("c", b["calendar"]!!.jsonPrimitive.content)
        assertEquals("Coiffeur", b["title"]!!.jsonPrimitive.content)
        assertFalse(b["all_day"]!!.jsonPrimitive.boolean)
        assertEquals("a@x.fr", b["invite"]!!.jsonArray.single().jsonPrimitive.content)
        assertEquals(60, b["reminders"]!!.jsonArray.single().jsonObject["minutes"]!!.jsonPrimitive.int)
        // un champ absent ne part pas : pas de « remind », pas de « location »
        assertFalse("remind" in b)
        assertFalse("location" in b)
    }

    @Test fun `modifier envoie l'occurrence, la portee et ce qui change seulement`() = runBlocking {
        ok("""{"ok": true, "message": "Modifié."}""")
        api.edit(42, "20261125T130000Z", "suivants", EventFields(title = "Point"))
        val b = body(server.takeRequest())
        assertEquals(setOf("event", "occurrence", "scope", "title"), b.keys)
        assertEquals(42, b["event"]!!.jsonPrimitive.int)
        assertEquals("suivants", b["scope"]!!.jsonPrimitive.content)
    }

    @Test fun `repondre, accepter tel qu'il a ete lu, refuser, Mika te le rappelle`() = runBlocking {
        repeat(4) { ok("""{"ok": true, "message": "Fait."}""") }
        api.respond(42, "", "non", "Désolé", "tous")
        api.accept(7, "abc")
        api.refuse(7)
        api.remind(42, "veille")
        val respond = server.takeRequest()
        assertEquals("/api/moi/agenda/event/respond", respond.url.encodedPath)
        assertEquals("non", body(respond)["answer"]!!.jsonPrimitive.content)
        assertEquals("Désolé", body(respond)["comment"]!!.jsonPrimitive.content)
        val accept = server.takeRequest()
        assertEquals("/api/moi/agenda/proposal/accept", accept.url.encodedPath)
        assertEquals("abc", body(accept)["seen"]!!.jsonPrimitive.content)
        assertEquals("/api/moi/agenda/proposal/refuse", server.takeRequest().url.encodedPath)
        val remind = server.takeRequest()
        assertEquals("veille", body(remind)["value"]!!.jsonPrimitive.content)
    }

    @Test fun `le tableau d'un agenda part entier, sans ses mots`() = runBlocking {
        ok("""{"ok": true, "message": "Réglé."}""")
        val line = AgendaRule(who = listOf("personne:user_1"), moment = listOf("conversation"), read = true, write = "accord", words = RuleWords(who = "Toi"))
        api.saveRights("c", listOf(line), AgendaRule())
        val b = body(server.takeRequest())
        val l = b["lines"]!!.jsonArray.single().jsonObject
        assertFalse("words" in l)
        assertEquals("conversation", l["when"]!!.jsonArray.single().jsonPrimitive.content)
        assertEquals("accord", l["write"]!!.jsonPrimitive.content)
        assertNotNull(b["default"])
    }

    @Test fun `partager un agenda passe par shares set, kind agenda`() = runBlocking {
        ok("""{"ok": true, "message": "Partagé."}""")
        api.share("moi:user_1~mon-agenda", "user_2", "preparer")
        val r = server.takeRequest()
        assertEquals("/api/moi/shares/set", r.url.encodedPath)
        val b = body(r)
        assertEquals("agenda", b["kind"]!!.jsonPrimitive.content)
        assertEquals("moi:user_1~mon-agenda", b["key"]!!.jsonPrimitive.content)
        assertEquals("preparer", b["level"]!!.jsonPrimitive.content)
    }

    @Test fun `brancher un compte - sa sorte et ses valeurs, regler un des siens - sa cle`() = runBlocking {
        ok("""{"ok": true, "message": "Branché.", "account": "dav-1"}""")
        ok("""{"ok": true, "message": "Réglé."}""")
        val got = api.saveAccount("caldav", "", mapOf("label" to "Travail", "url" to "https://dav.x.fr", "enabled" to true))
        assertEquals("dav-1", (got as MoiApi.Result.Ok).value.account)
        val b = body(server.takeRequest())
        assertEquals("caldav", b["kind"]!!.jsonPrimitive.content)
        assertTrue(b["values"]!!.jsonObject["enabled"]!!.jsonPrimitive.boolean)
        api.saveAccount("caldav", "dav-1", mapOf("label" to "Pro"))
        val c = body(server.takeRequest())
        assertEquals("dav-1", c["account"]!!.jsonPrimitive.content)
        assertFalse("kind" in c)
    }

    @Test fun `un refus se dit avec les mots du serveur, champ par champ`() = runBlocking {
        server.enqueue(MockResponse.Builder().code(400).body("""{"error": "« title » : 300 caractères au plus.", "fields": {"title": "300 caractères au plus"}}""").build())
        val got = api.create("c", EventFields(title = "x".repeat(301)))
        val e = (got as MoiApi.Result.Failed).error
        assertEquals(400, e.code)
        assertEquals("300 caractères au plus", e.fields["title"])
    }
}
