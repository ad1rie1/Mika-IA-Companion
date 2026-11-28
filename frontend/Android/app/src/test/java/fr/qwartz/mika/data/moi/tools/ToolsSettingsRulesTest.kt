package fr.qwartz.mika.data.moi.tools

import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.Tone
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Les règles de Paramètres › Services MCP, portées du client web (`frontend/Web/src/screens/outils/words.ts`, ses tests
 * `settings.test.ts`) : l'état d'un service et de ses outils, les choix qui partent, ce qu'un service réglé envoie, son
 * nom et son adresse, ses lignes d'accès, les en-têtes redemandés quand l'adresse mène ailleurs.
 */
class ToolsSettingsRulesTest {
    // ── les services ──

    @Test fun `l'état d'un service et de ses outils`() {
        assertEquals(Tone.OK to "connecté", stateWords("connecte"))
        assertEquals(Tone.NEUTRAL to "jamais joint", stateWords("jamais"))
        assertEquals(Tone.NEUTRAL to "bizarre", stateWords("bizarre"))
        assertTrue(serviceTrouble("panne") && !serviceTrouble("connecte"))
        val tools = listOf(
            ServiceTool(remote = "a", choice = ToolChoices.READ),
            ServiceTool(remote = "b", choice = ToolChoices.OFF),
            ServiceTool(remote = "c", choice = "", new = true),
            ServiceTool(remote = "d", choice = ToolChoices.ACT, changed = true),
        )
        assertEquals(Served(served = 2, total = 4, review = 2), servedOf(tools))
        assertEquals(Tone.INFO to "nouveau", toolState(tools[2]))
        assertEquals(Tone.WARN to "changé", toolState(tools[3]))
        assertEquals(Tone.NEUTRAL to "coupé", toolState(tools[1]))
        assertEquals("", shownChoice(tools[3]))
        assertEquals("Il agit", choiceWords(ToolChoices.ACT))
    }

    @Test fun `ne partent que les choix d'outils qui ont bougé, un outil qui attend se décide même comme avant`() {
        val tools = listOf(
            ServiceTool(remote = "a", choice = ToolChoices.READ),
            ServiceTool(remote = "d", choice = ToolChoices.ACT, changed = true),
            ServiceTool(remote = "c", new = true),
        )
        val picks = mapOf("a" to ToolChoices.READ, "d" to ToolChoices.ACT, "c" to "", "zz" to ToolChoices.READ)
        assertEquals(mapOf("d" to ToolChoices.ACT), toolChoiceChanges(tools, picks))
        assertEquals(mapOf("a" to ToolChoices.OFF, "d" to ToolChoices.ACT), toolChoiceChanges(tools, picks + ("a" to ToolChoices.OFF)))
    }

    @Test fun `ce qui part d'un service réglé, des en-têtes seulement s'ils sont tapés`() {
        val s = Service(name = "meteo", purpose = "météo", url = "https://m.example/mcp", enabled = true, headers = true)
        assertTrue(serviceChanges(s, "météo", "", " https://m.example/mcp ", true, "").isEmpty())
        val sent = serviceChanges(s, "la météo", "le matin", "https://n.example/mcp", false, "Authorization: Bearer x")
        assertEquals(setOf("purpose", "when_to_use", "url", "enabled", "secret_headers"), sent.keys)
        assertFalse(sent["enabled"]!!.jsonPrimitive.boolean)
    }

    @Test fun `le nom et l'adresse d'un service`() {
        assertEquals("Un nom court.", serviceNameProblem(""))
        assertEquals("", serviceNameProblem("agenda_club"))
        assertTrue(serviceNameProblem("Agenda").isNotEmpty())
        assertTrue(serviceNameProblem("a".repeat(25)).isNotEmpty())
        assertEquals("Son adresse.", urlProblem(" "))
        assertEquals("", urlProblem("https://x.example/mcp"))
        assertTrue(urlProblem("http://x.example/mcp").startsWith("Une adresse https"))
    }

    @Test fun `ses lignes d'accès, la tienne est « toi », un partage par son nom`() {
        val mine = AccessLine(who = "Adrien", mine = true)
        val lea = AccessLine(who = "Léa")
        assertEquals("toi", whoWords(mine))
        assertEquals("tout le monde", whoWords(AccessLine()))
        assertEquals("Léa", sharedWith(Service(access = listOf(mine, lea, AccessLine()))))
        assertEquals("fermé : personne d'autre", defaultWords(AccessLine(read = "non", act = "non")))
        assertEquals("fermé : personne d'autre", defaultWords(null))
        assertEquals("il lit : seule · il agit : non · privé", defaultWords(AccessLine(read = "seule", act = "x", readWords = "seule", actWords = "non", keepWords = "privé")))
        val r = ReceivedService(level = Levels.USE, ownerName = "Léa", line = AccessLine(readWords = "seule", actWords = ""))
        assertTrue(receivedSentence(r).contains("et ceux qui agissent"))
        assertEquals("seule", forYou(r, ToolChoices.READ))
        assertEquals("non", forYou(r, ToolChoices.ACT))
    }

    @Test fun `une adresse qui mène ailleurs redemande ses en-têtes gardés (ADR 0236)`() {
        val kept = Service(name = "agenda", url = "https://agenda.exemple.fr/mcp", headers = true)
        fun changes(url: String, headers: String = "", clear: Boolean = false) = serviceChanges(kept, "", "", url, true, headers, clear)
        assertEquals(mapOf("secret_headers" to HEADERS_TO_RETYPE), headersToRetype(kept, changes("https://autre.example/mcp")))
        assertEquals(mapOf("secret_headers" to HEADERS_TO_RETYPE), headersToRetype(kept, changes("https://agenda.exemple.fr:8443/mcp")))
        assertTrue(headersToRetype(kept, changes("https://autre.example/mcp", headers = "Authorization: Bearer x")).isEmpty())
        val cleared = changes("https://autre.example/mcp", clear = true)
        assertEquals(true, cleared["clear_headers"]?.jsonPrimitive?.boolean)
        assertTrue(headersToRetype(kept, cleared).isEmpty())
        assertTrue(headersToRetype(kept, changes("https://AGENDA.exemple.fr:443/v2/mcp")).isEmpty())
        assertTrue(headersToRetype(kept.copy(headers = false), changes("https://autre.example/mcp")).isEmpty())
        // retirer ce qu'il n'a pas ne part pas
        assertFalse("clear_headers" in serviceChanges(kept.copy(headers = false), "", "", kept.url, true, "", true))
        assertEquals(urlOrigin("https://Agenda.exemple.fr/x"), urlOrigin("https://agenda.exemple.fr:443/mcp"))
    }
}
