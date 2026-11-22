package fr.qwartz.mika.ui.mail

import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.mail.MailBox
import fr.qwartz.mika.data.moi.mail.MailBoxes
import fr.qwartz.mika.data.moi.mail.MailRow
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * La liste de Mail et sa page suivante (R2-06) : après un rangement, rien ne tombe entre deux pages ni ne revient en
 * double ; une page reçue ne défait pas un rangement fait pendant qu'elle se lisait. Une ligne glissée part à la
 * corbeille par le même geste, revient si le serveur refuse, et « Annuler » la remet à sa place.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class MailListModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val api = FakeMailApi()
    private val list by lazy { main.model { MailListViewModel(MailDeps(api)) } }

    private fun ref(n: Int) = "pro:<$n@x>"

    private fun inbox(n: Int) {
        // les plus récents d'abord, comme le serveur
        api.inbox = (1..n).map { MailRow(ref = ref(it), box = "pro", folder = "INBOX", subject = "Mail $it", seen = false, date = 1_000L * (n - it + 1)) }.toMutableList()
    }

    private fun shown(n: Int): MailRow = list.listing.valueOrNull!!.rows.first { it.ref == ref(n) }

    /** Ce que la liste dit (ses toasts) et ce qu'elle offre d'annuler, entendus dès maintenant. */
    private fun TestScope.listen(): Pair<MutableList<String>, MutableList<MailListViewModel.Trashed>> {
        val said = mutableListOf<String>()
        val trashed = mutableListOf<MailListViewModel.Trashed>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { list.said.collect { said += it } }
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { list.trashed.collect { trashed += it } }
        return said to trashed
    }

    private val rows: List<String> get() = list.listing.valueOrNull!!.rows.map { it.ref }

    private fun TestScope.archive(vararg n: Int) {
        val shown = list.listing.valueOrNull!!.rows
        for (i in n) list.toggle(shown.first { it.ref == ref(i) }, "lecture seule")
        list.tidySelected("archive")
        advanceUntilIdle()
    }

    @Test fun `trois mails archivés - la page suivante n'en saute aucun`() = runTest {
        inbox(40)
        list.resume()
        advanceUntilIdle()
        assertEquals(25, rows.size)
        archive(2, 3, 4)
        assertEquals(22, rows.size)
        list.loadMore()
        advanceUntilIdle()
        // les anciens 26ᵉ à 28ᵉ sont là : la liste suit le serveur, sans trou ni doublon
        assertEquals(api.inbox.map { it.ref }, rows)
        assertTrue(ref(26) in rows && ref(27) in rows && ref(28) in rows)
    }

    @Test fun `lus sous « Non lus » depuis la liseuse - la page suivante n'en saute aucun`() = runTest {
        inbox(40)
        list.toggleFilter("unread")
        list.resume()
        advanceUntilIdle()
        // lus ailleurs : la liste les garde (marqués lus) jusqu'à sa relecture, le serveur ne les compte plus
        val read = listOf(ref(1), ref(2), ref(3))
        api.inbox.removeAll { it.ref in read }
        MailChanges.tell(MailChanges.Change.Tidied(read, "read"))
        advanceUntilIdle()
        list.loadMore()
        advanceUntilIdle()
        for (n in 4..40) assertTrue("le mail $n manque", ref(n) in rows)
        assertEquals(rows.size, rows.distinct().size)
    }

    @Test fun `un mail archivé pendant la lecture de la page suivante ne revient pas`() = runTest {
        inbox(40)
        list.resume()
        advanceUntilIdle()
        // la page suivante part ; le serveur répond ce qu'il avait (le mail 5 encore là)…
        api.hold("messages")
        list.loadMore()
        // …et pendant ce temps, le mail 5 est archivé
        archive(5)
        api.release("messages")
        advanceUntilIdle()
        assertFalse(ref(5) in rows)
        assertEquals(39, rows.size)
    }

    @Test fun `au-delà de cent lignes, la suite reprend sans trou après un rangement`() = runTest {
        inbox(140)
        list.resume()
        advanceUntilIdle()
        repeat(3) {
            list.loadMore()
            advanceUntilIdle()
        }
        assertEquals(100, rows.size)
        archive(2, 3, 4)
        list.loadMore()
        advanceUntilIdle()
        assertEquals(api.inbox.take(100).map { it.ref }, rows)
        list.loadMore()
        advanceUntilIdle()
        assertEquals(api.inbox.take(125).map { it.ref }, rows)
        list.loadMore()
        advanceUntilIdle()
        assertEquals(api.inbox.map { it.ref }, rows)
    }

    // ── la sélection, aussitôt (ADR 0302) ──

    @Test fun `archivé, il quitte la liste avant la réponse du serveur, et une relecture d'ici là ne le remonte pas`() = runTest {
        inbox(5)
        list.resume()
        advanceUntilIdle()
        val two = shown(2)
        api.hold("tidy")
        archive(2)
        assertFalse(ref(2) in rows)
        assertTrue(list.selected.isEmpty())
        // le serveur ne l'a pas encore rangé : sa liste le rapporte encore
        api.inbox.add(1, two)
        list.pull()
        advanceUntilIdle()
        assertFalse(ref(2) in rows)
        api.release("tidy")
        advanceUntilIdle()
        // il a répondu : une lecture partie après dit ce qu'il sait (ici, le mail remis à la main dans sa réception)
        list.pull()
        advanceUntilIdle()
        assertTrue(ref(2) in rows)
    }

    @Test fun `refusés par le serveur, ils reviennent et le refus se dit`() = runTest {
        inbox(5)
        list.resume()
        advanceUntilIdle()
        val (said, _) = listen()
        api.tidyFail = MoiError(502, "Le serveur a refusé : boîte injoignable.")
        api.hold("tidy")
        list.toggle(shown(3), "lecture seule")
        list.toggle(shown(4), "lecture seule")
        list.tidySelected("trash")
        assertEquals(listOf(ref(1), ref(2), ref(5)), rows)
        api.release("tidy")
        advanceUntilIdle()
        assertEquals((1..5).map { ref(it) }, rows)
        assertEquals(listOf("Le serveur a refusé : boîte injoignable."), said)
    }

    @Test fun `rangé depuis la liseuse puis refusé, il revient dans la liste`() = runTest {
        inbox(3)
        list.resume()
        advanceUntilIdle()
        val id = MailChanges.nextId()
        MailChanges.tell(MailChanges.Change.Tidied(listOf(ref(2)), "archive", id))
        advanceUntilIdle()
        assertEquals(listOf(ref(1), ref(3)), rows)
        list.pull()  // une relecture d'ici là ne le remonte pas
        advanceUntilIdle()
        assertEquals(listOf(ref(1), ref(3)), rows)
        MailChanges.tell(MailChanges.Change.Settled(id, ok = false))
        advanceUntilIdle()
        assertEquals((1..3).map { ref(it) }, rows)
    }

    // ── glisser vers la corbeille ──

    @Test fun `glissée, une ligne part à la corbeille et s'offre à « Annuler »`() = runTest {
        inbox(5)
        list.resume()
        advanceUntilIdle()
        val (_, trashed) = listen()
        api.hold("tidy")
        assertTrue(list.swipeTrash(shown(2)))
        // le serveur n'a pas répondu : elle reste écartée, et un second glissement ne part pas
        assertTrue(ref(2) in list.trashing)
        assertFalse(list.swipeTrash(shown(2)))
        api.release("tidy")
        advanceUntilIdle()
        assertEquals(listOf("tidy:trash"), api.calls.filter { it.startsWith("tidy") })
        assertFalse(ref(2) in rows)
        assertEquals(4, list.listing.valueOrNull!!.total)
        assertTrue(list.trashing.isEmpty())
        assertEquals(listOf(ref(2)), trashed.map { it.row.ref })
    }

    @Test fun `refusée par le serveur, la ligne revient et le refus se dit`() = runTest {
        inbox(5)
        list.resume()
        advanceUntilIdle()
        val (said, trashed) = listen()
        api.tidyFail = MoiError(502, "Le serveur a refusé : boîte injoignable.")
        assertTrue(list.swipeTrash(shown(3)))
        advanceUntilIdle()
        assertTrue(ref(3) in rows)
        assertTrue(list.trashing.isEmpty())
        assertTrue(trashed.isEmpty())
        assertEquals(listOf("Le serveur a refusé : boîte injoignable."), said)
    }

    @Test fun `« Annuler » la remet dans son dossier, à sa place`() = runTest {
        inbox(5)
        list.resume()
        advanceUntilIdle()
        val (_, trashed) = listen()
        list.swipeTrash(shown(3))
        advanceUntilIdle()
        assertEquals(listOf(ref(1), ref(2), ref(4), ref(5)), rows)
        list.untrash(trashed.single())
        advanceUntilIdle()
        assertEquals("tidy:move:INBOX", api.calls.last { it.startsWith("tidy") })
        assertEquals((1..5).map { ref(it) }, rows)
        assertEquals(5, list.listing.valueOrNull!!.total)
    }

    @Test fun `une boîte partagée en lecture ne se glisse pas`() = runTest {
        api.boxes = MailBoxes(boxes = listOf(MailBox(key = "pro", name = "Atelier", level = Levels.READ)))
        inbox(3)
        list.resume()
        advanceUntilIdle()
        assertFalse(list.swipeTrash(shown(1)))
        assertTrue(api.calls.none { it.startsWith("tidy") })
        assertTrue(ref(1) in rows)
    }
}
