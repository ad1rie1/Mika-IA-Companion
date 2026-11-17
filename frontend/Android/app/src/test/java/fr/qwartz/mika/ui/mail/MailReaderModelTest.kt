package fr.qwartz.mika.ui.mail

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.mail.DraftPreview
import fr.qwartz.mika.data.moi.mail.DraftStates
import fr.qwartz.mika.data.moi.mail.MailDone
import fr.qwartz.mika.data.moi.mail.MailDraft
import fr.qwartz.mika.data.moi.mail.MailFull
import fr.qwartz.mika.data.moi.mail.MailPerson
import fr.qwartz.mika.ui.shell.Load
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.withTimeoutOrNull
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test

/**
 * La liseuse et la page d'un brouillon, des modèles pour tous les mails de la session : un geste qui répond après
 * qu'on a changé de mail ne pose rien sur le suivant (R2-05), et un ordre de retour ne referme que l'écran de la visite
 * où son geste a commencé — jamais le même mail, ou le même brouillon, rouvert plus tard (R2-07).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class MailReaderModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val a = "pro:<a@x>"
    private val b = "pro:<b@x>"
    private val api = FakeMailApi().apply {
        mails[a] = MailFull(ref = a, box = "pro", from = MailPerson("Léa", "lea@x.fr"), subject = "Le devis", body = "Le devis de Léa.")
        mails[b] = MailFull(ref = b, box = "pro", from = MailPerson("Paul", "paul@x.fr"), subject = "La facture", body = "La facture de Paul.")
        drafts = listOf(
            MailDraft(id = "d1", box = "pro", state = DraftStates.WAITING, inReplyTo = a, decides = true, subject = "Re: Le devis", preview = DraftPreview(digest = "dg1")),
        )
    }
    private val reader by lazy { main.model { MailReaderViewModel(MailDeps(api)) } }

    private suspend fun <T> Flow<T>.next(): T? = withTimeoutOrNull(200) { first() }

    // ── R2-05 ──

    @Test fun `« Suivre » qui répond après qu'on est passé à un autre mail ne remet pas l'ancien à l'écran`() = runTest {
        reader.open(a, "v1")
        advanceUntilIdle()
        api.hold("tidy")
        reader.tidy("flag")
        // ← tout de suite, puis B
        reader.open(b, "v2")
        advanceUntilIdle()
        api.release("tidy")
        advanceUntilIdle()
        val shown = (reader.mail as Load.Ready).value
        assertEquals(b, shown.ref)
        assertEquals("La facture de Paul.", shown.body)
        assertFalse(shown.flagged)
    }

    @Test fun `« Préremplir » qui trouve son brouillon après qu'on a changé de mail ne le montre pas sur l'autre et n'ouvre rien`() = runTest {
        api.prefillResult = MoiApi.Result.Ok(MailDone(ok = true, draft = "d1", message = "Son brouillon attend déjà."))
        reader.open(a, "v1")
        advanceUntilIdle()
        api.hold("prefill")
        reader.prefill("Elle va l'écrire.")
        reader.open(b, "v2")
        advanceUntilIdle()
        api.release("prefill")
        advanceUntilIdle()
        assertNull(reader.draft)
        assertFalse(reader.asked)
        assertNull(reader.orders("v2").next())
    }

    @Test fun `« Préremplir » demandé sur A ne fait pas guetter B`() = runTest {
        api.prefillResult = MoiApi.Result.Ok(MailDone(ok = true, asked = true, message = "Elle l'écrira."))
        reader.open(a, "v1")
        advanceUntilIdle()
        api.hold("prefill")
        reader.prefill("Elle va l'écrire.")
        reader.open(b, "v2")
        advanceUntilIdle()
        api.release("prefill")
        advanceUntilIdle()
        assertFalse(reader.asked)
    }

    @Test fun `« Préremplir » sur le mail à l'écran ouvre son brouillon`() = runTest {
        api.prefillResult = MoiApi.Result.Ok(MailDone(ok = true, draft = "d1", message = "Son brouillon attend déjà."))
        reader.open(a, "v1")
        advanceUntilIdle()
        reader.prefill("Elle va l'écrire.")
        advanceUntilIdle()
        assertEquals("d1", reader.draft?.id)
        assertEquals(ReaderOrder.OpenDraft("d1"), reader.orders("v1").next())
    }

    // ── R2-07 ──

    @Test fun `archivé puis quitté avant la réponse - le même mail rouvert plus tard ne se referme pas`() = runTest {
        reader.open(a, "v1")
        advanceUntilIdle()
        api.hold("tidy")
        reader.tidy("archive")
        // ← aussitôt : personne n'écoute plus quand la réponse arrive
        api.release("tidy")
        advanceUntilIdle()
        // plus tard, depuis Archives ou la recherche : le même mail, une autre visite
        reader.open(a, "v2")
        advanceUntilIdle()
        assertNull(reader.orders("v2").next())
    }

    @Test fun `archivé sur l'écran resté là - il revient à la liste`() = runTest {
        reader.open(a, "v1")
        advanceUntilIdle()
        reader.tidy("archive")
        advanceUntilIdle()
        assertEquals(ReaderOrder.Back, reader.orders("v1").next())
    }

    @Test fun `un brouillon envoyé puis quitté - rouvert plus tard depuis « Partis », sa page reste`() = runTest {
        val drafts = main.model { MailDraftsViewModel(MailDeps(api)) }
        drafts.opened("p1")
        drafts.load()
        advanceUntilIdle()
        api.hold("send")
        drafts.send(api.drafts.single())
        api.release("send")
        advanceUntilIdle()
        drafts.opened("p2")
        assertNull(drafts.leave("p2").next())
    }

    @Test fun `un brouillon envoyé sur sa page restée là - elle revient en arrière`() = runTest {
        val drafts = main.model { MailDraftsViewModel(MailDeps(api)) }
        drafts.opened("p1")
        drafts.load()
        advanceUntilIdle()
        drafts.send(api.drafts.single())
        advanceUntilIdle()
        assertEquals(Unit, drafts.leave("p1").next())
    }
}
