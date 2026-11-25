package fr.qwartz.mika.ui.mail

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.Work
import fr.qwartz.mika.data.moi.WorkSteps
import fr.qwartz.mika.data.moi.mail.DraftPreview
import fr.qwartz.mika.data.moi.mail.DraftStates
import fr.qwartz.mika.data.moi.mail.HerMark
import fr.qwartz.mika.data.moi.mail.MailDone
import fr.qwartz.mika.data.moi.mail.MailDraft
import fr.qwartz.mika.data.moi.mail.MailFull
import fr.qwartz.mika.data.moi.mail.MailNotices
import fr.qwartz.mika.data.moi.mail.MailPerson
import fr.qwartz.mika.data.moi.mail.MailWork
import fr.qwartz.mika.data.net.Topics
import fr.qwartz.mika.ui.Route
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
 * « Préremplir avec Mika » suivi en direct dans Mail (ADR 0306), dans la liseuse et dans « Écrire », contre une fausse
 * API : sa ligne paraît aussitôt (elle s'y met, depuis maintenant) ; `/mail/work` relu sans relire le mail, quand le
 * direct (`mail.work`, ADR 0308) nomme ce mail — un autre mail nommé ne relit rien ; son brouillon arrivé paraît ici
 * (repris dans ta réponse si tu n'as rien écrit) ; plus rien de demandé ni d'en cours, la ligne s'en va ; ce qu'elle
 * prépare d'elle-même se suit aussi ; plus de plafond ; une relecture manquée, ou qui répond après qu'on a changé de mail.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class MailWorkModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val a = "pro:<a@x>"
    private val b = "pro:<b@x>"
    private val thinking = Work(WorkSteps.THINKING, "", since = 9_000, started = 8_000)
    private val tool = Work(WorkSteps.TOOL, "Lire un mail", since = 9_500, started = 8_000)
    private val herDraft = MailDraft(
        id = "d1", box = "pro", state = DraftStates.WAITING, inReplyTo = a, decides = true,
        to = "Léa <lea@x.fr>", subject = "Re: Le devis", body = "Bonjour Léa, le devis suit.", quote = true,
        preview = DraftPreview(digest = "dg1"),
    )
    private val api = FakeMailApi().apply {
        mails[a] = MailFull(ref = a, box = "pro", from = MailPerson("Léa", "lea@x.fr"), to = listOf(MailPerson("", "moi@atelier.fr")), subject = "Le devis", body = "Le devis de Léa.")
        mails[b] = MailFull(ref = b, box = "pro", from = MailPerson("Paul", "paul@x.fr"), to = listOf(MailPerson("", "moi@atelier.fr")), subject = "La facture", body = "La facture de Paul.")
    }
    private var clock = 10_000L
    private val notices = MailNotices()
    private val reader by lazy { main.model { MailReaderViewModel(MailDeps(api, now = { clock })) } }
    private val compose by lazy { main.model { MailComposeViewModel(MailDeps(api, notices = notices, now = { clock })) } }

    private val asked = "Demandé : elle s'y met tout de suite ; sa réponse arrivera ici."

    private suspend fun <T> Flow<T>.next(): T? = withTimeoutOrNull(200) { first() }

    /** Ce que le serveur dit de ce mail : demandée, et où elle en est. */
    private fun serverSays(ref: String, askedHere: Boolean, work: Work?) {
        api.mails[ref] = api.mails[ref]!!.copy(her = HerMark(asked = askedHere), work = work)
    }

    // ── La liseuse ──

    @Test fun `« Préremplir » réussi dans la liseuse - sa ligne paraît aussitôt, et le toast le dit`() = runTest {
        reader.open(a, "v1")
        advanceUntilIdle()
        assertNull(reader.work)
        assertFalse(reader.watching)
        reader.prefill(asked)
        advanceUntilIdle()
        assertTrue(reader.asked)
        assertEquals(Work(WorkSteps.WAITING, "", 10_000, 10_000), reader.work)
        assertTrue(reader.watching)
        assertEquals(asked, reader.said.next())
        // déjà demandée : ce que dit le serveur, tel quel
        api.prefillResult = MoiApi.Result.Ok(MailDone(ok = true, asked = true, message = "Elle y travaille déjà."))
        reader.prefill(asked)
        advanceUntilIdle()
        assertEquals("Elle y travaille déjà.", reader.said.next())
    }

    @Test fun `elle y travaille - seule sa ligne change, sans relire le mail ni ses brouillons`() = runTest {
        serverSays(a, askedHere = true, work = thinking)
        reader.open(a, "v1")
        advanceUntilIdle()
        assertEquals(thinking, reader.work)
        assertTrue(reader.watching)
        api.calls.clear()
        api.workResult = MoiApi.Result.Ok(MailWork(tool, asked = true))
        reader.readWork("Sa réponse est arrivée.")
        assertEquals(tool, reader.work)
        assertEquals(listOf("work:$a"), api.calls)
        assertTrue(reader.watching)
    }

    @Test fun `son brouillon arrivé paraît dans la liseuse, et on cesse de guetter`() = runTest {
        serverSays(a, askedHere = true, work = thinking)
        reader.open(a, "v1")
        advanceUntilIdle()
        api.drafts = listOf(herDraft)
        api.workResult = MoiApi.Result.Ok(MailWork(null, asked = false, draft = "d1"))
        reader.readWork("Sa réponse est arrivée.")
        assertEquals("d1", reader.draft?.id)
        assertFalse(reader.asked)
        assertNull(reader.work)
        assertFalse(reader.watching)
        assertEquals("Sa réponse est arrivée.", reader.said.next())
    }

    @Test fun `son brouillon annoncé mais ses brouillons illisibles - la relecture suivante le retrouvera`() = runTest {
        serverSays(a, askedHere = true, work = thinking)
        reader.open(a, "v1")
        advanceUntilIdle()
        api.draftsFail = MoiError(0, MoiError.NETWORK)
        api.workResult = MoiApi.Result.Ok(MailWork(null, asked = false, draft = "d1"))
        reader.readWork("Sa réponse est arrivée.")
        assertNull(reader.draft)
        assertTrue(reader.watching)
    }

    @Test fun `finie sans en rendre - la ligne s'en va et la demande s'oublie, un autre mail nommé ne relit rien`() = runTest {
        serverSays(a, askedHere = true, work = thinking)
        reader.open(a, "v1")
        advanceUntilIdle()
        api.workResult = MoiApi.Result.Ok(MailWork())
        reader.onLive(LiveSignal.of(Topics.MAIL_WORK to setOf(a)), "Sa réponse est arrivée.")
        assertFalse(reader.asked)
        assertNull(reader.work)
        assertFalse(reader.watching)
        api.calls.clear()
        reader.onLive(LiveSignal.of(Topics.MAIL_WORK to setOf(b)), "Sa réponse est arrivée.")
        assertTrue(api.calls.isEmpty())
    }

    @Test fun `ce qu'elle prépare d'elle-même se guette aussi, sans demande`() = runTest {
        serverSays(a, askedHere = false, work = thinking)
        reader.open(a, "v1")
        advanceUntilIdle()
        assertFalse(reader.asked)
        assertTrue(reader.watching)
        api.workResult = MoiApi.Result.Ok(MailWork(tool, asked = false))
        reader.readWork("Sa réponse est arrivée.")
        assertEquals(tool, reader.work)
    }

    @Test fun `plus de plafond - une heure après la demande, l'étape que le direct dit se suit encore`() = runTest {
        reader.open(a, "v1")
        advanceUntilIdle()
        reader.prefill(asked)
        advanceUntilIdle()
        clock += 60 * 60_000L
        api.calls.clear()
        api.workResult = MoiApi.Result.Ok(MailWork(tool, asked = true))
        reader.onLive(LiveSignal.of(Topics.MAIL_WORK to setOf(a)), "Sa réponse est arrivée.")
        assertEquals(listOf("work:$a"), api.calls)
        assertEquals(tool, reader.work)
        assertTrue(reader.watching)
    }

    @Test fun `une relecture manquée garde la ligne et attend la suivante`() = runTest {
        serverSays(a, askedHere = true, work = thinking)
        reader.open(a, "v1")
        advanceUntilIdle()
        api.workResult = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        reader.readWork("Sa réponse est arrivée.")
        assertEquals(thinking, reader.work)
        assertTrue(reader.watching)
    }

    @Test fun `une relecture qui répond après qu'on a changé de mail ne pose rien sur l'autre`() = runTest {
        serverSays(a, askedHere = true, work = thinking)
        reader.open(a, "v1")
        advanceUntilIdle()
        api.workResult = MoiApi.Result.Ok(MailWork(tool, asked = true))
        api.hold("work")
        launch { reader.readWork("Sa réponse est arrivée.") }
        // la relecture est partie pour A ; on passe à B avant sa réponse
        advanceUntilIdle()
        assertEquals(listOf("work:$a"), api.calls.filter { it.startsWith("work") })
        reader.open(b, "v2")
        advanceUntilIdle()
        api.release("work")
        advanceUntilIdle()
        assertEquals(b, reader.ref)
        assertNull(reader.work)
        assertFalse(reader.watching)
    }

    // ── Écrire ──

    @Test fun `« Préremplir » réussi dans Écrire - sa ligne paraît aussitôt, et le toast le dit`() = runTest {
        compose.prepare(Route.MailCompose("reply", ref = a), "v1")
        advanceUntilIdle()
        assertFalse(compose.watching)
        compose.prefill(asked, "Son brouillon est repris.")
        advanceUntilIdle()
        assertTrue(compose.asked)
        assertEquals(Work(WorkSteps.WAITING, "", 10_000, 10_000), compose.work)
        assertTrue(compose.watching)
        assertEquals(asked, notices.flow.next())
    }

    @Test fun `son brouillon arrivé est repris dans ta réponse si tu n'as rien écrit`() = runTest {
        compose.prepare(Route.MailCompose("reply", ref = a), "v1")
        advanceUntilIdle()
        compose.prefill(asked, "Son brouillon est repris.")
        advanceUntilIdle()
        notices.clear()
        api.drafts = listOf(herDraft)
        api.workResult = MoiApi.Result.Ok(MailWork(null, asked = false, draft = "d1"))
        compose.readWork("Sa proposition est arrivée.", "Elle attend dans ses brouillons.")
        assertEquals("d1", compose.fromDraft)
        assertEquals("Bonjour Léa, le devis suit.", compose.body)
        assertNull(compose.work)
        assertFalse(compose.watching)
        assertEquals("Sa proposition est arrivée.", notices.flow.next())
    }

    @Test fun `son brouillon arrivé pendant que tu écris - ta réponse reste, et c'est dit`() = runTest {
        compose.prepare(Route.MailCompose("reply", ref = a), "v1")
        advanceUntilIdle()
        compose.prefill(asked, "Son brouillon est repris.")
        advanceUntilIdle()
        notices.clear()
        compose.editBody("Je regarde et je reviens vers toi.")
        api.drafts = listOf(herDraft)
        api.workResult = MoiApi.Result.Ok(MailWork(null, asked = false, draft = "d1"))
        compose.readWork("Sa proposition est arrivée.", "Elle attend dans ses brouillons.")
        assertEquals("", compose.fromDraft)
        assertEquals("Je regarde et je reviens vers toi.", compose.body)
        assertFalse(compose.asked)
        assertFalse(compose.watching)
        assertEquals("Elle attend dans ses brouillons.", notices.flow.next())
    }

    @Test fun `répondre à un mail qu'elle prépare déjà - sa ligne se suit dans Écrire aussi`() = runTest {
        serverSays(a, askedHere = true, work = thinking)
        compose.prepare(Route.MailCompose("reply", ref = a), "v1")
        advanceUntilIdle()
        assertEquals(thinking, compose.work)
        assertTrue(compose.watching)
        api.workResult = MoiApi.Result.Ok(MailWork(tool, asked = true))
        compose.readWork("Sa proposition est arrivée.", "Elle attend dans ses brouillons.")
        assertEquals(tool, compose.work)
        // un transfert ne la suit pas
        compose.prepare(Route.MailCompose("forward", ref = a), "v2")
        advanceUntilIdle()
        assertNull(compose.work)
        assertFalse(compose.watching)
    }
}
