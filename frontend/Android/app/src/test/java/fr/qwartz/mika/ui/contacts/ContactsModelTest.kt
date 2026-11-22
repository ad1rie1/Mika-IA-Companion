package fr.qwartz.mika.ui.contacts

import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.contacts.ContactFact
import fr.qwartz.mika.data.moi.contacts.ContactForget
import fr.qwartz.mika.data.moi.contacts.ContactIdent
import fr.qwartz.mika.data.moi.contacts.ContactKinds
import fr.qwartz.mika.data.moi.contacts.ContactLine
import fr.qwartz.mika.data.moi.contacts.ContactSheet
import fr.qwartz.mika.data.moi.contacts.ContactsCounts
import fr.qwartz.mika.data.moi.contacts.ContactsLimits
import fr.qwartz.mika.ui.mail.MainDispatcherRule
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
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Les écrans de Contacts contre une fausse API : la liste (la recherche après la pause de frappe, la sorte, la suite en
 * fin de liste gardée par une relecture discrète, une relecture en panne qui garde ce qui était montré), la fiche (sa
 * relecture, l'oublier, qu'elle oublie un fait), et ce qu'une fiche dit à la liste.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ContactsModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val api = FakeContactsApi()
    private val list by lazy { main.model { ContactsListViewModel(ContactsDeps(api)) } }
    private val sheet by lazy { main.model { ContactSheetViewModel(ContactsDeps(api)) } }

    private fun person(id: Int, name: String, email: String = "") =
        ContactLine(id = id, name = name, identifiers = if (email.isEmpty()) emptyList() else listOf(ContactIdent("email", email)))

    private val claire = person(12, "Claire Dubois", "c.dubois@lumen.fr")
    private val lea = person(13, "Léa Moreau", "lea@x.fr")
    private val lumen = ContactLine(id = 3, kind = ContactKinds.ORG, name = "Lumen Conseil", identifiers = listOf(ContactIdent("domain", "lumen.fr")))

    private val claireSheet = ContactSheet(
        id = 12, name = "Claire Dubois", privacy = ContactSheet.PRIVACY_MINE, forget = ContactForget(allowed = true),
        facts = listOf(
            ContactFact("note", value = "Elle attend ta version.", id = 41, from = "ses mails à Pro", forget = true),
            ContactFact("note", value = "Elle prépare l'anniversaire.", id = 42, from = "ses mails à Boîte de Léa", forget = false),
        ),
    )

    private suspend fun <T> Flow<T>.next(): T? = withTimeoutOrNull(200) { first() }

    private fun ready(): ContactsListing = (list.listing as Load.Ready).value

    // ── La liste ──

    @Test fun `la liste se lit dans l'ordre du serveur, avec les nombres de chaque sorte`() = runTest {
        api.contacts = mutableListOf(claire, lumen, lea)
        list.resume()
        advanceUntilIdle()
        assertEquals(listOf(12, 3, 13), ready().items.map { it.id })
        assertEquals(ContactsCounts(all = 3, person = 2, org = 1), list.counts)
        list.choose(ContactKinds.ORG)
        advanceUntilIdle()
        assertEquals(listOf(3), ready().items.map { it.id })
        assertEquals("page::org:1", api.calls.last())
        // les nombres restent ceux de toutes les sortes
        assertEquals(3, list.counts!!.all)
    }

    @Test fun `la recherche part après la pause de frappe, la dernière seulement`() = runTest {
        api.contacts = mutableListOf(claire, lea)
        list.resume()
        advanceUntilIdle()
        api.calls.clear()
        list.search("c")
        list.search("cl")
        list.search("cla")
        advanceUntilIdle()
        assertEquals(listOf("page:cla::1"), api.calls)
        assertEquals(listOf(12), ready().items.map { it.id })
        assertEquals("cla", ready().q)
    }

    @Test fun `la suite se lit en fin de liste, et une relecture discrète la garde si rien n'a changé devant`() = runTest {
        api.contacts = (1..120).map { person(it, "P$it", "p$it@x.fr") }.toMutableList()
        list.resume()
        advanceUntilIdle()
        assertEquals(ContactsLimits.PAGE, ready().items.size)
        list.more()
        advanceUntilIdle()
        assertEquals(2 * ContactsLimits.PAGE, ready().items.size)
        assertEquals("page:::2", api.calls.last())
        // l'écran revient : la première page relue est la même, la suite reste
        list.resume()
        advanceUntilIdle()
        assertEquals(2 * ContactsLimits.PAGE, ready().items.size)
        // quelqu'un de neuf en tête : la liste repart de la première page
        api.contacts.add(0, person(500, "Nouveau", "n@x.fr"))
        list.resume()
        advanceUntilIdle()
        assertEquals(ContactsLimits.PAGE, ready().items.size)
        assertEquals(500, ready().items.first().id)
    }

    @Test fun `une suite qui ne se lit pas ne se redemande qu'à Réessayer`() = runTest {
        api.contacts = (1..60).map { person(it, "P$it") }.toMutableList()
        list.resume()
        advanceUntilIdle()
        api.pageFail = MoiError(0, MoiError.NETWORK)
        list.more()
        advanceUntilIdle()
        assertEquals(MoiError.NETWORK, list.moreError)
        assertEquals(ContactsLimits.PAGE, ready().items.size)
        api.pageFail = null
        list.more()
        advanceUntilIdle()
        assertEquals("", list.moreError)
        assertEquals(60, ready().items.size)
    }

    @Test fun `une relecture en panne garde ce qui était montré, tirer la dit`() = runTest {
        api.contacts = mutableListOf(claire)
        list.resume()
        advanceUntilIdle()
        api.pageFail = MoiError(0, MoiError.NETWORK)
        list.resume()
        advanceUntilIdle()
        assertEquals(listOf(12), ready().items.map { it.id })
        list.pull()
        advanceUntilIdle()
        assertEquals(MoiError.NETWORK, list.said.next())
        assertFalse(list.refreshing)
        assertEquals(listOf(12), ready().items.map { it.id })
    }

    // ── La fiche ──

    @Test fun `la fiche se lit, puis se relit sans bruit à chaque retour, une relecture en panne la garde`() = runTest {
        api.sheets[12] = claireSheet
        sheet.open(12)
        advanceUntilIdle()
        assertEquals("Claire Dubois", sheet.sheet.valueOrNull?.name)
        api.sheets[12] = claireSheet.copy(title = "Cheffe de projet")
        sheet.open(12)
        advanceUntilIdle()
        assertEquals("Cheffe de projet", sheet.sheet.valueOrNull?.title)
        api.sheetFail = MoiError(0, MoiError.NETWORK)
        sheet.open(12)
        advanceUntilIdle()
        assertEquals("Cheffe de projet", sheet.sheet.valueOrNull?.title)
        // plus là (oublié ailleurs) : la fiche le dit
        api.sheetFail = MoiError(404, "Introuvable : ce n'est plus là.")
        sheet.open(12)
        advanceUntilIdle()
        assertTrue(sheet.sheet is Load.Failed)
    }

    @Test fun `oublier un contact, la fiche revient à la liste, qui le perd aussitôt avec ses nombres`() = runTest {
        api.contacts = mutableListOf(claire, lea)
        api.sheets[12] = claireSheet
        list.resume()
        advanceUntilIdle()
        // la liste lue ne se relit pas entre-temps : c'est la fiche qui le lui dit
        api.hold("page")
        sheet.open(12)
        advanceUntilIdle()
        sheet.forget()
        advanceUntilIdle()
        assertTrue(sheet.gone)
        assertEquals("« Claire Dubois » est oublié·e : ce n'est plus un de tes contacts.", sheet.said.next())
        assertEquals(listOf(13), ready().items.map { it.id })
        assertEquals(ContactsCounts(all = 1, person = 1, org = 0), list.counts)
        sheet.leave()
        assertFalse(sheet.gone)
        api.release("page")
    }

    @Test fun `un double appui n'oublie qu'une fois`() = runTest {
        api.sheets[12] = claireSheet
        sheet.open(12)
        advanceUntilIdle()
        api.hold("forget")
        sheet.forget()
        sheet.forget()
        assertTrue(sheet.busy)
        api.release("forget")
        advanceUntilIdle()
        assertEquals(1, api.calls.count { it == "forget:12" })
        assertFalse(sheet.busy)
    }

    @Test fun `un oubli que le serveur ne permet pas d'ici ne part pas, refusé, ses mots et la fiche se relit`() = runTest {
        api.sheets[12] = claireSheet.copy(forget = ContactForget(allowed = false, reason = "Une part vient d'un compte qu'on te partage."))
        sheet.open(12)
        advanceUntilIdle()
        sheet.forget()
        advanceUntilIdle()
        assertTrue(api.calls.none { it.startsWith("forget") })
        // la fiche disait oui, le serveur dit non (un partage arrivé entre-temps)
        api.sheets[12] = claireSheet
        sheet.open(12)
        advanceUntilIdle()
        api.forgetFail = MoiError(403, "Une part de ce qu'elle en sait vient d'un compte qu'on te partage.")
        api.calls.clear()
        sheet.forget()
        advanceUntilIdle()
        assertEquals("Une part de ce qu'elle en sait vient d'un compte qu'on te partage.", sheet.said.next())
        assertFalse(sheet.gone)
        assertEquals(listOf("forget:12", "sheet:12"), api.calls)
    }

    @Test fun `déjà oublié ailleurs (404), la fiche revient à la liste`() = runTest {
        api.sheets[12] = claireSheet
        sheet.open(12)
        advanceUntilIdle()
        api.forgetFail = MoiError(404, "Introuvable : ce n'est plus là.")
        sheet.forget()
        advanceUntilIdle()
        assertTrue(sheet.gone)
    }

    @Test fun `un fait d'un de tes comptes s'oublie et la fiche se relit, un fait d'un autre compte ne part pas d'ici`() = runTest {
        api.sheets[12] = claireSheet
        sheet.open(12)
        advanceUntilIdle()
        sheet.forgetFact(42)
        advanceUntilIdle()
        assertTrue(api.calls.none { it.startsWith("fact") })
        sheet.forgetFact(41)
        advanceUntilIdle()
        assertEquals("Oublié : elle ne le réapprendra pas.", sheet.said.next())
        assertEquals(listOf(42), sheet.sheet.valueOrNull!!.facts.map { it.id })
        assertNull(sheet.sheet.valueOrNull!!.facts.firstOrNull { it.id == 41 })
        assertEquals("sheet:12", api.calls.last())
    }
}
