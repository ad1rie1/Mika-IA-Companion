package fr.qwartz.mika.ui.teams

import fr.qwartz.mika.data.moi.CorrectWords
import fr.qwartz.mika.data.moi.Corrected
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.teams.ConversationThread
import fr.qwartz.mika.data.moi.teams.Kinds
import fr.qwartz.mika.data.moi.teams.TeamsMessage
import fr.qwartz.mika.ui.mail.MainDispatcherRule
import fr.qwartz.mika.ui.shell.CorrectNotice
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
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
 * « Corriger » dans le champ d'un fil (ADR 0307), contre une fausse API : le texte corrigé remplace le tien, le message
 * dit combien de fautes et « Annuler » te le rend (tant que le champ contient le texte corrigé) ; aucune faute, un champ
 * vide, aucun modèle ; tu as continué d'écrire pendant l'appel, ou ouvert une autre discussion : rien n'est posé ; un
 * refus dit tel quel ; un appel à la fois, « Correction… » le temps qu'il dure.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class TeamsCorrectModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val api = FakeTeamsApi().apply {
        threads["19:marc"] = ConversationThread(
            key = "19:marc", account = "principal", title = "Marc Delmas", kind = Kinds.DM,
            messages = listOf(TeamsMessage(ref = "m1", author = "Marc Delmas", authorId = "8:m", at = 1_500, text = "Tu viens demain ?")),
        )
        threads["19:lumen"] = ConversationThread(key = "19:lumen", account = "principal", title = "Projet Lumen", kind = Kinds.GROUP)
        correctResult = { text -> MoiApi.Result.Ok(if (text == "je viens a 9h") Corrected("Je viens à 9 h.", 3) else Corrected(text, 0)) }
    }
    private val vm by lazy { main.model { TeamsThreadViewModel(TeamsDeps(api, now = { 10_000L })) } }

    private val words = CorrectWords(
        empty = "Rien à corriger : le champ est vide.",
        none = "Aucune faute : ton texte reste tel quel.",
        moved = "Tu as continué d'écrire : la correction n'a pas été posée.",
        off = "Aucun modèle ne corrige : un opérateur en choisit un dans Réglages › Intelligence.",
        fixed = { n -> if (n <= 1) "$n faute corrigée." else "$n fautes corrigées." },
    )

    private suspend fun <T> Flow<T>.next(): T? = withTimeoutOrNull(200) { first() }

    private suspend fun said(): CorrectNotice? = vm.corrector.notices.next()

    private fun open(key: String) = vm.open(key, "Sa réponse est arrivée.")

    @Test fun `le texte corrigé remplace le tien, et Annuler te le rend`() = runTest {
        open("19:marc")
        advanceUntilIdle()
        vm.type("je viens a 9h")
        vm.correct(on = true, words)
        advanceUntilIdle()
        assertEquals(listOf("je viens a 9h"), api.corrections)
        assertEquals("Je viens à 9 h.", vm.text)
        val n = said()!!
        assertEquals("3 fautes corrigées.", n.text)
        n.undo!!.invoke()
        assertEquals("je viens a 9h", vm.text)
        // la discussion garde ce qui est revenu
        open("19:lumen")
        advanceUntilIdle()
        open("19:marc")
        advanceUntilIdle()
        assertEquals("je viens a 9h", vm.text)
    }

    @Test fun `Annuler ne défait rien de ce que tu as écrit depuis`() = runTest {
        open("19:marc")
        advanceUntilIdle()
        vm.type("je viens a 9h")
        vm.correct(on = true, words)
        advanceUntilIdle()
        val n = said()!!
        vm.type("Je viens à 9 h. Et toi ?")
        n.undo!!.invoke()
        assertEquals("Je viens à 9 h. Et toi ?", vm.text)
    }

    @Test fun `aucune faute - ton texte reste, sans Annuler`() = runTest {
        open("19:marc")
        advanceUntilIdle()
        vm.type("Oui, à demain.")
        vm.correct(on = true, words)
        advanceUntilIdle()
        assertEquals("Oui, à demain.", vm.text)
        val n = said()!!
        assertEquals("Aucune faute : ton texte reste tel quel.", n.text)
        assertNull(n.undo)
    }

    @Test fun `un champ vide ou aucun modèle - rien ne part, on dit pourquoi`() = runTest {
        open("19:marc")
        advanceUntilIdle()
        vm.type("   ")
        vm.correct(on = true, words)
        assertEquals("Rien à corriger : le champ est vide.", said()?.text)
        vm.type("je viens a 9h")
        vm.correct(on = false, words)
        assertEquals("Aucun modèle ne corrige : un opérateur en choisit un dans Réglages › Intelligence.", said()?.text)
        advanceUntilIdle()
        assertTrue(api.corrections.isEmpty())
        assertEquals("je viens a 9h", vm.text)
    }

    @Test fun `tu as continué d'écrire pendant l'appel - rien n'est posé`() = runTest {
        open("19:marc")
        advanceUntilIdle()
        vm.type("je viens a 9h")
        api.hold("correct")
        vm.correct(on = true, words)
        assertTrue(vm.correcting)
        vm.type("je viens a 9h, ok ?")
        api.release("correct")
        advanceUntilIdle()
        assertFalse(vm.correcting)
        assertEquals("je viens a 9h, ok ?", vm.text)
        assertEquals("Tu as continué d'écrire : la correction n'a pas été posée.", said()?.text)
    }

    @Test fun `une autre discussion ouverte pendant l'appel - rien ne se pose ni ici ni là`() = runTest {
        open("19:marc")
        advanceUntilIdle()
        vm.type("je viens a 9h")
        api.hold("correct")
        vm.correct(on = true, words)
        open("19:lumen")
        advanceUntilIdle()
        // la correction de l'autre discussion ne retient pas le bouton de celle-ci
        assertFalse(vm.correcting)
        api.release("correct")
        advanceUntilIdle()
        assertEquals("", vm.text)
        assertNull(said())
        open("19:marc")
        advanceUntilIdle()
        assertEquals("je viens a 9h", vm.text)
    }

    @Test fun `un appel à la fois, Correction… le temps qu'il dure`() = runTest {
        open("19:marc")
        advanceUntilIdle()
        vm.type("je viens a 9h")
        api.hold("correct")
        vm.correct(on = true, words)
        vm.correct(on = true, words)
        assertTrue(vm.correcting)
        api.release("correct")
        advanceUntilIdle()
        assertFalse(vm.correcting)
        assertEquals(1, api.corrections.size)
    }

    @Test fun `un refus se dit tel que le serveur le donne, ton texte reste`() = runTest {
        api.correctResult = { MoiApi.Result.Failed(MoiError(422, "La correction changeait trop ton texte : rien n'a été changé.")) }
        open("19:marc")
        advanceUntilIdle()
        vm.type("je viens a 9h")
        vm.correct(on = true, words)
        advanceUntilIdle()
        assertEquals("je viens a 9h", vm.text)
        val n = said()
        assertNotNull(n)
        assertEquals("La correction changeait trop ton texte : rien n'a été changé.", n!!.text)
        assertNull(n.undo)
        assertFalse(vm.correcting)
    }
}
