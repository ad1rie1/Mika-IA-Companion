package fr.qwartz.mika.data.chat

import fr.qwartz.mika.data.net.MikaProtocol
import fr.qwartz.mika.data.net.ServerFrame
import fr.qwartz.mika.data.net.ToolUse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

/** Ses cartes de travail (ADR 0116) : ce que chaque trame `tool` en fait, et ce que l'écran en écrit. */
class WorkLogTest {
    private fun start(call: String, name: String, args: String = "{}", at: Long? = null, episode: String = "e1", replyTo: Long? = 811) =
        ServerFrame.Tool(episode, replyTo, MikaProtocol.TOOL_START, callId = call, name = name, args = args, at = at)

    private fun end(call: String, name: String, ok: Boolean?, at: Long? = null, duration: Long? = null, episode: String = "e1", replyTo: Long? = 811) =
        ServerFrame.Tool(episode, replyTo, MikaProtocol.TOOL_END, callId = call, name = name, ok = ok, result = "rendu",
            durationMs = duration, at = at)

    private fun note(text: String, episode: String = "e1", replyTo: Long? = 811) =
        ServerFrame.Tool(episode, replyTo, MikaProtocol.TOOL_NOTE, text = text)

    private fun done(outcome: String, at: Long? = null, episode: String = "e1", replyTo: Long? = 811) =
        ServerFrame.Tool(episode, replyTo, MikaProtocol.TOOL_DONE, outcome = outcome, at = at)

    private fun WorkLog.feed(vararg frames: ServerFrame.Tool) = frames.fold(this) { log, f -> log.apply(f) }

    @Test fun `les outils dans l'ordre, chacun fini à son end, les notes entre deux`() {
        val log = WorkLog().feed(
            start("t1", "memory_search", """{"query": "Léa"}""", at = 1_000),
            note("Je regarde dans ta boîte…"),
            start("t2", "email_search", at = 1_100),
            end("t1", "memory_search", ok = true, at = 1_182, duration = 182),
            end("t2", "email_search", ok = false, at = 1_400),
        )
        val card = log.cards.single()
        assertEquals("we1", card.key)
        assertEquals(811L, card.replyTo)
        val (t1, n, t2) = card.steps
        assertEquals(WorkStep.Tool("t1", "memory_search", """{"query": "Léa"}""", ok = true, result = "rendu", durationMs = 182, startedAt = 1_000), t1)
        assertEquals(WorkStep.Note("Je regarde dans ta boîte…"), n)
        // une durée que le serveur ne dit pas se mesure de son start à son end
        assertEquals(300L, (t2 as WorkStep.Tool).durationMs)
        assertEquals(false, t2.ok)
        assertTrue(card.running)
        assertEquals(2, card.tools.size)

        val finished = log.apply(done("done", at = 4_200)).cards.single()
        assertEquals("done", finished.outcome)
        assertFalse(finished.running)
        assertEquals(3_200L, finished.elapsedMs)
    }

    @Test fun `un end sans start crée sa ligne, un appel sans identifiant aussi`() {
        val card = WorkLog().feed(
            end("refusé", "email_send", ok = false),
            end("", "web_fetch", ok = true),
            end("", "web_fetch", ok = true),
        ).cards.single()
        assertEquals(listOf("email_send", "web_fetch", "web_fetch"), card.tools.map { it.name })
        assertEquals(listOf(false, true, true), card.tools.map { it.ok })
    }

    @Test fun `un done seul n'ouvre pas de carte, une note vide ne s'écrit pas, l'issue vide vaut done`() {
        assertTrue(WorkLog().apply(done("failed")).cards.isEmpty())
        val card = WorkLog().feed(note("   "), done("")).cards.single()
        assertTrue(card.steps.isEmpty())
        assertEquals(MikaProtocol.TOOL_OUTCOME_DONE, card.outcome)
    }

