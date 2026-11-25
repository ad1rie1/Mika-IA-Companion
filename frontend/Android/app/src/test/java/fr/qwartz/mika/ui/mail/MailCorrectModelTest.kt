package fr.qwartz.mika.ui.mail

import fr.qwartz.mika.data.moi.Corrected
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.correctWords
import fr.qwartz.mika.data.moi.mail.MailFull
import fr.qwartz.mika.data.moi.mail.MailNotices
import fr.qwartz.mika.data.moi.mail.MailPerson
import fr.qwartz.mika.data.moi.mail.UnsentMails
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.CorrectNotice
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
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
 * « Corriger » dans « Écrire » (ADR 0307), contre une fausse API : le texte corrigé remplace le tien et « Annuler » te
 * le rend, en réponse comme dans un mail nouveau (où « Préremplir » n'est pas offert) ; tu as continué d'écrire : rien
 * n'est posé ; une autre écriture ouverte pendant l'appel, ou l'écran quitté : rien ne s'y pose, rien ne se dit, et la
 * correction de l'écriture d'avant ne retient pas le bouton de la suivante.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class MailCorrectModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val a = "pro:<a@x>"
    private val api = FakeMailApi().apply {
        mails[a] = MailFull(ref = a, box = "pro", from = MailPerson("Léa", "lea@x.fr"), to = listOf(MailPerson("", "moi@atelier.fr")), subject = "Le devis")
        correctResult = { text ->
            MoiApi.Result.Ok(if (text == "Bonjour Léa, voici le devis que tu ma demander.") Corrected("Bonjour Léa, voici le devis que tu m'as demandé.", 2) else Corrected(text, 0))
        }
    }
    private val vm by lazy { main.model { MailComposeViewModel(MailDeps(api, unsent = UnsentMails(), notices = MailNotices())) } }

    /** Les vrais mots de `strings.xml`. */
    private val words = correctWords
    private val typo = "Bonjour Léa, voici le devis que tu ma demander."
    private val fixed = "Bonjour Léa, voici le devis que tu m'as demandé."

    private suspend fun <T> Flow<T>.next(): T? = withTimeoutOrNull(200) { first() }

    private suspend fun said(): CorrectNotice? = vm.corrector.notices.next()

    @Test fun `en réponse - le texte corrigé remplace le tien, et Annuler te le rend`() = runTest {
        vm.prepare(Route.MailCompose("reply", ref = a), "v1")
        advanceUntilIdle()
        vm.editBody(typo)
        vm.correct(on = true, words)
        advanceUntilIdle()
        assertEquals(fixed, vm.body)
        assertTrue(vm.touched)
        val n = said()!!
        assertEquals("2 fautes corrigées.", n.text)
        n.undo!!.invoke()
        assertEquals(typo, vm.body)
        assertTrue("correct:$typo" in api.calls)
    }

    @Test fun `dans un mail nouveau aussi, et Annuler ne défait rien de ce que tu as écrit depuis`() = runTest {
        vm.prepare(Route.MailCompose(), "v1")
        advanceUntilIdle()
        assertFalse(vm.canPrefill)
        vm.editBody(typo)
        vm.correct(on = true, words)
        advanceUntilIdle()
        assertEquals(fixed, vm.body)
        val n = said()!!
        vm.editBody("$fixed\n\nAdrien")
        n.undo!!.invoke()
        assertEquals("$fixed\n\nAdrien", vm.body)
    }

    @Test fun `tu as continué d'écrire pendant l'appel - rien n'est posé`() = runTest {
        vm.prepare(Route.MailCompose(), "v1")
        advanceUntilIdle()
        vm.editBody(typo)
        api.hold("correct")
        vm.correct(on = true, words)
        assertTrue(vm.correcting)
        vm.editBody("$typo Merci")
        api.release("correct")
        advanceUntilIdle()
        assertFalse(vm.correcting)
        assertEquals("$typo Merci", vm.body)
        assertEquals("Tu as continué d'écrire : la correction n'a pas été posée.", said()?.text)
    }

    @Test fun `une autre écriture ouverte pendant l'appel - rien ne s'y pose, et son bouton n'est pas retenu`() = runTest {
        vm.prepare(Route.MailCompose(), "v1")
        advanceUntilIdle()
        vm.editBody(typo)
        api.hold("correct")
        vm.correct(on = true, words)
        vm.keepUnsent("v1")
        vm.prepare(Route.MailCompose("reply", ref = a), "v2")
        advanceUntilIdle()
        assertFalse(vm.correcting)
        // la même phrase tapée dans la nouvelle écriture n'attrape pas la correction de l'autre
        vm.editBody(typo)
        api.release("correct")
        advanceUntilIdle()
        assertEquals(typo, vm.body)
        assertNull(said())
    }

    @Test fun `l'écran quitté pendant l'appel - rien ne se pose`() = runTest {
        vm.prepare(Route.MailCompose(), "v1")
        advanceUntilIdle()
        vm.editBody(typo)
        api.hold("correct")
        vm.correct(on = true, words)
        vm.keepUnsent("v1")
        api.release("correct")
        advanceUntilIdle()
        assertEquals(typo, vm.body)
        assertNull(said())
    }

    @Test fun `aucun modèle - rien ne part, on dit pourquoi`() = runTest {
        vm.prepare(Route.MailCompose(), "v1")
        advanceUntilIdle()
        vm.editBody(typo)
        vm.correct(on = false, words)
        advanceUntilIdle()
        assertEquals("Aucun modèle ne corrige : un opérateur en choisit un dans Réglages › Intelligence.", said()?.text)
        assertTrue(api.calls.none { it.startsWith("correct:") })
        assertEquals(typo, vm.body)
    }
}
