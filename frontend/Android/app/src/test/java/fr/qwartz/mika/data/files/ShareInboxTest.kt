package fr.qwartz.mika.data.files

import fr.qwartz.mika.data.chat.MemoryThreadStore
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ShareInboxTest {
    @Test fun `deux partages s'accumulent, la barre de saisie prend tout d'un coup`() = runTest {
        val inbox = ShareInbox(MemoryThreadStore())
        val a = StagedFile("a.png", "image/png", "/s/a", 1)
        val b = StagedFile("b.pdf", "application/pdf", "/s/b", 2)
        inbox.deposit(ComposerDraft("premier", listOf(a)))
        inbox.deposit(ComposerDraft("second", listOf(b), listOf("c ignoré")))
        assertEquals(2L, inbox.arrivals.value)
        assertEquals(ComposerDraft("premier\nsecond", listOf(a, b), listOf("c ignoré")), inbox.take())
        assertNull(inbox.take())
    }

    @Test fun `un dépôt vide n'est pas un dépôt`() = runTest {
        val inbox = ShareInbox(MemoryThreadStore())
        inbox.deposit(ComposerDraft())
        assertEquals(0L, inbox.arrivals.value)
        assertNull(inbox.take())
    }
}
