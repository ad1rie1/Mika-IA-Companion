package fr.qwartz.mika.data.moi

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.moi.mail.MailApi
import fr.qwartz.mika.data.moi.teams.TeamsApi
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

/**
 * « Corriger » (ADR 0307, porté de `frontendv2/src/screens/mail/compose.ts`) : ce que dit le message selon `changes`
 * et `refused` — les vrais mots de `strings.xml` —, ce que décide la réponse (le champ changé pendant l'appel),
 * « Annuler », `correct` lu dans `GET /api/moi` (absent d'un serveur d'avant : éteint), et l'appel
 * `POST /api/moi/correct` — son chemin, son corps, sans clé d'envoi, sa réponse (`refused` absent d'un serveur
 * d'avant : 0), ses refus dits tels que le serveur les donne, son client qui attend la fin d'une correction — depuis
 * Mail comme depuis Teams.
 */
class CorrectTest {
    private val server = MockWebServer()
    private val client = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).build()
    private lateinit var moi: MoiApi
    private val words = correctWords

    @Before fun start() {
        server.start()
        val base = (ServerBase.parse(server.url("/").toString()) as ServerBase.Parsed.Ok).base
        moi = MoiApi(client, { Credentials(base, "mw_secret") }, {}, Dispatchers.IO)
    }

    @After fun stop() = server.close()

    // ── Le message ──

    @Test fun `le message dit combien de fautes, et ce qui a été écarté parce que ça touchait aux mots`() {
        assertEquals("Aucune faute : ton texte reste tel quel.", correctedText(0, 0, words))
        assertEquals("La correction touchait aux mots : rien n'a été changé.", correctedText(0, 2, words))
        assertEquals("La correction touchait aux mots : rien n'a été changé.", correctedText(0, 1, words))
        assertEquals("1 faute corrigée.", correctedText(1, 0, words))
        assertEquals("3 fautes corrigées.", correctedText(3, 0, words))
        assertEquals("3 fautes corrigées ; 1 changement écarté : il touchait aux mots.", correctedText(3, 1, words))
        assertEquals("1 faute corrigée ; 2 changements écartés : ils touchaient aux mots.", correctedText(1, 2, words))
        assertEquals("12 fautes corrigées ; 5 changements écartés : ils touchaient aux mots.", correctedText(12, 5, words))
        // un compte qui ne se lit pas (négatif) : rien n'a été corrigé, rien écarté
        assertEquals("Aucune faute : ton texte reste tel quel.", correctedText(-2, -1, words))
        assertEquals("2 fautes corrigées.", correctedText(2, -1, words))
    }

    @Test fun `les autres mots de Corriger sont ceux du web`() {
        assertEquals("Rien à corriger : le champ est vide.", words.empty)
        assertEquals("Tu as continué d'écrire : la correction n'a pas été posée.", words.moved)
        assertEquals("Aucun modèle ne corrige : un opérateur en choisit un dans Réglages › Intelligence.", words.off)
        assertEquals("Correction…", AppStrings.string("correct_busy"))
        assertEquals("Annuler", AppStrings.string("correct_undo"))
    }

    // ── Ce que décide la réponse ──

    @Test fun `la réponse se pose seulement si le champ n'a pas changé et qu'il y avait des fautes`() {
        val asked = "je pense que sa marche"
        assertEquals(CorrectTurn.PUT, correctTurn(asked, asked, Corrected("je pense que ça marche", 1)))
        assertEquals(CorrectTurn.PUT, correctTurn(asked, asked, Corrected("je pense que ça marche", 1, refused = 2)))
        assertEquals(CorrectTurn.NONE, correctTurn(asked, asked, Corrected(asked, 0)))
        // tout ce qu'il proposait touchait aux mots : rien n'est posé, pas d'« Annuler »
        assertEquals(CorrectTurn.NONE, correctTurn(asked, asked, Corrected(asked, 0, refused = 3)))
        // tu as continué d'écrire : rien n'est posé, même s'il y avait des fautes
        assertEquals(CorrectTurn.MOVED, correctTurn(asked, "$asked, non ?", Corrected("je pense que ça marche", 1)))
        assertEquals(CorrectTurn.MOVED, correctTurn(asked, "$asked ", Corrected(asked, 0)))
        // le champ vidé (envoyé) pendant l'appel, aussi
        assertEquals(CorrectTurn.MOVED, correctTurn(asked, "", Corrected("je pense que ça marche", 1)))
    }

    @Test fun `Annuler rend ton texte tant que le champ contient le texte corrigé`() {
        val before = "a demain"
        val fixed = "à demain"
        assertEquals(before, undoCorrection(fixed, fixed, before))
        // tu as écrit depuis : ce que tu as écrit reste
        assertNull(undoCorrection("à demain, 9 h", fixed, before))
        assertNull(undoCorrection("", fixed, before))
    }

    // ── `GET /api/moi` → `correct` ──

    @Test fun `correct se lit dans GET api-moi, absent d'un serveur d'avant - éteint`() {
        val on = MikaJson.decodeFromString(
            Me.serializer(),
            """{"username":"adrien","name":"Adrien Moreau","handle":"user_1","person":"user_1","operator":true,
               "owner":true,"counts":{"mail":7,"teams":1,"phone":0,"projects":3},"correct":true}""",
        )
        assertTrue(on.correct)
        assertEquals(7, on.counts.mail)
        assertFalse(MikaJson.decodeFromString(Me.serializer(), """{"username":"adrien","correct":false}""").correct)
        // un serveur d'avant l'ADR 0307 ne le dit pas
        assertFalse(MikaJson.decodeFromString(Me.serializer(), """{"username":"adrien","name":"Adrien"}""").correct)
        // ni un `null`
        assertFalse(MikaJson.decodeFromString(Me.serializer(), """{"username":"adrien","correct":null}""").correct)
    }

    // ── `POST /api/moi/correct` ──

    private fun sentJson(): Pair<String, JsonObject> {
        val req = server.takeRequest()
        assertEquals("POST", req.method)
        assertEquals("Bearer mw_secret", req.headers["Authorization"])
        // rien n'est gardé : pas de clé d'envoi
        assertNull(req.headers["Idempotency-Key"])
        return req.url.encodedPath to MikaJson.parseToJsonElement(req.body!!.utf8()).jsonObject
    }

    @Test fun `l'appel part sur api-moi-correct avec le texte seul, et sa réponse se lit`() = runBlocking {
        server.enqueue(MockResponse.Builder().body("""{"text":"Je pense que ça marche.","changes":2,"refused":1,"futur":1}""").build())
        val text = "  Je pense que sa marche .\n"
        val got = (moi.correct(text) as MoiApi.Result.Ok).value
        assertEquals(Corrected("Je pense que ça marche.", 2, refused = 1), got)
        val (path, body) = sentJson()
        assertEquals("/api/moi/correct", path)
        // le texte part tel quel, ses blancs de bord compris
        assertEquals(JsonObject(mapOf("text" to JsonPrimitive(text))), body)
        // un serveur d'avant ne dit pas `refused` : rien d'écarté
        server.enqueue(MockResponse.Builder().body("""{"text":"Ça marche.","changes":1}""").build())
        assertEquals(Corrected("Ça marche.", 1, refused = 0), (moi.correct("Sa marche.") as MoiApi.Result.Ok).value)
        server.takeRequest()
        Unit
    }

    @Test fun `Mail et Teams corrigent par la même route`() = runBlocking {
        server.enqueue(MockResponse.Builder().body("""{"text":"Bonjour Léa,","changes":0,"refused":0}""").build())
        val mail = (MailApi(moi).correct("Bonjour Léa,") as MoiApi.Result.Ok).value
        assertEquals(0, mail.changes)
        assertEquals("/api/moi/correct" to "Bonjour Léa,", sentJson().let { (p, b) -> p to (b["text"] as JsonPrimitive).content })
        server.enqueue(MockResponse.Builder().body("""{"text":"Ça marche.","changes":1,"refused":0}""").build())
        val teams = (TeamsApi(moi).correct("Sa marche.") as MoiApi.Result.Ok).value
        assertEquals(Corrected("Ça marche.", 1), teams)
        assertEquals("/api/moi/correct" to "Sa marche.", sentJson().let { (p, b) -> p to (b["text"] as JsonPrimitive).content })
    }

    @Test fun `ses refus se disent tels que le serveur les donne`() = runBlocking {
        for ((code, error) in listOf(
            409 to "Aucun modèle ne corrige : un opérateur en choisit un dans Réglages › Intelligence (« corriger les fautes »).",
            413 to "Ton texte est trop long pour être corrigé d'un coup : corrige-le en plusieurs fois.",
            422 to "Le modèle n'a pas voulu corriger ce texte : rien n'a été changé.",
            429 to "Une correction est déjà en cours : attends qu'elle finisse.",
            429 to "Trop de corrections d'affilée : attends une minute.",
            502 to "La correction n'a pas abouti : réessaie dans un instant.",
        )) {
            server.enqueue(MockResponse.Builder().code(code).body("""{"error":"$error"}""").build())
            val err = (moi.correct("sa marche") as MoiApi.Result.Failed).error
            assertEquals(code, err.code)
            assertEquals(error, refusalText(err.message, err.fields))
            server.takeRequest()
        }
    }

    // ── Le délai : le serveur se donne 50 s, et ne répond qu'à la fin ──

    /** Ce que chaque requête a emporté de son client : son chemin, son délai de lecture et celui de l'appel entier (ms).
     *  Il répond lui-même : rien ne passe par le réseau. */
    private class Timeouts : Interceptor {
        val seen = mutableListOf<Triple<String, Int, Long>>()
        override fun intercept(chain: Interceptor.Chain): Response {
            val call = TimeUnit.NANOSECONDS.toMillis(chain.call().timeout().timeoutNanos())
            seen += Triple(chain.request().url.encodedPath, chain.readTimeoutMillis(), call)
            val body = if (chain.request().url.encodedPath.endsWith("/correct")) """{"text":"Ça marche.","changes":1}""" else """{"accounts":[]}"""
            return Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(200).message("OK")
                .body(body.toResponseBody("application/json".toMediaType())).build()
        }
    }

    @Test fun `Corriger passe par un client qui attend plus de 70 s, les autres appels gardent leurs délais`() = runBlocking {
        val timeouts = Timeouts()
        // les délais de `AppGraph.http`, le client des appels courts
        val http = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS).callTimeout(60, TimeUnit.SECONDS)
            .addInterceptor(timeouts).build()
        val long = correctClient(http)
        assertTrue(long.readTimeoutMillis >= 70_000 && long.callTimeoutMillis >= 70_000)
        // dérivé : le reste du client tient, et le client court ne change pas
        assertEquals(15_000, long.connectTimeoutMillis)
        assertEquals(30_000 to 60_000, http.readTimeoutMillis to http.callTimeoutMillis)
        val base = (ServerBase.parse("http://127.0.0.1:8001") as ServerBase.Parsed.Ok).base
        fun moiOn(c: OkHttpClient) = MoiApi(c, { Credentials(base, "mw_secret") }, {}, Dispatchers.IO)
        val short = moiOn(http)
        val corrections = moiOn(long)
        val teams = TeamsApi(short, corrections)
        val mail = MailApi(short, corrections = corrections)
        assertTrue(teams.correct("Sa marche.") is MoiApi.Result.Ok)
        assertTrue(mail.correct("Sa marche.") is MoiApi.Result.Ok)
        assertTrue(teams.accounts() is MoiApi.Result.Ok)
        val expectLong = Triple("/api/moi/correct", CORRECT_READ_S.toInt() * 1000, CORRECT_CALL_S * 1000)
        assertEquals(
            listOf(expectLong, expectLong, Triple("/api/moi/teams/accounts", 30_000, 60_000L)),
            timeouts.seen,
        )
    }
}
