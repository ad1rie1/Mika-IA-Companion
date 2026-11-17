package fr.qwartz.mika.ui.shell

import fr.qwartz.mika.data.approvals.ApprovalsState
import fr.qwartz.mika.data.approvals.PendingDecision
import fr.qwartz.mika.data.net.ApprovalCard
import fr.qwartz.mika.data.net.ApprovalDecision
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * La pastille de ☰ et de « Chat » hors du chat (R1-01) : un accord qui attend ta décision, ou une parole de Mika depuis
 * ton dernier lu. Ni un accord expiré, ni un accord déjà décidé dont la réponse est en route.
 */
class ChatCueTest {
    private val now = 1_800_000_000_000L
    private val card = ApprovalCard(7, "Lancer le script", "python run.py", "d-7", expiresAt = now + 60_000)

    @Test fun `rien de neuf - pas de pastille`() {
        assertFalse(ChatCue.waiting(lastFromMika = 40, lastReadId = 40, ApprovalsState(), now, 0))
    }

    @Test fun `elle a écrit depuis le dernier lu`() {
        assertTrue(ChatCue.waiting(lastFromMika = 41, lastReadId = 40, ApprovalsState(), now, 0))
    }

    @Test fun `un accord attend ta décision`() {
        assertTrue(ChatCue.waiting(40, 40, ApprovalsState(listOf(card)), now, 0))
        assertTrue(ChatCue.waiting(40, 40, ApprovalsState(listOf(card.copy(expiresAt = null))), now, 0))
    }

    @Test fun `ni un accord expiré, ni un accord décidé dont la réponse est en route`() {
        assertFalse(ChatCue.waiting(40, 40, ApprovalsState(listOf(card.copy(expiresAt = now - 1))), now, 0))
        val sent = ApprovalsState(listOf(card), mapOf(7L to PendingDecision(ApprovalDecision.ACCEPT, sentAtElapsedMs = 1_000)))
        assertFalse(ChatCue.waiting(40, 40, sent, now, nowElapsedMs = 5_000))
        // sans réponse au bout de 30 s, les boutons reviennent : il attend de nouveau
        assertTrue(ChatCue.waiting(40, 40, sent, now, nowElapsedMs = 40_000))
    }

    @Test fun `Outils › Accords compte ceux qui attendent, pas les expirés ni les décidés (R3-09)`() {
        val expired = card.copy(id = 8, expiresAt = now - 3_600_000)
        val decided = card.copy(id = 9)
        val state = ApprovalsState(listOf(card, expired, decided), mapOf(9L to PendingDecision(ApprovalDecision.REFUSE, sentAtElapsedMs = 1_000)))
        assertEquals(1, ChatCue.open(state, now, nowElapsedMs = 5_000))
        assertEquals(0, ChatCue.open(ApprovalsState(listOf(expired)), now, 0))
    }
}
