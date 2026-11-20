package fr.qwartz.mika.data.moi.mail

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
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
 * Le HTML d'un mail pour la WebView de la liseuse (ADR 0242) : la politique du cadre posée en tête du document, avant
 * tout ce que le mail contient ; les liens qui s'ouvrent dehors ; et sa lecture (`/mail/frame`, `/mail/images`).
 */
class MailFramePageTest {
    private val server = MockWebServer()
    private val client = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).build()
    private lateinit var api: MailApi

    @Before fun start() {
        server.start()
        val base = (ServerBase.parse(server.url("/").toString()) as ServerBase.Parsed.Ok).base
        api = MailApi(MoiApi(client, { Credentials(base, "mw_secret") }, {}, Dispatchers.IO))
    }

    @After fun stop() = server.close()

    private val served = "<!doctype html><meta charset=\"utf-8\"><style>html{background:#fff}</style><p>Bonjour</p>"

    @Test fun `la politique se pose juste après l'en-tête du serveur, avant ses styles et le mail`() {
        val page = MailFramePage.of(served, remote = false)
        val csp = page.indexOf("Content-Security-Policy")
        assertTrue(page.startsWith("<!doctype html><meta charset=\"utf-8\"><meta http-equiv=\"Content-Security-Policy\""))
        assertTrue(csp < page.indexOf("<style>"))
        assertTrue(page.contains("content=\"${MailFramePage.CSP}\""))
        assertTrue(page.contains("<meta name=\"referrer\" content=\"no-referrer\">"))
        assertTrue(page.endsWith("<p>Bonjour</p>"))
        // un seul en-tête : le document du serveur n'est pas répété
        assertEquals(1, Regex("<!doctype", RegexOption.IGNORE_CASE).findAll(page).count())
    }

    @Test fun `ses images distantes permises, la politique n'ouvre que les images du web`() {
        val page = MailFramePage.of(served, remote = true)
        assertTrue(page.contains("img-src data: https: http:;"))
        assertTrue(page.contains("default-src 'none'"))
        assertFalse(page.contains(MailFramePage.CSP))
    }

    @Test fun `un document d'une autre forme reçoit quand même son en-tête et sa politique en premier`() {
        val page = MailFramePage.of("<p>nu</p>", remote = false)
        assertTrue(page.startsWith("<!doctype html><meta charset=\"utf-8\"><meta http-equiv=\"Content-Security-Policy\""))
        assertTrue(page.endsWith("<p>nu</p>"))
    }

    @Test fun `seuls un lien web et mailto s'ouvrent dehors`() {
        assertTrue(MailFramePage.opensOutside("https://exemple.fr/a"))
        assertTrue(MailFramePage.opensOutside("HTTP://exemple.fr"))
        assertTrue(MailFramePage.opensOutside("mailto:lea@x.fr"))
        assertFalse(MailFramePage.opensOutside("javascript:alert(1)"))
        assertFalse(MailFramePage.opensOutside("intent://scan#Intent;scheme=zxing;end"))
        assertFalse(MailFramePage.opensOutside("file:///sdcard/a"))
        assertFalse(MailFramePage.opensOutside("content://x/y"))
        assertFalse(MailFramePage.opensOutside("about:blank"))
    }

    @Test fun `le cadre se lit en HTML sous le jeton, ses images cette fois par images=1`() = runBlocking {
        server.enqueue(MockResponse.Builder().body(served).addHeader("Content-Type", "text/html; charset=utf-8").build())
        server.enqueue(MockResponse.Builder().body(served).build())
        val got = api.frame("pro:<a@x>")
        assertEquals(MoiApi.Result.Ok(served), got)
        val first = server.takeRequest()
        assertEquals("/api/moi/mail/frame", first.url.encodedPath)
        assertEquals("pro:<a@x>", first.url.queryParameter("ref"))
        assertNull(first.url.queryParameter("images"))
        assertEquals("text/html", first.headers["Accept"])
        assertEquals("Bearer mw_secret", first.headers["Authorization"])
        api.frame("pro:<a@x>", images = true)
        assertEquals("1", server.takeRequest().url.queryParameter("images"))
    }

    @Test fun `un mail sans HTML - le refus du serveur se lit en mots`() = runBlocking {
        server.enqueue(MockResponse.Builder().code(404).body("""{"error":"Ce mail n'a pas de HTML."}""").build())
        val got = api.frame("pro:<a@x>")
        assertTrue(got is MoiApi.Result.Failed)
        assertEquals("Ce mail n'a pas de HTML.", (got as MoiApi.Result.Failed).error.message)
    }

    @Test fun `« toujours pour cet expéditeur » part en JSON, avec sa clé d'envoi`() = runBlocking {
        server.enqueue(MockResponse.Builder().body("""{"ok":true,"message":""}""").build())
        api.images("pro:<a@x>", shown = true, key = "k1")
        val req = server.takeRequest()
        assertEquals("/api/moi/mail/images", req.url.encodedPath)
        assertEquals("k1", req.headers["Idempotency-Key"])
        val body = MikaJson.parseToJsonElement(req.body!!.utf8()).jsonObject
        assertEquals("pro:<a@x>", body["ref"]!!.jsonPrimitive.content)
        assertEquals(true, body["shown"]!!.jsonPrimitive.content.toBoolean())
    }
}
