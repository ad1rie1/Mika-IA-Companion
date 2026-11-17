package fr.qwartz.mika.data.moi.tools

import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
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
 * Outils sur l'API par personne (`protocole-moi.md` § 6, 8) : la matrice lue (une case `null` ou absente, l'inconnu
 * ignoré, les défauts, la règle d'un compte, ce qu'une opératrice reçoit de plus), ses services, les refus — sous le
 * jeton de ce téléphone, sans rien écrire.
 */
class ToolsApiTest {
    private val server = MockWebServer()
    private val client = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).build()
    private lateinit var api: ToolsApi

    @Before fun start() {
        server.start()
        val base = (ServerBase.parse(server.url("/").toString()) as ServerBase.Parsed.Ok).base
        api = ToolsApi(MoiApi(client, { Credentials(base, "mw_secret") }, {}, Dispatchers.IO))
    }

    @After fun stop() = server.close()

    private fun ok(body: String) = server.enqueue(MockResponse.Builder().body(body).build())

    @Test fun `la matrice se lit, une case nulle ou absente ne sert pas, l'inconnu est ignoré`() = runBlocking {
        ok(
            """{"canals":[{"key":"web","label":"Chat web"},{"key":"mobile","label":"App Android"},{"key":"seule","label":"Elle seule"}],
               "moments":[{"key":"reply","label":"quand elle te répond"},{"key":"initiative","label":"quand elle te parle d'elle-même"},
                          {"key":"work","label":"quand elle travaille seule"}],
               "groups":[
                 {"key":"families","title":"Ses propres outils","resources":[
                   {"key":"famille:goals","title":"Buts","description":"tes rappels","href":"","futur":true,"tools":[
                     {"name":"goal_remind","label":"Te promettre un rappel","description":"Promettre un rappel…","acts":true,
                      "cells":{"mobile/reply":{"level":"seule","keep":"perso","why":"toi, toujours","line":"","reason":"","owned":false},
                               "mobile/initiative":null,
                               "web/reply":{"level":"non","keep":"rien","why":"En tête-à-tête.","reason":"when"}}}]}]},
                 {"key":"accounts","title":"Tes comptes","resources":[
                   {"key":"courrier:pro","kind":"mail","title":"Atelier","address":"a@b.fr","family":"famille:email",
                    "rules":{"canal":"courrier:pro","set":false,"common":true,
                             "lines":[{"who":"tout le monde","when":"toujours","prepare":false,"reply":"accord","reply_words":"ton accord"}],
                             "default":{"who":"","when":"toujours","prepare":false,"reply":"non","reply_words":"non"}}}]},
                 {"key":"services","title":"Services","resources":[
                   {"key":"mcp:meteo","title":"Service « meteo »","description":"La météo d'une ville.","href":"",
                    "tools":[{"name":"mcp_meteo_now","label":"","description":"Current weather. For a city.","acts":false,"cells":{}}]}]},
                 {"key":"apps","title":"Apps de la Forge","resources":[]}]}""",
        )
        val r = (api.rights() as MoiApi.Result.Ok).value
        assertEquals(listOf("web", "mobile", "seule"), r.canals.map { it.key })
        assertEquals("quand elle travaille seule", r.moments.last().label)
        val remind = r.groups[0].resources.single().tools.single()
        assertTrue(remind.acts)
        assertEquals(RightsCell(level = "seule", keep = "perso", why = "toi, toujours"), remind.cells["mobile/reply"])
        assertNull(remind.cells["mobile/initiative"])
        assertNull(remind.cells["teams/reply"])
        // une case maigre : ses défauts (pas de ligne, pas à ton nom)
        assertEquals(RightsCell(level = "non", keep = "rien", why = "En tête-à-tête.", reason = "when"), remind.cells["web/reply"])
        val pro = r.groups[1].resources.single()
        assertEquals("mail", pro.kind)
        assertEquals("famille:email", pro.family)
        assertTrue(pro.rules!!.common)
        assertEquals("ton accord", pro.rules!!.lines.single().replyWords)
        assertEquals("non", pro.rules!!.default.reply)
        assertEquals(emptyList<RightsTool>(), pro.tools)
        val meteo = r.groups[2].resources.single().tools.single()
        assertEquals("", meteo.label)
        assertEquals("Current weather", labelOf(meteo))
        assertTrue(meteo.cells.isEmpty())
        assertTrue(r.groups[3].resources.isEmpty())
        val req = server.takeRequest()
        assertEquals("GET", req.method)
        assertEquals("/api/moi/rights", req.url.encodedPath)
        assertEquals("Bearer mw_secret", req.headers["Authorization"])
        assertNull(req.headers["Origin"])
    }

    @Test fun `une opératrice reçoit la ligne même et la page de la console, une forme vide a ses défauts`() = runBlocking {
        ok(
            """{"canals":[],"moments":[],"groups":[{"key":"families","title":"Ses propres outils","resources":[
               {"key":"famille:email","title":"Courrier","href":"/inspecteur/reglages/droits?detail=famille%3Aemail","tools":[
                 {"name":"email_read","label":"Ouvrir un de tes mails","cells":{"web/reply":{"level":"toi","keep":"prive",
                  "why":"toi, quand elle répond","line":"ligne 2 — serré par le canal","reason":"","owned":true}}}]}]}]}""",
        )
        val res = (api.rights() as MoiApi.Result.Ok).value.groups.single().resources.single()
        assertEquals("/inspecteur/reglages/droits?detail=famille%3Aemail", res.href)
        val c = res.tools.single().cells["web/reply"]!!
        assertEquals("ligne 2 — serré par le canal", c.line)
        assertTrue(c.owned)
        assertFalse(res.tools.single().acts)
        server.takeRequest()
        ok("{}")
        val empty = (api.rights() as MoiApi.Result.Ok).value
        assertEquals(Rights(), empty)
    }

    @Test fun `ses services, les tiens et ceux qu'on te partage`() = runBlocking {
        ok(
            """{"plugged":true,"items":[{"name":"meteo","purpose":"La météo.","url":"https://m.test/mcp","state":"connecte",
               "tools":[{"remote":"now","name":"mcp_meteo_now","choice":"lecture"}],"access":[{"who":"Léa","mine":true}]}],
               "received":[{"name":"agenda","purpose":"L'agenda de Léa.","state":"jamais","level":"servir","owner_name":"Léa",
               "tools":[{"remote":"day","choice":"lecture"}],"line":{"read_words":"seule","keep_words":"une confidence"}}]}""",
        )
        val s = (api.services() as MoiApi.Result.Ok).value
        assertEquals("connecte", s.items.single().state)
        assertTrue(s.items.single().access.single().mine)
        val agenda = s.received.single()
        assertEquals("Léa", agenda.ownerName)
        assertEquals("une confidence", agenda.line.keepWords)
        assertEquals("partagé avec toi par Léa (s'en servir)", receivedWords(agenda))
        assertEquals("/api/moi/mcp/services", server.takeRequest().url.encodedPath)
    }

    @Test fun `les refus se disent, et une réponse illisible n'est pas une exception`() = runBlocking {
        server.enqueue(MockResponse.Builder().code(503).body("""{"error":"Les services ne sont pas branchés."}""").build())
        val err = (api.services() as MoiApi.Result.Failed).error
        assertEquals(503, err.code)
        assertEquals("Les services ne sont pas branchés.", err.message)
        server.takeRequest()
        ok("""{"canals":"pas une liste"}""")
        val bad = api.rights()
        assertTrue(bad is MoiApi.Result.Failed)
        assertNotNull((bad as MoiApi.Result.Failed).error.message)
    }
}
