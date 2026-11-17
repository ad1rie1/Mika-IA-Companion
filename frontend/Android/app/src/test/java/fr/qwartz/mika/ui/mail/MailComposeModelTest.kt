package fr.qwartz.mika.ui.mail

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.mail.DraftPreview
import fr.qwartz.mika.data.moi.mail.DraftStates
import fr.qwartz.mika.data.moi.mail.MailDone
import fr.qwartz.mika.data.moi.mail.MailDraft
import fr.qwartz.mika.data.moi.mail.MailFull
import fr.qwartz.mika.data.moi.mail.MailPerson
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.Load
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.withTimeoutOrNull
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Écrire, un modèle pour toutes les écritures de la session : ce qui répond tard (un chargement, « Préremplir », un
 * envoi) ne pose rien dans une écriture ouverte depuis (R2-01, R2-03) ; une réponse partie de son brouillon ne part
 * pas une seconde fois (R2-02) ; un envoi refusé se dit en toast, même l'écran quitté (R2-04).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class MailComposeModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val a = "pro:<a@x>"
    private val b = "pro:<b@x>"
    private val api = FakeMailApi().apply {
        mails[a] = MailFull(ref = a, box = "pro", from = MailPerson("Léa", "lea@x.fr"), to = listOf(MailPerson("", "moi@atelier.fr")), subject = "Le devis")
        mails[b] = MailFull(ref = b, box = "pro", from = MailPerson("Paul", "paul@x.fr"), to = listOf(MailPerson("", "moi@atelier.fr")), subject = "La facture")
    }
    private val notices = MailNotices()
    private val unsent = UnsentMails()
    private val vm by lazy { main.model { MailComposeViewModel(MailDeps(api, unsent = unsent, notices = notices)) } }

    private val replyA = Route.MailCompose("reply", ref = a)
    private val replyB = Route.MailCompose("reply", ref = b)
    private val fresh = Route.MailCompose()

    private val herDraft = MailDraft(
        id = "d1", box = "pro", state = DraftStates.WAITING, inReplyTo = a, decides = true,
        to = "Léa <lea@x.fr>", subject = "Re: Le devis", body = "Bonjour Léa, le devis suit.", quote = true,
        preview = DraftPreview(digest = "dg1"),
    )

    private suspend fun <T> Flow<T>.next(): T? = withTimeoutOrNull(200) { first() }

    private fun send() = vm.send(
        notAnAddress = { "« $it » n'est pas une adresse." },
        notSent = { reason, left -> "Ton mail n'est pas parti : $reason" + if (left) " (il t'attend)" else "" },
    )

    /** Une réponse à A, son brouillon repris par « Préremplir » (il attend). */
    private suspend fun TestScope.replyFromHerDraft() {
        api.drafts = listOf(herDraft)
        api.prefillResult = MoiApi.Result.Ok(MailDone(ok = true, draft = "d1", message = "Son brouillon attend déjà."))
        vm.prepare(replyA, "v1")
        advanceUntilIdle()
        vm.prefill("Elle va l'écrire.", "Son brouillon est repris.")
        advanceUntilIdle()
        assertEquals("d1", vm.fromDraft)
        assertEquals("Son brouillon est repris.", notices.flow.next())
    }

    // ── R2-01 ──

    @Test fun `une réponse quittée qui finit de charger ne touche pas au mail neuf ouvert ensuite`() = runTest {
        // tu réponds à A ; sa boîte tarde (le mail se complète sur l'IMAP)
        api.hold("message:$a")
        vm.prepare(replyA, "v1")
        assertTrue(vm.setup is Load.Loading)
        // rien n'est tapé : ← sort sans rien demander, puis « Écrire », ta boîte, À : Paul, objet « Facture »
        vm.keepUnsent("v1")
        vm.prepare(fresh, "v2")
        advanceUntilIdle()
        assertTrue(vm.setup is Load.Ready)
        vm.chooseFrom("perso")
        vm.type(RecipientField.TO, "paul@x.fr,")
        vm.editSubject("Facture")
        // le chargement de A arrive : rien ne change dans le mail neuf
        api.release("message:$a")
        advanceUntilIdle()
        assertEquals("perso", vm.from)
        assertEquals(listOf("paul@x.fr"), vm.to.map { it.address })
        assertTrue(vm.cc.isEmpty())
        assertEquals("Facture", vm.subject)
        assertNull(vm.original)
        assertEquals(fresh, vm.route)
    }

    @Test fun `la réponse à B ouverte après celle à A ne reçoit ni Léa, ni l'objet de A`() = runTest {
        api.hold("message:$a")
        vm.prepare(replyA, "v1")
        vm.keepUnsent("v1")
        vm.prepare(replyB, "v2")
        advanceUntilIdle()
        api.release("message:$a")
        advanceUntilIdle()
        assertEquals(listOf("paul@x.fr"), vm.to.map { it.address })
        assertEquals("Re: La facture", vm.subject)
        assertEquals(b, vm.original?.ref)
    }

    @Test fun `réessayer pendant un chargement ne double personne`() = runTest {
        api.hold("message:$a")
        vm.prepare(replyA, "v1")
        vm.retry()
        vm.retry()
        api.release("message:$a")
        advanceUntilIdle()
        assertEquals(listOf("lea@x.fr"), vm.to.map { it.address })
    }

    @Test fun `Préremplir qui répond après qu'on a quitté la réponse ne pose son brouillon nulle part`() = runTest {
        api.drafts = listOf(herDraft)
        api.prefillResult = MoiApi.Result.Ok(MailDone(ok = true, draft = "d1", message = "Son brouillon attend déjà."))
        vm.prepare(replyA, "v1")
        advanceUntilIdle()
        api.hold("prefill")
        vm.prefill("Elle va l'écrire.", "Son brouillon est repris.")
        // ← (rien de tapé), puis la réponse à B
        vm.keepUnsent("v1")
        vm.prepare(replyB, "v2")
        advanceUntilIdle()
        vm.editBody("Merci Paul")
        api.release("prefill")
        advanceUntilIdle()
        assertEquals("Merci Paul", vm.body)
        assertEquals("", vm.fromDraft)
        assertEquals(listOf("paul@x.fr"), vm.to.map { it.address })
        assertEquals("Re: La facture", vm.subject)
        assertFalse(vm.prefilling)
    }

    // ── R2-02 ──

    @Test fun `son brouillon déjà parti - ta version retouchée ne part pas en seconde réponse`() = runTest {
        replyFromHerDraft()
        // envoyé une première fois, réponse perdue ; ou envoyé d'ailleurs par l'autre propriétaire
        api.drafts = listOf(herDraft.copy(state = DraftStates.SENT, preview = null))
        vm.editBody("Bonjour Léa, le devis suit (corrigé).")
        send()
        advanceUntilIdle()
        assertTrue(api.calls.none { it.startsWith("reply") || it.startsWith("draftSend") || it.startsWith("draftEdit") })
        assertEquals("Son brouillon est déjà parti.", vm.problem)
        assertEquals("Ton mail n'est pas parti : Son brouillon est déjà parti.", notices.flow.next())
    }

    @Test fun `son brouillon approuvé ou en échec - rien de plus ne part`() = runTest {
        replyFromHerDraft()
        for (state in listOf(DraftStates.APPROVED, DraftStates.FAILED)) {
            api.drafts = listOf(herDraft.copy(state = state, preview = null))
            send()
            advanceUntilIdle()
            assertTrue(api.calls.none { it.startsWith("reply") || it.startsWith("draftSend") })
            assertTrue(vm.problem.isNotBlank())
        }
    }

    @Test fun `ses brouillons illisibles (le réseau) - rien ne part, et ce n'est pas « rien n'est parti »`() = runTest {
        replyFromHerDraft()
        api.draftsFail = MoiError(0, MoiError.NETWORK)
        send()
        advanceUntilIdle()
        assertTrue(api.calls.none { it.startsWith("reply") || it.startsWith("draftSend") })
        assertEquals(MoiError.NETWORK, vm.problem)
    }

    @Test fun `son brouillon refusé ou plus là - ta réponse part comme une autre`() = runTest {
        replyFromHerDraft()
        api.drafts = listOf(herDraft.copy(state = DraftStates.REFUSED, preview = null))
        send()
        advanceUntilIdle()
        assertTrue("reply:$a" in api.calls)
        assertEquals("Parti.", notices.flow.next())
    }

    @Test fun `son brouillon qui attend - ta version passe par lui`() = runTest {
        replyFromHerDraft()
        vm.editBody("Bonjour Léa, le devis suit (corrigé).")
        send()
        advanceUntilIdle()
        assertEquals(listOf("draftEdit:d1", "draftSend:d1"), api.calls.filter { it.startsWith("draft") && it != "drafts" })
        assertTrue(api.calls.none { it.startsWith("reply") })
    }

    // ── R2-03 ──

    @Test fun `un envoi quitté ne referme pas l'écriture ouverte ensuite, et ne la retient pas`() = runTest {
        vm.prepare(fresh, "v1")
        advanceUntilIdle()
        vm.type(RecipientField.TO, "paul@x.fr,")
        vm.editSubject("Facture")
        vm.editBody("Voici.")
        api.hold("send")
        send()
        assertTrue(vm.sending)
        // ← pendant l'envoi : rien n'est gardé pour l'instant (son issue décide)
        vm.keepUnsent("v1")
        assertNull(unsent.take(fresh))
        // plus tard, « Écrire » : la même route, une autre visite
        vm.prepare(fresh, "v2")
        assertFalse(vm.sending)
        advanceUntilIdle()
        api.release("send")
        advanceUntilIdle()
        assertNull(vm.finished("v2").next())
        assertEquals("Parti.", notices.flow.next())
        assertEquals("", vm.subject)
    }

    @Test fun `parti, l'écran de son envoi revient en arrière`() = runTest {
        vm.prepare(fresh, "v1")
        advanceUntilIdle()
        vm.type(RecipientField.TO, "paul@x.fr,")
        vm.editSubject("Facture")
        vm.editBody("Voici.")
        send()
        advanceUntilIdle()
        assertNotNull(vm.finished("v1").next())
        assertFalse(vm.touched)
    }

    // ── R2-04 ──

    @Test fun `un envoi refusé se dit en toast, et sous le formulaire`() = runTest {
        api.sendResult = MoiApi.Result.Failed(MoiError(400, "Cci : « pa » n'est pas une adresse."))
        vm.prepare(fresh, "v1")
        advanceUntilIdle()
        vm.type(RecipientField.TO, "paul@x.fr,")
        vm.editSubject("Facture")
        vm.editBody("Voici.")
        send()
        advanceUntilIdle()
        assertEquals("Ton mail n'est pas parti : Cci : « pa » n'est pas une adresse.", notices.flow.next())
        assertEquals("Cci : « pa » n'est pas une adresse.", vm.problem)
        assertFalse(vm.sending)
    }

    @Test fun `un envoi refusé après qu'on a quitté son écran se dit quand même, et ce qui était écrit attend`() = runTest {
        api.sendResult = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        vm.prepare(fresh, "v1")
        advanceUntilIdle()
        vm.type(RecipientField.TO, "paul@x.fr,")
        vm.editSubject("Facture")
        vm.editBody("Voici.")
        api.hold("send")
        send()
        // une notification touchée remplace la pile ; une réponse s'ouvre plus tard
        vm.keepUnsent("v1")
        vm.prepare(replyB, "v2")
        advanceUntilIdle()
        api.release("send")
        advanceUntilIdle()
        assertEquals("Ton mail n'est pas parti : ${MoiError.NETWORK} (il t'attend)", notices.flow.next())
        // le refus ne s'affiche pas dans la réponse ouverte
        assertEquals("", vm.problem)
        val kept = unsent.take(fresh)
        assertEquals("Facture", kept?.subject)
        assertEquals(listOf("paul@x.fr"), kept?.to?.map { it.address })
    }
}
