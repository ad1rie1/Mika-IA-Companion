package fr.qwartz.mika.data.phone

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Les propositions de réponse (ADR 0120) : jamais une expirée, jamais deux fois la même, réglées une seule fois. */
class PhoneDraftsTest {
    private val now = 1_791_000_000_000
    private fun draft(id: Long = 7, exp: Long = now + 7_200_000) =
        PhoneDraft(id, "whatsapp", "611ae22e6d5c431f8b537e638278435d", "Léa", "J'arrive", exp, now)

    @Test fun `une proposition neuve se montre et attend un geste`() {
        val a = PhoneDrafts.admit(PhoneDraftBook(), draft(), now)
        assertTrue(a is PhoneDrafts.Admission.Show)
        val book = (a as PhoneDrafts.Admission.Show).book
        assertEquals(listOf(draft()), book.pending)
        assertEquals(draft(), PhoneDrafts.pending(book, 7, now + 1))
    }

    @Test fun `une proposition déjà expirée n'est pas montrée`() {
        assertEquals(PhoneDrafts.Admission.Expired, PhoneDrafts.admit(PhoneDraftBook(), draft(exp = now), now))
        assertEquals(PhoneDrafts.Admission.Expired, PhoneDrafts.admit(PhoneDraftBook(), draft(exp = now - 1), now))
    }

    @Test fun `une proposition déjà vue ne se remontre pas, même réglée`() {
        val book = (PhoneDrafts.admit(PhoneDraftBook(), draft(), now) as PhoneDrafts.Admission.Show).book
        assertEquals(PhoneDrafts.Admission.Seen, PhoneDrafts.admit(book, draft(), now))
        val settled = PhoneDrafts.settled(book, 7)
        assertNull(PhoneDrafts.pending(settled, 7, now))
        assertEquals(PhoneDrafts.Admission.Seen, PhoneDrafts.admit(settled, draft(), now))
    }

    @Test fun `à son échéance une proposition n'attend plus rien`() {
        val book = (PhoneDrafts.admit(PhoneDraftBook(), draft(), now) as PhoneDrafts.Admission.Show).book
        assertNull(PhoneDrafts.pending(book, 7, now + 7_200_000))
        assertTrue(PhoneDrafts.prune(book, now + 7_200_000).pending.isEmpty())
        assertEquals(book, PhoneDrafts.prune(book, now))
    }

    @Test fun `une proposition lisible a tout ce qu'il faut`() {
        assertTrue(PhoneDrafts.isValid(draft()))
        assertFalse(PhoneDrafts.isValid(draft(id = 0)))
        assertFalse(PhoneDrafts.isValid(draft().copy(app = "telegram")))
        assertFalse(PhoneDrafts.isValid(draft().copy(thread = "abc")))
        assertFalse(PhoneDrafts.isValid(draft().copy(text = " ")))
        assertFalse(PhoneDrafts.isValid(draft(exp = 0)))
    }

    @Test fun `chaque proposition a sa notification, au-dessus de celles de l'app`() {
        assertNotEquals(PhoneDrafts.notificationId(7), PhoneDrafts.notificationId(8))
        assertTrue(PhoneDrafts.notificationId(1) > 2)
        assertTrue(PhoneDrafts.notificationId(Long.MAX_VALUE) > 2)
        assertTrue(PhoneDrafts.notificationId(-5) > 2)
    }
}
