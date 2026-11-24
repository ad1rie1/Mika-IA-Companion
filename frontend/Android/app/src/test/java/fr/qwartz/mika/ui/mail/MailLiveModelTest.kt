package fr.qwartz.mika.ui.mail

import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.WorkSteps
import fr.qwartz.mika.data.moi.Work
import fr.qwartz.mika.data.moi.mail.DraftPreview
import fr.qwartz.mika.data.moi.mail.DraftStates
import fr.qwartz.mika.data.moi.mail.HerMark
import fr.qwartz.mika.data.moi.mail.MailDraft
import fr.qwartz.mika.data.moi.mail.MailFolder
import fr.qwartz.mika.data.moi.mail.MailFull
import fr.qwartz.mika.data.moi.mail.MailPerson
import fr.qwartz.mika.data.moi.mail.MailRow
import fr.qwartz.mika.data.moi.mail.MailView
import fr.qwartz.mika.data.moi.mail.MailWork
import fr.qwartz.mika.data.net.Topics
import fr.qwartz.mika.ui.shell.Load
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
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
 * Mail face au direct (ADR 0308), contre une fausse API : la liste relit ses boîtes sur tout `mail` ou `mail.drafts`,
 * sa page seulement si elle montre une boîte nommée (ou toutes tes réceptions), sans repasser en chargement, et jamais
 * sous une sélection — relue dès qu'elle se vide ; la liseuse relit le mail ouvert si sa boîte est nommée, où elle en
 * est s'il est nommé, les deux à une reconnexion ; son brouillon arrivé par le direct paraît, et se dit si on l'attendait.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class MailLiveModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val a = "pro:<a@x>"
    private val api = FakeMailApi().apply {
        inbox = (1..3).map { MailRow(ref = "pro:<$it@x>", box = "pro", folder = "INBOX", subject = "Mail $it", seen = false, date = 1_000L * (4 - it)) }.toMutableList()
        mails[a] = MailFull(ref = a, box = "pro", from = MailPerson("Léa", "lea@x.fr"), to = listOf(MailPerson("", "moi@atelier.fr")), subject = "Le devis", body = "Le devis de Léa.")
    }
    private val list by lazy { main.model { MailListViewModel(MailDeps(api)) } }
    private val reader by lazy { main.model { MailReaderViewModel(MailDeps(api, now = { 10_000L })) } }

    private val rows: List<String> get() = list.listing.valueOrNull!!.rows.map { it.ref }
    private val pageReads: Int get() = api.calls.count { it.startsWith("messages:") }

    private suspend fun <T> Flow<T>.next(): T? = withTimeoutOrNull(200) { first() }

    private fun clear() {
        api.calls.clear()
        api.boxesReads = 0
        api.messageReads.clear()
    }

    @Test fun `avant sa première lecture, la liste ne lit rien sur un signal`() = runTest {
        list.onLive(LiveSignal.of(Topics.MAIL to null))
        advanceUntilIdle()
        assertEquals(0, api.boxesReads)
        assertEquals(0, pageReads)
    }

    @Test fun `toutes tes réceptions - un mail d'une boîte relit ses boîtes et la page`() = runTest {
        list.resume()
        advanceUntilIdle()
        clear()
        list.onLive(LiveSignal.of(Topics.MAIL to setOf("perso")))
        assertEquals(1, api.boxesReads)
        // la page, et ce qui attend une réponse (sa puce)
        assertEquals(2, pageReads)
    }

    @Test fun `une boîte affichée ne relit sa page que si elle est nommée - ses boîtes, toujours`() = runTest {
        list.resume()
        advanceUntilIdle()
        list.showView(MailView.Folder("pro", "INBOX"))
        advanceUntilIdle()
        clear()
        list.onLive(LiveSignal.of(Topics.MAIL to setOf("perso")))
        assertEquals(1, api.boxesReads)
        assertEquals(0, pageReads)
        list.onLive(LiveSignal.of(Topics.MAIL to setOf("pro")))
        assertTrue(pageReads > 0)
        // ses brouillons : ses boîtes (le bandeau), pas la page
        clear()
        list.onLive(LiveSignal.of(Topics.MAIL_DRAFTS to setOf("pro")))
        assertEquals(1, api.boxesReads)
        assertEquals(0, pageReads)
    }

    @Test fun `un mail qui arrive paraît en tête, sans que la liste repasse en chargement`() = runTest {
        list.resume()
        advanceUntilIdle()
        api.inbox.add(0, MailRow(ref = "pro:<new@x>", box = "pro", folder = "INBOX", subject = "Nouveau", seen = false, date = 9_000))
        api.hold("messages")
        launch { list.onLive(LiveSignal.of(Topics.MAIL to setOf("pro"))) }
        advanceUntilIdle()
        assertTrue("la liste montrée reste pendant la lecture", list.listing is Load.Ready)
        assertEquals(3, rows.size)
        api.release("messages")
        advanceUntilIdle()
        assertEquals("pro:<new@x>", rows.first())
        assertEquals(4, rows.size)
    }

    @Test fun `sous une sélection, la liste ne bouge pas - elle se relit dès que plus rien n'est coché`() = runTest {
        list.resume()
        advanceUntilIdle()
        list.toggle(list.listing.valueOrNull!!.rows.first(), "lecture seule")
        api.inbox.add(0, MailRow(ref = "pro:<new@x>", box = "pro", folder = "INBOX", subject = "Nouveau", seen = false, date = 9_000))
        clear()
        list.onLive(LiveSignal.of(Topics.MAIL to setOf("pro")))
        advanceUntilIdle()
        assertEquals(0, pageReads)
        assertEquals(1, api.boxesReads)
        assertEquals(3, rows.size)
        list.clearSelection()
        advanceUntilIdle()
        assertTrue(pageReads > 0)
        assertEquals("pro:<new@x>", rows.first())
    }

    @Test fun `la liseuse relit le mail ouvert si sa boîte est nommée - rien pour une autre`() = runTest {
        reader.open(a, "v1")
        advanceUntilIdle()
        clear()
        reader.onLive(LiveSignal.of(Topics.MAIL to setOf("perso")), "Sa réponse est arrivée.")
        assertTrue(api.messageReads.isEmpty())
        assertTrue(api.calls.isEmpty())
        // lu ailleurs : la liseuse le montre lu, sans repasser en chargement
        api.mails[a] = api.mails[a]!!.copy(seen = true)
        reader.onLive(LiveSignal.of(Topics.MAIL to setOf("pro")), "Sa réponse est arrivée.")
        advanceUntilIdle()
        assertEquals(listOf(a), api.messageReads)
        assertTrue(reader.mail is Load.Ready)
        assertTrue(reader.full!!.seen)
    }

    @Test fun `une reconnexion relit le mail ouvert et où elle en est`() = runTest {
        reader.open(a, "v1")
        advanceUntilIdle()
        clear()
        reader.onLive(LiveSignal.RESYNC, "Sa réponse est arrivée.")
        advanceUntilIdle()
        assertEquals(listOf(a), api.messageReads)
        assertEquals(listOf("work:$a"), api.calls.filter { it.startsWith("work") })
    }

    @Test fun `son brouillon arrive par le direct - il paraît, et se dit parce qu'on l'attendait`() = runTest {
        api.mails[a] = api.mails[a]!!.copy(her = HerMark(asked = true), work = Work(WorkSteps.THINKING, "", 9_000, 8_000))
        reader.open(a, "v1")
        advanceUntilIdle()
        assertTrue(reader.watching)
        val d1 = MailDraft(
            id = "d1", box = "pro", state = DraftStates.WAITING, inReplyTo = a, decides = true, to = "Léa <lea@x.fr>",
            subject = "Re: Le devis", body = "Bonjour Léa.", preview = DraftPreview(digest = "dg1"),
        )
        api.drafts = listOf(d1)
        api.mails[a] = api.mails[a]!!.copy(her = HerMark(draft = "d1"), work = null)
        api.workResult = MoiApi.Result.Ok(MailWork(null, asked = false, draft = "d1"))
        // la trame de sa proposition : sa boîte, ses brouillons, ce mail
        reader.onLive(
            LiveSignal.of(Topics.MAIL to setOf("pro"), Topics.MAIL_DRAFTS to setOf("pro"), Topics.MAIL_WORK to setOf(a)),
            "Sa réponse est arrivée.",
        )
        advanceUntilIdle()
        assertEquals("d1", reader.draft?.id)
        assertNull(reader.work)
        assertFalse(reader.watching)
        assertEquals("Sa réponse est arrivée.", reader.said.next())
    }

    @Test fun `la boîte affichée n'est plus à toi - la liste revient à toutes les réceptions, sans « introuvable »`() = runTest {
        list.resume()
        advanceUntilIdle()
        list.showView(MailView.Folder("pro", "INBOX"))
        advanceUntilIdle()
        // son partage retiré : ses boîtes ne la disent plus
        api.boxes = api.boxes.copy(boxes = api.boxes.boxes.filter { it.key != "pro" })
        list.onLive(LiveSignal.of(Topics.MAIL to null))
        advanceUntilIdle()
        assertEquals(MailView.All, list.view)
        assertTrue(list.listing is Load.Ready)
    }

    @Test fun `le dossier affiché n'est plus dans sa boîte - retour à toutes les réceptions, un dossier encore là reste`() = runTest {
        val folders = listOf(MailFolder(name = "INBOX"), MailFolder(name = "Factures"))
        api.boxes = api.boxes.copy(boxes = api.boxes.boxes.map { if (it.key == "pro") it.copy(folders = folders) else it })
        list.resume()
        advanceUntilIdle()
        list.showView(MailView.Folder("pro", "Factures"))
        advanceUntilIdle()
        list.onLive(LiveSignal.of(Topics.MAIL to setOf("pro")))
        advanceUntilIdle()
        assertEquals(MailView.Folder("pro", "Factures"), list.view)
        api.boxes = api.boxes.copy(boxes = api.boxes.boxes.map { if (it.key == "pro") it.copy(folders = folders.take(1)) else it })
        list.onLive(LiveSignal.of(Topics.MAIL to setOf("pro")))
        advanceUntilIdle()
        assertEquals(MailView.All, list.view)
    }

    @Test fun `le mail ouvert d'une boîte qui n'est plus à toi - la liseuse revient à la liste`() = runTest {
        reader.open(a, "v1")
        advanceUntilIdle()
        api.boxes = api.boxes.copy(boxes = api.boxes.boxes.filter { it.key != "pro" })
        clear()
        reader.onLive(LiveSignal.of(Topics.MAIL to null), "Sa réponse est arrivée.")
        advanceUntilIdle()
        assertEquals(ReaderOrder.Back, reader.orders("v1").next())
        // le mail ne s'est pas relu (il dirait « introuvable »)
        assertTrue(api.messageReads.isEmpty())
        // une boîte encore là : la liseuse reste
        api.boxes = FakeMailApi().boxes
        reader.open(a, "v2")
        advanceUntilIdle()
        reader.onLive(LiveSignal.of(Topics.MAIL to null), "Sa réponse est arrivée.")
        advanceUntilIdle()
        assertNull(reader.orders("v2").next())
    }
}
