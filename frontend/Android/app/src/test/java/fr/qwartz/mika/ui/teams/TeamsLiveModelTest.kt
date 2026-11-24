package fr.qwartz.mika.ui.teams

import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.teams.ConversationThread
import fr.qwartz.mika.data.moi.teams.Kinds
import fr.qwartz.mika.data.moi.teams.TeamsMessage
import fr.qwartz.mika.data.net.Topics
import fr.qwartz.mika.ui.mail.MainDispatcherRule
import fr.qwartz.mika.ui.shell.Load
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.withTimeoutOrNull
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Un fil Teams face au direct (ADR 0308), contre une fausse API : il se relit quand `teams` le nomme — sous la clé
 * demandée ou celle du serveur —, jamais pour une autre discussion ; le message arrivé paraît sans que le fil repasse
 * en chargement, et ce que tu tapes reste ; une reconnexion relit le fil et où elle en est.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class TeamsLiveModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val marc = TeamsMessage(ref = "m1", author = "Marc Delmas", authorId = "8:m", at = 1_500, text = "Tu as vu le devis ?")
    private val again = TeamsMessage(ref = "m2", author = "Marc Delmas", authorId = "8:m", at = 2_500, text = "Je te le renvoie.")
    private val thread = ConversationThread(key = "19:marc", account = "principal", title = "Marc Delmas", kind = Kinds.DM, messages = listOf(marc))
    private val api = FakeTeamsApi().apply { threads["principal~19:marc"] = thread }
    private val vm by lazy { main.model { TeamsThreadViewModel(TeamsDeps(api, now = { 10_000L })) } }

    private fun open() {
        // la clé de la route, telle qu'une liste l'a donnée ; le serveur rend la sienne (« principal~ » en moins)
        vm.open("principal~19:marc", "Sa réponse est arrivée.")
    }

    @Test fun `le fil se relit quand le direct le nomme - une autre discussion, rien`() = runTest {
        open()
        advanceUntilIdle()
        api.calls.clear()
        vm.onLive(LiveSignal.of(Topics.TEAMS to setOf("pro~19:lumen")))
        advanceUntilIdle()
        assertTrue(api.calls.isEmpty())
        // le serveur nomme le fil par sa clé à lui
        api.threads["principal~19:marc"] = thread.copy(messages = listOf(marc, again))
        vm.onLive(LiveSignal.of(Topics.TEAMS to setOf("19:marc")))
        advanceUntilIdle()
        assertEquals(listOf("thread:principal~19:marc"), api.calls)
        assertEquals(listOf("m1", "m2"), vm.messages.map { it.ref })
    }

    @Test fun `le message arrivé paraît sans repasser en chargement, et ce que tu tapes reste`() = runTest {
        open()
        advanceUntilIdle()
        vm.type("Je regarde ça")
        api.threads["principal~19:marc"] = thread.copy(messages = listOf(marc, again))
        api.hold("thread")
        launch { vm.onLive(LiveSignal.of(Topics.TEAMS to null)) }
        advanceUntilIdle()
        assertTrue("le fil montré reste pendant la lecture", vm.thread is Load.Ready)
        api.release("thread")
        advanceUntilIdle()
        assertEquals(listOf("m1", "m2"), vm.messages.map { it.ref })
        assertEquals("Je regarde ça", vm.text)
    }

    @Test fun `une reconnexion relit le fil et où elle en est`() = runTest {
        open()
        advanceUntilIdle()
        api.calls.clear()
        vm.onLive(LiveSignal.RESYNC)
        advanceUntilIdle()
        assertTrue(api.calls.toString(), "thread:principal~19:marc" in api.calls)
        assertTrue(api.calls.toString(), "work:19:marc" in api.calls)
    }

    @Test fun `le compte du fil n'est plus à toi - l'écran revient à la liste, sans relire le fil`() = runTest {
        open()
        advanceUntilIdle()
        // un compte encore là : le fil reste
        vm.onLive(LiveSignal.of(Topics.TEAMS to null))
        advanceUntilIdle()
        assertNull(withTimeoutOrNull(200) { vm.left.first() })
        // son partage retiré : ses comptes ne le disent plus
        api.accounts = api.accounts.copy(accounts = emptyList())
        api.calls.clear()
        vm.onLive(LiveSignal.of(Topics.TEAMS to null))
        advanceUntilIdle()
        assertEquals("principal~19:marc", withTimeoutOrNull(200) { vm.left.first() })
        assertTrue("le fil ne s'est pas relu (il dirait « introuvable »)", api.calls.none { it.startsWith("thread") })
        assertTrue(vm.thread is Load.Ready)
    }
}
