package fr.qwartz.mika.ui.teams

import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.teams.ConversationThread
import fr.qwartz.mika.data.moi.teams.Kinds
import fr.qwartz.mika.data.moi.teams.TeamsAccount
import fr.qwartz.mika.data.moi.teams.TeamsAccounts
import fr.qwartz.mika.data.moi.teams.TeamsMessage
import fr.qwartz.mika.data.moi.teams.TeamsQuote
import fr.qwartz.mika.ui.mail.MainDispatcherRule
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test

/**
 * Un fil de Teams contre une fausse API : la citation (ADR 0305, « Citer » de Teams mobile) — la carte posée au-dessus du
 * champ, discussion par discussion, son ×, l'envoi qui part avec `reply_to` puis la carte qui s'en va (une autre choisie
 * pendant l'envoi reste, un refus la garde), la clé d'envoi qui suit la citation, ce qui ne se cite pas ; et un appui
 * sur une citation reçue, qui mène au message cité quand il est chargé, sinon nulle part.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class TeamsThreadModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val karim = TeamsMessage(ref = "t1", author = "Karim Haddad", authorId = "8:k", at = 1_000, text = "La démo tourne ?")
    private val lea = TeamsMessage(ref = "t2", author = "Léa Martin", authorId = "8:l", at = 2_000, text = "Chez moi, oui.")
    private val mine = TeamsMessage(ref = "t3", author = "Adrien Moreau", authorId = "8:a", at = 3_000, text = "Je regarde.", own = true)

    private val api = FakeTeamsApi().apply {
        threads["19:lumen"] = ConversationThread(key = "19:lumen", account = "principal", title = "Projet Lumen", kind = Kinds.GROUP, messages = listOf(karim, lea, mine))
        threads["19:marc"] = ConversationThread(
            key = "19:marc", account = "principal", title = "Marc Delmas", kind = Kinds.DM,
            messages = listOf(TeamsMessage(ref = "m1", author = "Marc Delmas", authorId = "8:m", at = 1_500, text = "Salut")),
        )
        threads["19:annonces"] = ConversationThread(key = "19:annonces", account = "principal", title = "Annonces", kind = Kinds.CHANNEL, messages = listOf(karim))
    }
    private val vm by lazy { main.model { TeamsThreadViewModel(TeamsDeps(api, now = { 10_000L })) } }

    private fun open(key: String) {
        vm.open(key, "Sa réponse est arrivée.")
    }

    // ── Citer ──

    @Test fun `citer pose la carte, l'envoi part avec reply_to, puis la carte s'en va`() = runTest {
        open("19:lumen")
        advanceUntilIdle()
        vm.cite(karim)
        assertEquals("t1", vm.citing?.ref)
        vm.type("Oui, depuis ce matin.")
        vm.send()
        advanceUntilIdle()
        val sent = api.sends.single()
        assertEquals(listOf("19:lumen", "Oui, depuis ce matin.", "t1"), listOf(sent.conversation, sent.body, sent.replyTo))
        assertNull(vm.citing)
        assertEquals("", vm.text)
        // le message suivant ne cite plus rien
        vm.type("Et la tienne ?")
        vm.send()
        advanceUntilIdle()
        assertEquals("", api.sends.last().replyTo)
    }

    @Test fun `le × retire la carte, le message part sans citation`() = runTest {
        open("19:lumen")
        advanceUntilIdle()
        vm.cite(lea)
        vm.uncite()
        assertNull(vm.citing)
        vm.type("ok")
        vm.send()
        advanceUntilIdle()
        assertEquals("", api.sends.single().replyTo)
    }

    @Test fun `une autre citation remplace la première, et on cite aussi ses propres messages`() = runTest {
        open("19:lumen")
        advanceUntilIdle()
        vm.cite(karim)
        vm.cite(mine)
        assertEquals("t3", vm.citing?.ref)
    }

    @Test fun `la citation est par discussion, comme ce que tu tapes`() = runTest {
        open("19:lumen")
        advanceUntilIdle()
        vm.cite(karim)
        vm.type("Oui")
        open("19:marc")
        advanceUntilIdle()
        assertNull(vm.citing)
        assertEquals("", vm.text)
        // un tête-à-tête se cite aussi
        vm.cite(api.threads["19:marc"]!!.messages.single())
        assertEquals("m1", vm.citing?.ref)
        open("19:lumen")
        advanceUntilIdle()
        assertEquals("t1", vm.citing?.ref)
        assertEquals("Oui", vm.text)
    }

    @Test fun `un envoi refusé garde la carte avec ton texte`() = runTest {
        api.sendResult = MoiApi.Result.Failed(MoiError(400, "Il reste des passages à compléter."))
        open("19:lumen")
        advanceUntilIdle()
        vm.cite(karim)
        vm.type("Oui")
        vm.send()
        advanceUntilIdle()
        assertEquals("t1", vm.citing?.ref)
        assertEquals("Oui", vm.text)
    }

    @Test fun `une citation choisie pendant l'envoi reste pour le message suivant`() = runTest {
        open("19:lumen")
        advanceUntilIdle()
        vm.cite(karim)
        vm.type("Oui")
        api.hold("send")
        vm.send()
        // l'envoi en route : tu en cites un autre
        vm.cite(lea)
        api.release("send")
        advanceUntilIdle()
        assertEquals("t1", api.sends.single().replyTo)
        assertEquals("t2", vm.citing?.ref)
    }

    @Test fun `la clé d'envoi suit la citation, même texte et autre citation font un autre envoi`() = runTest {
        // une coupure du réseau garde la clé du même geste ; changer la citation en fait un autre
        api.sendResult = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        open("19:lumen")
        advanceUntilIdle()
        vm.cite(karim)
        vm.type("Oui")
        vm.send()
        advanceUntilIdle()
        vm.send()
        advanceUntilIdle()
        assertEquals(api.sends[0].key, api.sends[1].key)
        vm.uncite()
        vm.send()
        advanceUntilIdle()
        assertNotEquals(api.sends[1].key, api.sends[2].key)
        assertEquals("", api.sends[2].replyTo)
    }

    @Test fun `ne se citent pas un message d'un canal ni un message sans référence`() = runTest {
        open("19:annonces")
        advanceUntilIdle()
        vm.cite(karim)
        assertNull(vm.citing)
        open("19:lumen")
        advanceUntilIdle()
        vm.cite(karim.copy(ref = ""))
        assertNull(vm.citing)
    }

    @Test fun `sur un compte qu'on ne te partage qu'en lecture, rien ne se cite`() = runTest {
        api.accounts = TeamsAccounts(accounts = listOf(TeamsAccount(key = "principal", name = "Atelier", level = Levels.READ, ownerName = "Adrien Moreau")))
        open("19:lumen")
        advanceUntilIdle()
        vm.cite(karim)
        assertNull(vm.citing)
    }

    // ── Aller au message cité ──

    @Test fun `un appui sur une citation mène au message cité quand il est chargé, sinon nulle part`() = runTest {
        open("19:lumen")
        advanceUntilIdle()
        vm.jumpTo(TeamsQuote(author = "Karim Haddad", preview = "La démo tourne ?", ref = "t1"))
        val first = vm.jump!!
        assertEquals("t1", first.ref)
        vm.jumped(first)
        assertNull(vm.jump)
        // pas chez Mika (`ref` vide), ou pas parmi les messages chargés : rien
        vm.jumpTo(TeamsQuote(author = "Karim Haddad", preview = "Un vieux message", ref = ""))
        assertNull(vm.jump)
        vm.jumpTo(TeamsQuote(author = "Karim Haddad", preview = "Plus ancien", ref = "t0"))
        assertNull(vm.jump)
        // deux appuis sur la même citation : deux allers
        vm.jumpTo(TeamsQuote(ref = "t2"))
        val one = vm.jump!!
        vm.jumped(one)
        vm.jumpTo(TeamsQuote(ref = "t2"))
        assertNotEquals(one, vm.jump)
        // un geste déjà remplacé ne retire pas le suivant
        vm.jumped(one)
        assertEquals("t2", vm.jump?.ref)
    }

    @Test fun `une autre discussion ouverte oublie où le fil devait aller`() = runTest {
        open("19:lumen")
        advanceUntilIdle()
        vm.jumpTo(TeamsQuote(ref = "t1"))
        open("19:marc")
        assertNull(vm.jump)
    }
}
