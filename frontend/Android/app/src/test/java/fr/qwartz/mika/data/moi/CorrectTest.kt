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
 * « Corriger » (ADR 0307, porté de `frontendv2/src/screens/mail/compose.ts`) : ce que dit le message selon `changes`,
 * ce que décide la réponse (le champ changé pendant l'appel), « Annuler », `correct` lu dans `GET /api/moi` (absent
 * d'un serveur d'avant : éteint), et l'appel `POST /api/moi/correct` — son chemin, son corps, sans clé d'envoi, ses
 * refus dits tels que le serveur les donne — depuis Mail comme depuis Teams.
 */
class CorrectTest {
    private val server = MockWebServer()
    private val client = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).build()
    private lateinit var moi: MoiApi

    /** Les mots de `strings.xml`, et le pluriel de `correct_done` tel qu'Android le choisit en français. */
    private val words = CorrectWords(
        empty = "Rien à corriger : le champ est vide.",
        none = "Aucune faute : ton texte reste tel quel.",
        moved = "Tu as continué d'écrire : la correction n'a pas été posée.",
        off = "Aucun modèle ne corrige : un opérateur en choisit un dans Réglages › Intelligence.",
        fixed = { n -> if (n <= 1) "$n faute corrigée." else "$n fautes corrigées." },
    )

    @Before fun start() {
        server.start()
        val base = (ServerBase.parse(server.url("/").toString()) as ServerBase.Parsed.Ok).base
        moi = MoiApi(client, { Credentials(base, "mw_secret") }, {}, Dispatchers.IO)
    }

    @After fun stop() = server.close()

    // ── Le message ──

    @Test fun `le message dit combien de fautes, ou aucune`() {
        assertEquals("Aucune faute : ton texte reste tel quel.", correctedText(0, words))
        assertEquals("1 faute corrigée.", correctedText(1, words))
        assertEquals("3 fautes corrigées.", correctedText(3, words))
        // un compte qui ne se lit pas (négatif) : rien n'a été corrigé
        assertEquals("Aucune faute : ton texte reste tel quel.", correctedText(-2, words))
    }

    // ── Ce que décide la réponse ──

    @Test fun `la réponse se pose seulement si le champ n'a pas changé et qu'il y avait des fautes`() {
        val asked = "je pense que sa marche"
        assertEquals(CorrectTurn.PUT, correctTurn(asked, asked, Corrected("je pense que ça marche", 1)))
        assertEquals(CorrectTurn.NONE, correctTurn(asked, asked, Corrected(asked, 0)))
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
        server.enqueue(MockResponse.Builder().body("""{"text":"Je pense que ça marche.","changes":2,"futur":1}""").build())
        val text = "  Je pense que sa marche .\n"
        val got = (moi.correct(text) as MoiApi.Result.Ok).value
        assertEquals(Corrected("Je pense que ça marche.", 2), got)
        val (path, body) = sentJson()
        assertEquals("/api/moi/correct", path)
        // le texte part tel quel, ses blancs de bord compris
        assertEquals(JsonObject(mapOf("text" to JsonPrimitive(text))), body)
    }

    @Test fun `Mail et Teams corrigent par la même route`() = runBlocking {
        server.enqueue(MockResponse.Builder().body("""{"text":"Bonjour Léa,","changes":0}""").build())
        val mail = (MailApi(moi).correct("Bonjour Léa,") as MoiApi.Result.Ok).value
        assertEquals(0, mail.changes)
        assertEquals("/api/moi/correct" to "Bonjour Léa,", sentJson().let { (p, b) -> p to (b["text"] as JsonPrimitive).content })
        server.enqueue(MockResponse.Builder().body("""{"text":"Ça marche.","changes":1}""").build())
        val teams = (TeamsApi(moi).correct("Sa marche.") as MoiApi.Result.Ok).value
        assertEquals(Corrected("Ça marche.", 1), teams)
        assertEquals("/api/moi/correct" to "Sa marche.", sentJson().let { (p, b) -> p to (b["text"] as JsonPrimitive).content })
    }

    @Test fun `ses refus se disent tels que le serveur les donne`() = runBlocking {
        for ((code, error) in listOf(
            409 to "Aucun modèle ne corrige : un opérateur en choisit un dans Réglages › Intelligence (« corriger les fautes »).",
            422 to "La correction changeait trop ton texte : rien n'a été changé.",
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
}
