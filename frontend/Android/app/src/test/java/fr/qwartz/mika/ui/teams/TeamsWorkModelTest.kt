package fr.qwartz.mika.ui.teams

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.Work
import fr.qwartz.mika.data.moi.WorkSteps
import fr.qwartz.mika.data.moi.teams.ALREADY_ASKED
import fr.qwartz.mika.data.moi.teams.ConversationThread
import fr.qwartz.mika.data.moi.teams.Kinds
import fr.qwartz.mika.data.moi.teams.ReplyStates
import fr.qwartz.mika.data.moi.teams.TeamsDone
import fr.qwartz.mika.data.moi.teams.TeamsMessage
import fr.qwartz.mika.data.moi.teams.TeamsReply
import fr.qwartz.mika.data.moi.teams.TeamsWork
import fr.qwartz.mika.data.net.Topics
import fr.qwartz.mika.ui.mail.MainDispatcherRule
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.withTimeoutOrNull
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * « Préremplir avec Mika » suivi en direct dans un fil (ADR 0306), contre une fausse API : sa ligne paraît aussitôt
 * (elle s'y met, depuis maintenant) puis suit ce que dit le serveur ; `/teams/work` relu sans relire le fil quand le
 * direct (`teams.work`, ADR 0308) nomme ce fil — une autre discussion nommée ne relit rien ; le fil relu quand sa
 * réponse arrive ou qu'elle a fini sans en rendre ; ce qu'elle prépare d'elle-même suivi aussi ; plus de plafond ; une
 * relecture manquée qui attend le signal suivant.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class TeamsWorkModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val marc = TeamsMessage(ref = "m1", author = "Marc Delmas", authorId = "8:m", at = 1_500, text = "Tu as vu le devis ?")
    private val quiet = ConversationThread(key = "19:marc", account = "principal", title = "Marc Delmas", kind = Kinds.DM, messages = listOf(marc))
    private val thinking = Work(WorkSteps.THINKING, "", since = 9_000, started = 8_000)
    private val tool = Work(WorkSteps.TOOL, "Relire une de tes conversations Teams", since = 9_500, started = 8_000)

    private val api = FakeTeamsApi().apply { threads["19:marc"] = quiet }
    private var clock = 10_000L
    private val vm by lazy { main.model { TeamsThreadViewModel(TeamsDeps(api, now = { clock })) } }

    private suspend fun <T> Flow<T>.next(): T? = withTimeoutOrNull(200) { first() }

    private fun open() {
        vm.open("19:marc", "Sa réponse est arrivée.")
    }

    private fun prefill() = vm.prefill(noReceived = "Aucun message reçu.", askedText = "Demandé : elle s'y met tout de suite ; sa réponse arrivera ici.")

    /** Ce que le serveur dit du fil : demandée, et où elle en est. */
    private fun serverSays(asked: Boolean, work: Work?, underWay: Boolean = false, replies: List<TeamsReply> = emptyList()) {
        api.threads["19:marc"] = quiet.copy(asked = asked, work = work, underWay = underWay, replies = replies)
    }

    @Test fun `« Préremplir » réussi - sa ligne paraît aussitôt, puis la relecture du fil la corrige`() = runTest {
        open()
        advanceUntilIdle()
        assertNull(vm.work)
        assertFalse(vm.watching)
        // le serveur répond « demandé » (et elle réfléchit déjà) ; le fil relu ensuite ne répond pas encore
        serverSays(asked = true, work = thinking)
        api.hold("thread")
        prefill()
        advanceUntilIdle()
        assertEquals(Work(WorkSteps.WAITING, "", 10_000, 10_000), vm.work)
        assertTrue(vm.asked)
        assertTrue(vm.watching)
        assertEquals("Demandé : elle s'y met tout de suite ; sa réponse arrivera ici.", vm.said.next())
        // le fil relu dit où elle en est vraiment
        api.release("thread")
        advanceUntilIdle()
        assertEquals(thinking, vm.work)
    }

    @Test fun `déjà demandée, ou une réponse en chemin - ce que dit le serveur se dit tel quel`() = runTest {
        open()
        advanceUntilIdle()
        api.prefillResult = MoiApi.Result.Ok(TeamsDone(ok = true, message = ALREADY_ASKED, asked = true))
        prefill()
        advanceUntilIdle()
        assertEquals(ALREADY_ASKED, vm.said.next())
        api.prefillResult = MoiApi.Result.Ok(TeamsDone(ok = true, message = "Une réponse est déjà en chemin.", draft = "r1"))
        prefill()
        advanceUntilIdle()
        assertEquals("Une réponse est déjà en chemin.", vm.said.next())
    }

    @Test fun `elle y travaille - seule sa ligne change, le fil ne se relit pas`() = runTest {
        serverSays(asked = true, work = thinking)
        open()
        advanceUntilIdle()
        assertEquals(thinking, vm.work)
        assertTrue(vm.watching)
        api.calls.clear()
        api.workResult = MoiApi.Result.Ok(TeamsWork(tool, asked = true, underWay = false))
        vm.readWork()
        advanceUntilIdle()
        assertEquals(tool, vm.work)
        assertEquals(listOf("work:19:marc"), api.calls)
        assertTrue(vm.watching)
    }

    @Test fun `sa réponse est arrivée - le fil se relit, on cesse de guetter, et elle se dit`() = runTest {
        prefillThenWorking()
        val reply = TeamsReply(id = "r1", account = "principal", conversation = "19:marc", inReplyTo = "m1", state = ReplyStates.WAITING, asked = true)
        serverSays(asked = false, work = null, underWay = true, replies = listOf(reply))
        api.workResult = MoiApi.Result.Ok(TeamsWork(null, asked = false, underWay = true))
        api.calls.clear()
        vm.readWork()
        advanceUntilIdle()
        assertEquals(listOf("work:19:marc", "thread:19:marc"), api.calls)
        assertFalse(vm.watching)
        assertFalse(vm.asked)
        assertEquals("Sa réponse est arrivée.", vm.said.next())
    }

    @Test fun `finie sans en rendre - le fil se relit et on cesse de guetter, même demandée d'ici`() = runTest {
        prefillThenWorking()
        // le fil relu dirait encore « demandée » d'ici : la relecture de work suffit à cesser
        serverSays(asked = false, work = null)
        api.workResult = MoiApi.Result.Ok(TeamsWork(null, asked = false, underWay = false))
        api.calls.clear()
        vm.readWork()
        advanceUntilIdle()
        assertEquals(listOf("work:19:marc", "thread:19:marc"), api.calls)
        assertNull(vm.work)
        assertFalse(vm.asked)
        assertFalse(vm.watching)
        // le direct qui nomme une autre discussion ne relit rien ici
        api.calls.clear()
        vm.onLive(LiveSignal.of(Topics.TEAMS_WORK to setOf("19:lumen")))
        advanceUntilIdle()
        assertTrue(api.calls.isEmpty())
    }

    @Test fun `ce qu'elle prépare d'elle-même se guette aussi, sans demande`() = runTest {
        serverSays(asked = false, work = thinking)
        open()
        advanceUntilIdle()
        assertFalse(vm.asked)
        assertTrue(vm.watching)
        api.workResult = MoiApi.Result.Ok(TeamsWork(tool, asked = false, underWay = false))
        vm.readWork()
        advanceUntilIdle()
        assertEquals(tool, vm.work)
    }

    @Test fun `plus de plafond - une heure après la demande, l'étape que le direct dit se suit encore`() = runTest {
        prefillThenWorking()
        clock += 60 * 60_000L
        api.calls.clear()
        api.workResult = MoiApi.Result.Ok(TeamsWork(tool, asked = true, underWay = false))
        vm.onLive(LiveSignal.of(Topics.TEAMS_WORK to setOf("19:marc")))
        advanceUntilIdle()
        assertEquals(listOf("work:19:marc"), api.calls)
        assertEquals(tool, vm.work)
        assertTrue(vm.watching)
    }

    @Test fun `une relecture manquée garde la ligne et attend la suivante`() = runTest {
        prefillThenWorking()
        api.workResult = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        vm.readWork()
        advanceUntilIdle()
        assertEquals(thinking, vm.work)
        assertTrue(vm.watching)
    }

    @Test fun `une autre discussion ouverte oublie où elle en était dans la précédente`() = runTest {
        serverSays(asked = true, work = thinking)
        api.threads["19:lumen"] = ConversationThread(key = "19:lumen", account = "principal", title = "Lumen", kind = Kinds.GROUP, messages = listOf(marc.copy(ref = "l1")))
        open()
        advanceUntilIdle()
        api.hold("thread")
        vm.open("19:lumen", "Sa réponse est arrivée.")
        assertNull(vm.work)
        assertFalse(vm.watching)
        api.release("thread")
        advanceUntilIdle()
        assertNull(vm.work)
    }

    /** Une réponse demandée d'ici, sur laquelle elle réfléchit. */
    private suspend fun TestScope.prefillThenWorking() {
        open()
        advanceUntilIdle()
        serverSays(asked = true, work = thinking)
        prefill()
        advanceUntilIdle()
        vm.said.next()
        assertEquals(thinking, vm.work)
        assertTrue(vm.watching)
    }
}