    @Test fun `un nouvel épisode pour le même message remplace la carte, et l'ancien ne revient pas`() {
        val first = WorkLog().feed(start("a", "memory_search"), done("superseded"))
        val second = first.apply(start("b", "email_search", episode = "e2"))
        assertEquals(listOf("e2"), second.cards.map { it.episode })
        assertEquals(listOf("e1"), second.retired)
        // une trame tardive de l'épisode supplanté est ignorée
        assertSame(second, second.apply(end("a", "memory_search", ok = true)))
        // un autre message garde sa carte à côté
        val other = second.apply(start("c", "ws_read", episode = "e3", replyTo = 900))
        assertEquals(listOf("e2", "e3"), other.cards.map { it.episode })
    }

    @Test fun `sa réponse replie la carte de son message, ou la dernière sans message`() {
        val log = WorkLog().feed(
            start("a", "x"),
            start("b", "y", episode = "e2", replyTo = 900),
            start("c", "z", episode = "e3", replyTo = null),
        )
        val answered = log.answer(811, 812)
        val card = answered.cards.first { it.episode == "e1" }
        assertTrue(card.answered)
        assertEquals(812L, card.answerId)
        assertFalse(answered.cards.first { it.episode == "e2" }.answered)
        assertTrue(log.answer(null, 950).cards.first { it.episode == "e3" }.answered)
        assertSame(log, log.answer(12345, 1))
    }

    @Test fun `des cartes et des étapes bornées`() {
        var log = WorkLog()
        for (n in 0 until MikaProtocol.MAX_WORK_CARDS + 3) log = log.apply(start("t", "x", episode = "e$n", replyTo = n.toLong()))
        assertEquals(MikaProtocol.MAX_WORK_CARDS, log.cards.size)
        assertEquals("e3", log.cards.first().episode)
        var one = WorkLog()
        for (n in 0 until MikaProtocol.MAX_WORK_STEPS + 5) one = one.apply(note("note $n"))
        assertEquals(MikaProtocol.MAX_WORK_STEPS, one.cards.single().steps.size)
        assertEquals(5, one.cards.single().dropped)
    }

    @Test fun `sans heure, le temps passé est la somme des durées de ses outils`() {
        val card = WorkLog().feed(end("a", "x", ok = true, duration = 1_000), end("b", "y", ok = true, duration = 2_500)).cards.single()
        assertEquals(3_500L, card.elapsedMs)
        assertNull(WorkLog().apply(note("rien")).cards.single().elapsedMs)
    }

    @Test fun `ce que l'écran écrit - l'aperçu des arguments, la durée, la ligne des outils`() {
        assertEquals("anniversaire de Léa", WorkText.argsPreview("""{"query": "anniversaire de Léa"}"""))
        assertEquals("Paul, 3, true", WorkText.argsPreview("""{"to":"Paul","limit":3,"unread":true}"""))
        assertEquals("""a, {"b":1}""", WorkText.argsPreview("""["a", {"b": 1}]"""))
        assertEquals("pas du json", WorkText.argsPreview("  pas\n du   json "))
        assertEquals("", WorkText.argsPreview("{}"))
        val long = WorkText.argsPreview("""{"q": "${"mot ".repeat(40)}"}""", max = 20)
        assertEquals(20, long.length)
        assertTrue(long.endsWith("…"))

        assertEquals("182 ms", WorkText.duration(182))
        assertEquals("3,2 s", WorkText.duration(3_200))
        assertEquals("2 min 05 s", WorkText.duration(125_000))

        assertEquals("email_search ✓ · email_read ✗", WorkText.toolsLine(listOf(ToolUse("email_search", true), ToolUse("email_read", false))))
    }

    @Test fun `une parole d'elle fait partir les cartes finies sans réponse, pas celles où elle travaille`() {
        val log = WorkLog().feed(
            start("a", "x"), done("superseded"),
            start("b", "y", episode = "e2", replyTo = 900),
            start("c", "z", episode = "e3", replyTo = 950), done("done", episode = "e3", replyTo = 950),
        )
        val settled = log.settle(950, 951, pro = true)
        assertEquals(listOf("e2", "e3"), settled.cards.map { it.episode })
        assertTrue(settled.cards.last().answered)
        assertTrue("e1" in settled.retired)
        // une parole ordinaire ne replie rien, et fait le même ménage
        assertEquals(listOf("e2"), log.settle(null, 999, pro = false).cards.map { it.episode })
        assertEquals(listOf("e2"), log.prune().cards.map { it.episode })
        assertSame(settled, settled.prune())
    }
}
