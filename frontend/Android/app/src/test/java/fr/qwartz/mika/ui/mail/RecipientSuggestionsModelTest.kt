package fr.qwartz.mika.ui.mail

import fr.qwartz.mika.data.moi.contacts.ContactIdent
import fr.qwartz.mika.data.moi.contacts.ContactKinds
import fr.qwartz.mika.data.moi.contacts.ContactLine
import fr.qwartz.mika.data.moi.contacts.ContactRef
import fr.qwartz.mika.data.moi.contacts.ContactSource
import fr.qwartz.mika.data.moi.mail.MailPerson
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.contacts.FakeContactsApi
import fr.qwartz.mika.ui.shell.Load
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Écrire et ses destinataires proposés (la maquette validée `ecrans/contacts.js`, ADR 0298) : taper dans À, Cc ou Cci
 * propose tous tes contacts — une ligne par adresse, une adresse générique marquée et après les personnes —, ce qui est
 * déjà en puce n'est plus proposé, rien trouvé se dit ; « Écrire » depuis une fiche pose son adresse ; Retour arrière
 * dans un champ vide retire la dernière puce.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class RecipientSuggestionsModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val mail = FakeMailApi()
    private val directory = FakeContactsApi().apply {
        val lumen = ContactRef(3, "Lumen Conseil")
        contacts = mutableListOf(
            ContactLine(
                id = 3, kind = ContactKinds.ORG, name = "Lumen Conseil",
                sources = listOf(ContactSource("mail", "pro", "Atelier", 120)),
                identifiers = listOf(ContactIdent("domain", "lumen-conseil.fr"), ContactIdent("email", "noreply@lumen-conseil.fr")),
            ),
            ContactLine(
                id = 12, name = "Claire Dubois", title = "Cheffe de projet", organisation = lumen,
                sources = listOf(ContactSource("teams", label = "Teams", count = 64), ContactSource("mail", "pro", "Atelier", 23)),
                identifiers = listOf(ContactIdent("email", "c.dubois@lumen-conseil.fr"), ContactIdent("teams", "Claire Dubois")),
            ),
            // connu seulement par Teams : son adresse vient de son profil
            ContactLine(
                id = 14, name = "Karim Haddad", organisation = lumen,
                sources = listOf(ContactSource("teams", label = "Teams", count = 18)),
                identifiers = listOf(ContactIdent("email", "k.haddad@lumen-conseil.fr")),
            ),
        )
    }
    private val vm by lazy { main.model { MailComposeViewModel(MailDeps(mail), directory) } }

    private suspend fun kotlinx.coroutines.test.TestScope.open(route: Route.MailCompose = Route.MailCompose()) {
        vm.prepare(route, "v1")
        advanceUntilIdle()
        assertTrue(vm.setup is Load.Ready)
    }

    @Test fun `taper propose tous tes contacts, une adresse générique marquée et après les personnes`() = runTest {
        open()
        vm.type(RecipientField.TO, "lumen")
        advanceUntilIdle()
        assertEquals(RecipientField.TO, vm.suggestFor)
        assertEquals(listOf("c.dubois@lumen-conseil.fr", "k.haddad@lumen-conseil.fr", "noreply@lumen-conseil.fr"), vm.suggestions.map { it.address })
        assertEquals(listOf(false, false, true), vm.suggestions.map { it.generic })
        assertEquals("Lumen Conseil", vm.suggestions.first().about)
        // Karim ne vient pas du courrier : son adresse est proposée quand même, d'après son profil Teams
        assertTrue(vm.suggestions[1].hint!!.teams)
        assertEquals("page:lumen::1", directory.calls.last())
        assertEquals("", vm.noMatch)
    }

    @Test fun `une proposition choisie devient une puce, et ne se propose plus dans aucun champ`() = runTest {
        open()
        vm.type(RecipientField.TO, "clai")
        advanceUntilIdle()
        vm.pick(RecipientField.TO, vm.suggestions.single())
        assertEquals(listOf(MailPerson("Claire Dubois", "c.dubois@lumen-conseil.fr")), vm.to.toList())
        assertEquals("", vm.typedOf(RecipientField.TO))
        assertTrue(vm.suggestions.isEmpty())
        assertTrue(vm.touched)
        vm.showCc = true
        vm.type(RecipientField.CC, "lumen")
        advanceUntilIdle()
        assertEquals(RecipientField.CC, vm.suggestFor)
        assertEquals(listOf("k.haddad@lumen-conseil.fr", "noreply@lumen-conseil.fr"), vm.suggestions.map { it.address })
    }

    @Test fun `rien trouvé, la ligne le dit pour ce qui a été cherché`() = runTest {
        open()
        vm.type(RecipientField.TO, "personne@nulle.part")
        advanceUntilIdle()
        assertTrue(vm.suggestions.isEmpty())
        assertEquals("personne@nulle.part", vm.noMatch)
        // la virgule pose la puce telle quelle, et la ligne s'en va
        vm.type(RecipientField.TO, "personne@nulle.part,")
        assertEquals(listOf("personne@nulle.part"), vm.to.map { it.address })
        assertEquals("", vm.noMatch)
        assertNull(vm.suggestFor)
    }

    @Test fun `Écrire depuis une fiche de Contacts pose son adresse, sans rien à confirmer en quittant`() = runTest {
        open(Route.MailCompose(to = "c.dubois@lumen-conseil.fr", toName = "Claire Dubois"))
        assertEquals(listOf(MailPerson("Claire Dubois", "c.dubois@lumen-conseil.fr")), vm.to.toList())
        assertFalse(vm.touched)
        // un second chargement de la même écriture ne la double pas
        vm.retry()
        advanceUntilIdle()
        assertEquals(1, vm.to.size)
    }

    @Test fun `Retour arrière dans un champ vide retire la dernière puce, pas avec du texte tapé`() = runTest {
        open()
        vm.type(RecipientField.TO, "a@x.fr,")
        vm.type(RecipientField.TO, "b@x.fr,")
        vm.type(RecipientField.TO, "c")
        vm.removeLast(RecipientField.TO)
        assertEquals(listOf("a@x.fr", "b@x.fr"), vm.to.map { it.address })
        vm.type(RecipientField.TO, "")
        vm.removeLast(RecipientField.TO)
        assertEquals(listOf("a@x.fr"), vm.to.map { it.address })
    }
}
