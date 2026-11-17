package fr.qwartz.mika.ui.mail

import fr.qwartz.mika.data.moi.mail.MailRow
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * La liste de Mail et sa page suivante (R2-06) : après un rangement, rien ne tombe entre deux pages ni ne revient en
 * double ; une page reçue ne défait pas un rangement fait pendant qu'elle se lisait.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class MailListModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val api = FakeMailApi()
    private val list by lazy { main.model { MailListViewModel(MailDeps(api)) } }

    private fun ref(n: Int) = "pro:<$n@x>"

    private fun inbox(n: Int) {
        api.inbox = (1..n).map { MailRow(ref = ref(it), box = "pro", folder = "INBOX", subject = "Mail $it", seen = false) }.toMutableList()
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
}
