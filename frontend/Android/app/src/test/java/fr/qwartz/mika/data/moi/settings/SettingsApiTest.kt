package fr.qwartz.mika.data.moi.settings

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
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
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

/**
 * Paramètres sur l'API par personne (`protocole-moi.md` § 5, 7, 8, 9) : les formes lues (l'inconnu ignoré, les défauts,
 * jamais un secret), les corps des écritures (seulement ce qui a changé, la clé d'envoi d'une création), les refus par
 * champ.
 */
class SettingsApiTest {
    private val server = MockWebServer()
    private val client = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).build()
    private lateinit var api: SettingsApi

    @Before fun start() {
        server.start()
        val base = (ServerBase.parse(server.url("/").toString()) as ServerBase.Parsed.Ok).base
        api = SettingsApi(MoiApi(client, { Credentials(base, "mw_secret") }, {}, Dispatchers.IO))
    }

    @After fun stop() = server.close()

    private fun ok(body: String) = server.enqueue(MockResponse.Builder().body(body).build())
    private fun body(req: RecordedRequest): JsonObject = MikaJson.parseToJsonElement(req.body!!.utf8()).jsonObject

    @Test fun `les réglages d'une boîte, ses valeurs, ses secrets gardés, sa connexion Microsoft, sa règle`() = runBlocking {
        ok(
            """{"box":"pro","values":{"label":"Pro","address":"a@b.fr","enabled":true,"auth":"microsoft","imap_host":"outlook.office365.com",
               "imap_port":993,"imap_ssl":true,"user":"a@b.fr","folders":["INBOX","Sent"],"sync_all":false,"since_days":7,
               "oauth_client_id":"abc","oauth_tenant":"consumers","smtp_host":"","smtp_port":587,"smtp_security":"starttls",
               "smtp_user":"","save_sent":true,"voice":"assistante","display_name":"Adrien","sender_name":"","tone":"","instructions":"",
               "signature":"","futur":1},"secrets":{"password":false,"smtp_password":true},"ready":false,"can_send":false,"microsoft":true,
               "signin":{"state":"en_attente","code":"ABCD-1234","url":"https://microsoft.com/devicelogin","until":1790800000000,"error":""},
               "rules":{"canal":"courrier:pro","set":false,"common":true,"version":"0123456789abcdef",
               "lines":[{"who":"Claire","when":"toujours","prepare":true,"reply":"accord","reply_words":"ton accord"}],
               "default":{"who":"","when":"toujours","prepare":false,"reply":"non","reply_words":"non"}}}""",
        )
        val s = (api.box("pro") as MoiApi.Result.Ok).value
        assertEquals(Auths.MICROSOFT, s.values.auth)
        assertEquals(listOf("INBOX", "Sent"), s.values.folders)
        assertEquals(Voices.ASSISTANT, s.values.voice)
        assertTrue(s.secrets.smtpPassword)
        assertFalse(s.secrets.password)
        assertTrue(s.signin!!.waiting)
        assertEquals("ABCD-1234", s.signin!!.code)
        assertEquals("0123456789abcdef", s.rules.version)
        assertEquals("toujours", s.rules.lines.single().whenWords)
        assertEquals(Replies.NO, s.rules.default.reply)
        val url = server.takeRequest().url
        assertEquals("/api/moi/mail/box", url.encodedPath)
        assertEquals("pro", url.queryParameter("box"))
        // une forme maigre : les défauts, pas de connexion Microsoft
        ok("""{"box":"x"}""")
        val thin = (api.box("x") as MoiApi.Result.Ok).value
        assertNull(thin.signin)
        assertEquals(BoxValues(), thin.values)
    }

    @Test fun `une boîte nouvelle porte sa clé d'envoi, une boîte réglée son nom`() = runBlocking {
        ok("""{"ok":true,"message":"Boîte enregistrée.","box":"moi-a1b2c3","ready":true}""")
        val values = newBoxValues(Provider.GMAIL, NewBox(address = "moi@gmail.com", password = "app", imapHost = "imap.gmail.com", imapPort = "993", smtpHost = "smtp.gmail.com", smtpPort = "587"))
        val done = (api.saveBox(values, "", key = "creation-1") as MoiApi.Result.Ok).value
        assertEquals("moi-a1b2c3", done.box)
        val req = server.takeRequest()
        assertEquals("/api/moi/mail/box/save", req.url.encodedPath)
        assertEquals("creation-1", req.headers["Idempotency-Key"])
        val sent = body(req)
        assertNull(sent["box"])
        assertEquals("app", sent["values"]!!.jsonObject["password"]!!.jsonPrimitive.content)
        ok("""{"ok":true,"message":"Boîte enregistrée.","box":"pro"}""")
        api.saveBox(boxChanges(BoxValues(label = "Pro"), BoxValues(label = "Travail")), "pro")
        val again = body(server.takeRequest())
        assertEquals("pro", again["box"]!!.jsonPrimitive.content)
        assertEquals(JsonObject(mapOf("label" to JsonPrimitive("Travail"))), again["values"])
    }

    @Test fun `un refus de boîte, par champ`() = runBlocking {
        server.enqueue(
            MockResponse.Builder().code(400)
                .body("""{"error":"La connexion a changé : redonne le mot de passe.","fields":{"password":"à redonner pour cette connexion"}}""")
                .build(),
        )
        val err = (api.saveBox(JsonObject(mapOf("imap_host" to JsonPrimitive("imap.autre.fr"))), "pro") as MoiApi.Result.Failed).error
        assertEquals(mapOf("password" to "à redonner pour cette connexion"), fieldErrors(err.fields))
        assertEquals("La connexion a changé : redonne le mot de passe.", err.message)
    }

    @Test fun `tester, connecter à Microsoft, relever, retirer`() = runBlocking {
        repeat(4) { ok("""{"ok":true,"message":"fait"}""") }
        assertTrue((api.testBox("pro") as MoiApi.Result.Ok).value.ok)
        api.connectMicrosoft("pro")
        api.pollBox("pro")
        api.removeBox("pro")
        val paths = (1..4).map { server.takeRequest() }
        assertEquals(listOf("/api/moi/mail/box/test", "/api/moi/mail/box/microsoft", "/api/moi/mail/poll", "/api/moi/mail/box/remove"), paths.map { it.url.encodedPath })
        assertTrue(paths.all { body(it)["box"]!!.jsonPrimitive.content == "pro" })
    }

    @Test fun `la règle d'un compte part entière, avec sa version, changée ailleurs, 409`() = runBlocking {
        val rules = SendRules(canal = "teams:atelier", version = "v1", lines = listOf(RuleLine(reply = Replies.ASK)), default = RuleLine(reply = Replies.NO))
        ok("""{"ok":true,"message":"Règle d'envoi enregistrée."}""")
        api.saveRules(ruleBody(rules, listOf(RuleEdit(true, Replies.DRAFT)), RuleEdit(false, Replies.NO))!!)
        val req = server.takeRequest()
        assertEquals("/api/moi/rules", req.url.encodedPath)
        val sent = body(req)
        assertEquals("v1", sent["version"]!!.jsonPrimitive.content)
        assertEquals("brouillon", sent["lines"]!!.jsonArray.single().jsonObject["reply"]!!.jsonPrimitive.content)
        server.enqueue(MockResponse.Builder().code(409).body("""{"error":"Cette règle vient d'être réglée ailleurs : rouvre-la, puis recommence."}""").build())
        assertTrue((api.saveRules(ruleBody(rules, listOf(RuleEdit(true, Replies.ASK)), RuleEdit(false, Replies.NO))!!) as MoiApi.Result.Failed).error.conflict)
    }

    @Test fun `un compte Teams, sa clé montrée une fois`() = runBlocking {
        ok(
            """{"account":"atelier","values":{"label":"Atelier","enabled":true,"display_name":"","tone":"","instructions":"","sign":true,"signature":"— {elle}"},
               "extension_key":{"hint":"mtk_ab","created_at":1790700000000},"rules":{"canal":"teams:atelier","version":"v","lines":[],"default":{"reply":"accord"}}}""",
        )
        val t = (api.teamsAccount("atelier") as MoiApi.Result.Ok).value
        assertTrue(t.values.sign)
        assertEquals("mtk_ab", t.extensionKey!!.hint)
        assertEquals(1_790_700_000_000L, t.extensionKey!!.createdAt)
        assertEquals("atelier", server.takeRequest().url.queryParameter("account"))
        ok("""{"ok":true,"message":"Clé neuve : colle-la dans l'extension de ce compte (elle ne sera plus montrée).","key":"mtk_secret_neuf"}""")
        assertEquals("mtk_secret_neuf", (api.newExtensionKey("atelier") as MoiApi.Result.Ok).value.key)
        assertEquals("/api/moi/teams/account/key", server.takeRequest().url.encodedPath)
        ok("""{"ok":true,"message":"Compte Teams enregistré.","account":"teams-pro-1a2b3c"}""")
        val made = api.saveTeamsAccount(JsonObject(mapOf("label" to JsonPrimitive("Teams pro"))), "", key = "creation-2")
        assertEquals("teams-pro-1a2b3c", (made as MoiApi.Result.Ok).value.account)
        val req = server.takeRequest()
        assertEquals("creation-2", req.headers["Idempotency-Key"])
        assertNull(body(req)["account"])
        repeat(2) { ok("""{"ok":true,"message":"fait"}""") }
        api.revokeExtensionKey("atelier")
        api.removeTeamsAccount("atelier")
        assertEquals("/api/moi/teams/account/revoke", server.takeRequest().url.encodedPath)
        assertEquals("/api/moi/teams/account/remove", server.takeRequest().url.encodedPath)
    }

    @Test fun `son nom, son mot de passe et la reconnexion`() = runBlocking {
        ok("""{"ok":true,"message":"C'est ton nom, maintenant : elle t'appellera ainsi."}""")
        api.saveName("Adrien Moreau")
        assertEquals("Adrien Moreau", body(server.takeRequest())["name"]!!.jsonPrimitive.content)
        ok("""{"ok":true,"message":"Mot de passe changé : reconnecte-toi.","relogin":true}""")
        assertTrue((api.savePassword("vieux", "neuf-et-long") as MoiApi.Result.Ok).value.relogin)
        val sent = body(server.takeRequest())
        assertEquals("vieux", sent["current"]!!.jsonPrimitive.content)
        assertEquals("neuf-et-long", sent["password"]!!.jsonPrimitive.content)
        server.enqueue(MockResponse.Builder().code(400).body("""{"error":"Ce n'est pas ton mot de passe actuel.","fields":{"current":"mot de passe incorrect"}}""").build())
        assertEquals("mot de passe incorrect", (api.savePassword("faux", "x") as MoiApi.Result.Failed).error.fields["current"])
        server.enqueue(MockResponse.Builder().code(429).body("""{"error":"Trop d'essais : attends une minute avant de réessayer."}""").build())
        assertEquals(429, (api.savePassword("faux", "x") as MoiApi.Result.Failed).error.code)
    }

    @Test fun `ses services, ceux qu'on lui partage, sans adresse ni en-têtes`() = runBlocking {
        ok(
            """{"plugged":true,"items":[{"name":"meteo","purpose":"la météo","when_to_use":"","enabled":true,"url":"https://m.example/mcp",
               "headers":true,"state":"connecte","detail":"","tools":[{"remote":"previsions","name":"mcp_meteo_previsions","description":"prévisions",
               "choice":"lecture","new":false,"changed":false},{"remote":"alerte","name":"","description":"","choice":"","new":true,"changed":false}],
               "access":[{"who":"Adrien","when":"toujours","mine":true,"read":"seule","act":"carte","keep":"prive","read_words":"seule",
               "act_words":"elle te demande","keep_words":"une confidence","tools":[]}],"default":{"who":"","read":"non","act":"non"}}],
               "received":[{"name":"agenda","purpose":"l'agenda","enabled":true,"state":"jamais","tools":[{"remote":"lire","choice":"lecture"}],
               "level":"lire","line":{"read_words":"seule"},"owner_name":"Léa"}]}""",
        )
        val got = (api.services() as MoiApi.Result.Ok).value
        val meteo = got.items.single()
        assertTrue(meteo.headers)
        assertTrue(meteo.access.single().mine)
        assertTrue(meteo.tools[1].waiting)
        assertEquals("non", meteo.default!!.act)
        val agenda = got.received.single()
        assertEquals("Léa", agenda.ownerName)
        assertEquals("seule", agenda.line.readWords)
        assertEquals("/api/moi/mcp/services", server.takeRequest().url.encodedPath)
    }

    @Test fun `brancher un service avec sa clé, choisir ses outils, le régler, le tester`() = runBlocking {
        ok("""{"ok":true,"message":"« meteo » branché : teste-le, puis choisis ses outils.","name":"meteo"}""")
        val done = (api.plugService("meteo", "la météo", "https://m.example/mcp", "", "", key = "creation-3") as MoiApi.Result.Ok).value
        assertEquals("meteo", done.name)
        val plug = server.takeRequest()
        assertEquals("creation-3", plug.headers["Idempotency-Key"])
        assertEquals(setOf("name", "purpose", "url", "headers", "when_to_use"), body(plug).keys)
        ok("""{"ok":true,"message":"Ses outils sont choisis.","decided":{"alerte":"action"}}""")
        api.chooseTools("meteo", mapOf("alerte" to ToolChoices.ACT))
        val tools = body(server.takeRequest())
        assertEquals("action", tools["choices"]!!.jsonObject["alerte"]!!.jsonPrimitive.content)
        ok("""{"ok":true,"message":"Service réglé."}""")
        api.saveService("meteo", JsonObject(mapOf("enabled" to JsonPrimitive(false))))
        val saved = body(server.takeRequest())
        assertFalse(saved["values"]!!.jsonObject["enabled"]!!.jsonPrimitive.boolean)
        ok("""{"ok":false,"message":"Le service ne répond pas (délai dépassé)."}""")
        val tested = (api.testService("meteo") as MoiApi.Result.Ok).value
        assertFalse(tested.ok)
        assertEquals("Le service ne répond pas (délai dépassé).", tested.message)
        assertEquals("/api/moi/mcp/test", server.takeRequest().url.encodedPath)
        ok("""{"ok":true,"message":"Service retiré."}""")
        api.removeService("meteo")
        assertEquals("/api/moi/mcp/remove", server.takeRequest().url.encodedPath)
    }

    @Test fun `les partages, les personnes, partager et retirer`() = runBlocking {
        ok(
            """{"given":[{"kind":"mail","key":"pro","title":"Pro","person":"p2","name":"Julien","level":"lire"}],
               "received":[{"kind":"mcp","key":"agenda","title":"agenda","level":"servir","owner_name":"Léa"}]}""",
        )
        val shares = (api.shares() as MoiApi.Result.Ok).value
        assertEquals("p2", shares.given.single().person)
        assertEquals("Léa", shares.received.single().ownerName)
        server.takeRequest()
        ok("""{"items":[{"person":"p1","name":"Léa","owner":true},{"person":"p2","name":"Julien"}]}""")
        val people = (api.people() as MoiApi.Result.Ok).value.items
        assertTrue(people[0].owner)
        assertFalse(people[1].owner)
        assertEquals("/api/moi/people", server.takeRequest().url.encodedPath)
        ok("""{"ok":true,"message":"Partage retiré."}""")
        api.setShare(ShareKinds.MAIL, "pro", "p2", "")
        val sent = body(server.takeRequest())
        assertEquals("", sent["level"]!!.jsonPrimitive.content)
        assertEquals("p2", sent["person"]!!.jsonPrimitive.content)
        server.enqueue(MockResponse.Builder().code(403).body("""{"error":"Seul son propriétaire partage ce service."}""").build())
        assertEquals(403, (api.setShare(ShareKinds.MCP, "agenda", "p1", "lire") as MoiApi.Result.Failed).error.code)
    }

    @Test fun `ses téléphones, en révoquer un`() = runBlocking {
        ok("""{"items":[{"id":3,"label":"Android · samsung SM-S931B","created_at":1,"last_used":2,"revoked":false,"push":true}],"apk":false}""")
        assertEquals(3L, (api.phones() as MoiApi.Result.Ok).value.items.single().id)
        assertEquals("/api/moi/phone/phones", server.takeRequest().url.encodedPath)
        ok("""{"ok":true,"message":"Téléphone révoqué."}""")
        assertNotNull((api.revokePhone(3) as MoiApi.Result.Ok).value)
        val req = server.takeRequest()
        assertEquals("/api/moi/phone/revoke", req.url.encodedPath)
        assertEquals(3L, body(req)["id"]!!.jsonPrimitive.long)
    }

    @Test fun `une création redite garde sa clé`() = runBlocking {
        // le serveur rend la même réponse, « deduped » : rien de créé deux fois
        ok("""{"ok":true,"message":"Boîte enregistrée.","box":"pro-1","deduped":true}""")
        val done = (api.saveBox(JsonObject(mapOf("address" to JsonPrimitive("a@b.fr"))), "", key = "k") as MoiApi.Result.Ok).value
        assertTrue(done.deduped)
        assertEquals("k", server.takeRequest().headers["Idempotency-Key"])
        // les défauts d'une boîte sont ceux du moteur (`MailAccount`)
        assertEquals(993, BoxValues().imapPort)
        assertEquals(2, BoxValues().sinceDays)
        assertEquals(listOf("INBOX"), BoxValues().folders)
    }
}
