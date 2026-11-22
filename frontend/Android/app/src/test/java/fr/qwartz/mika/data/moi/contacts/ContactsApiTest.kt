package fr.qwartz.mika.data.moi.contacts

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.int
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
 * Contacts sur l'API par personne (`protocole-moi.md` § 12) : l'exemple du protocole lu tel quel (l'inconnu ignoré —
 * la photo de l'ADR 0300 —, les défauts), une fiche entière, ce que la liste demande, les corps des oublis sous le
 * jeton avec leur clé d'envoi, un refus avec les mots du serveur.
 */
class ContactsApiTest {
    private val server = MockWebServer()
    private val client = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).build()
    private lateinit var api: ContactsApi

    @Before fun start() {
        server.start()
        val base = (ServerBase.parse(server.url("/").toString()) as ServerBase.Parsed.Ok).base
        api = ContactsApi(MoiApi(client, { Credentials(base, "mw_secret") }, {}, Dispatchers.IO))
    }

    @After fun stop() = server.close()

    private fun ok(body: String) = server.enqueue(MockResponse.Builder().body(body).build())

    @Test fun `l'exemple du protocole se lit, la photo ignorée`() = runBlocking {
        ok(
            """{"total": 7, "page": 1, "size": 50, "counts": {"all": 7, "person": 6, "org": 1},
             "items": [{"id": 12, "kind": "person", "name": "Alice Durand", "title": "Cheffe de projet", "department": "",
                        "organisation": {"id": 3, "name": "Nordis"}, "linked": false, "talks": false, "members": 0,
                        "last": 1790790000000,
                        "sources": [{"source": "teams", "label": "Teams", "count": 64},
                                    {"source": "mail", "account": "perso", "label": "Personnel", "count": 23},
                                    {"source": "whatsapp", "label": "WhatsApp", "count": 4},
                                    {"source": "told", "label": "Raconté", "count": 2}],
                        "identifiers": [{"kind": "email", "value": "alice@nordis.fr"}],
                        "photo": "/api/moi/teams/photo?account=equipe&person=8%3Aorgid%3Ax&v=1"}]}""",
        )
        val page = (api.page() as MoiApi.Result.Ok).value
        assertEquals(ContactsCounts(all = 7, person = 6, org = 1), page.counts)
        val c = page.items.single()
        assertEquals("Alice Durand", c.name)
        assertEquals(ContactRef(3, "Nordis"), c.organisation)
        assertFalse(c.org)
        assertEquals(listOf("teams", "mail", "whatsapp", "told"), c.sources.map { it.source })
        assertEquals("perso", c.sources[1].account)
        assertEquals(ContactIdent("email", "alice@nordis.fr"), c.identifiers.single())
        assertEquals(1790790000000, c.last)
    }

    @Test fun `la liste demande sa recherche, sa sorte et sa page, une sorte vide ne part pas`() = runBlocking {
        ok("""{"items": []}""")
        api.page(q = "  claire  ", kind = "org", page = 2, size = 50)
        val url = server.takeRequest().url
        assertEquals("/api/moi/contacts", url.encodedPath)
        assertEquals("claire", url.queryParameter("q"))
        assertEquals("org", url.queryParameter("kind"))
        assertEquals("2", url.queryParameter("page"))
        assertEquals("50", url.queryParameter("size"))

        ok("""{"items": []}""")
        api.page()
        val bare = server.takeRequest().url
        assertNull(bare.queryParameter("q"))
        assertNull(bare.queryParameter("kind"))
    }

    @Test fun `une fiche se lit en entier, ses lieux de trois sortes`() = runBlocking {
        ok(
            """{"id": 12, "kind": "person", "name": "Claire Dubois", "title": "Cheffe de projet", "department": "Conseil",
               "organisation": {"id": 3, "name": "Lumen Conseil"}, "linked": true, "talks": false,
               "sources": [{"source": "teams", "label": "Teams", "count": 64}], "first": 1, "last": 2,
               "identifiers": [{"kind": "email", "label": "E-mail", "value": "c.dubois@lumen.fr", "name": "",
                                "where": ["Pro", "son profil Teams"], "generic": false},
                               {"kind": "phone_app", "label": "Contact WhatsApp", "value": "", "name": "Claire D.",
                                "where": ["ton téléphone"], "generic": false}],
               "facts": [{"kind": "title", "label": "Poste", "value": "Cheffe de projet", "from": "son profil Teams"},
                         {"kind": "organisation", "label": "Organisation", "value": "Lumen Conseil", "id": 3, "from": "son adresse e-mail"},
                         {"kind": "note", "id": 41, "sort": "expectation", "label": "", "value": "Elle attend ta version.",
                          "confidence": 0.85, "from": "ses mails à Pro", "place": "un mail, objet « Re: Présentation »",
                          "at": 5, "forget": true}],
               "places": [{"source": "teams", "conversation": "pro~19:abc", "account": "pro", "title": "Claire Dubois",
                           "kind": "dm", "count": 41, "last": 9},
                          {"source": "mail", "box": "pro", "box_name": "Pro", "count": 23, "last": 8,
                           "ref": "pro:<m1@x>", "subject": "Re: Présentation"},
                          {"source": "phone", "conversation": "whatsapp|t1", "app": "whatsapp", "app_name": "WhatsApp",
                           "title": "", "group": false, "count": 4, "last": 7}],
               "members": [], "members_total": 0, "write": {"address": "c.dubois@lumen.fr", "name": "Claire Dubois"},
               "teams": "pro~19:abc", "message": "whatsapp|t1", "privacy": "mine",
               "forget": {"allowed": true, "reason": ""}, "photo": null}""",
        )
        val s = (api.sheet(12) as MoiApi.Result.Ok).value
        assertEquals("12", server.takeRequest().url.queryParameter("id"))
        assertEquals(listOf("Pro", "son profil Teams"), s.identifiers.first().where)
        assertEquals("Claire D.", s.identifiers[1].name)
        assertEquals(3, s.facts[1].id)
        assertEquals(0.85, s.facts[2].confidence!!, 1e-9)
        assertTrue(s.facts[2].note && s.facts[2].forget)
        assertNull(s.facts[0].confidence)
        assertEquals(listOf("teams", "mail", "phone"), s.places.map { it.source })
        assertEquals("Pro", s.places[1].boxName)
        assertEquals("WhatsApp", s.places[2].appName)
        assertEquals(ContactWrite("c.dubois@lumen.fr", "Claire Dubois"), s.write)
        assertEquals(ContactSheet.PRIVACY_MINE, s.privacy)
        assertTrue(s.forget.allowed)
    }

    @Test fun `oublier un contact, puis un fait, leur numéro dans le corps, sous le jeton, avec leur clé d'envoi`() = runBlocking {
        ok("""{"ok": true, "message": "« Claire » est oublié·e : ce n'est plus un de tes contacts."}""")
        val done = (api.forget(12, key = "cle-1") as MoiApi.Result.Ok).value
        assertTrue(done.message.startsWith("« Claire »"))
        val req = server.takeRequest()
        assertEquals("/api/moi/contacts/forget", req.url.encodedPath)
        assertEquals("POST", req.method)
        assertEquals("cle-1", req.headers["Idempotency-Key"])
        assertEquals("Bearer mw_secret", req.headers["Authorization"])
        assertEquals(12, MikaJson.parseToJsonElement(req.body!!.utf8()).jsonObject["id"]!!.jsonPrimitive.int)

        ok("""{"ok": true, "message": "Oublié.", "deduped": false, "id": 41}""")
        assertEquals(41, (api.forgetFact(41, key = "cle-2") as MoiApi.Result.Ok).value.id)
        val fact = server.takeRequest()
        assertEquals("/api/moi/contacts/fact/forget", fact.url.encodedPath)
        assertEquals(41, MikaJson.parseToJsonElement(fact.body!!.utf8()).jsonObject["id"]!!.jsonPrimitive.int)
    }

    @Test fun `un oubli refusé se dit avec les mots du serveur`() = runBlocking {
        server.enqueue(
            MockResponse.Builder().code(403)
                .body("""{"error": "Une part de ce qu'elle en sait vient d'un compte qu'on te partage ou d'un de ses comptes à elle : une opératrice peut l'oublier depuis la console."}""")
                .build(),
        )
        val got = api.forget(7) as MoiApi.Result.Failed
        assertEquals(403, got.error.code)
        assertTrue(got.error.message.startsWith("Une part de ce qu'elle en sait"))
    }
}
