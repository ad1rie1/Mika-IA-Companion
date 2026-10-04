package fr.qwartz.mika.data.approvals

import fr.qwartz.mika.data.net.ApprovalCard
import fr.qwartz.mika.data.net.ApprovalDecision
import fr.qwartz.mika.data.net.MikaProtocol
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

/** Les règles des cartes d'accord (ADR 0064), sans écran ni socket. */
class ApprovalsTest {
    private val now = 1_790_600_000_000L
    private val card = ApprovalCard(
        id = 905,
        title = "Appeler « prevision » (meteo)",
        text = "Service : meteo\nOutil : prevision",
        digest = "3f9c",
        expiresAt = now + 4 * 60_000,
    )
    private val other = card.copy(id = 906, digest = "ab12", expiresAt = null)

    private fun view(
        c: ApprovalCard = card,
        pending: PendingDecision? = null,
        online: Boolean = true,
        wall: Long = now,
        elapsed: Long = 100_000,
    ) = Approvals.view(c, pending, online, wall, elapsed)

    // ── L'état ───────────────────────────────────────────────────────────────────────────

    @Test fun `chaque socket repart d'une liste vide — le serveur ne renvoie la liste que si elle n'est pas vide`() {
        var state = Approvals.received(listOf(card, other))
        state = Approvals.sent(state, 905, ApprovalDecision.ACCEPT, 0)
        // Reconnexion : plus aucune carte n'attend (s'il y en avait, la liste suivrait).
        state = Approvals.opened()
        assertEquals(ApprovalsState(), state)
        // Une liste arrive après l'ouverture : c'est elle, exactement.
        state = Approvals.received(listOf(other))
        assertEquals(listOf(other), state.cards)
    }

    @Test fun `une liste remplace la précédente en entier, décisions en attente comprises`() {
        var state = Approvals.received(listOf(card, other))
        state = Approvals.sent(state, 905, ApprovalDecision.REFUSE, 0)
        assertEquals(setOf(905L), state.pending.keys)
        state = Approvals.received(listOf(other))
        assertEquals(listOf(other), state.cards)
        assertTrue(state.pending.isEmpty())
        assertEquals(ApprovalsState(), Approvals.received(emptyList()))
    }

    @Test fun `une décision n'attend que pour une carte affichée, et jusqu'à son sort`() {
        val shown = Approvals.received(listOf(card))
        assertSame(shown, Approvals.sent(shown, 999, ApprovalDecision.ACCEPT, 0))
        val sent = Approvals.sent(shown, 905, ApprovalDecision.ACCEPT, 50)
        assertEquals(PendingDecision(ApprovalDecision.ACCEPT, 50), sent.pending[905])
        val resolved = Approvals.resolved(sent, 905)
        assertTrue(resolved.pending.isEmpty())
        assertEquals(listOf(card), resolved.cards) // la carte reste jusqu'à la liste suivante
        assertSame(resolved, Approvals.resolved(resolved, 905))
    }

    // ── Ce que l'écran montre ────────────────────────────────────────────────────────────

    @Test fun `une carte ordinaire en ligne — accepter et refuser, le compte à rebours`() {
        val v = view()
        assertTrue(v.canAccept)
        assertTrue(v.canRefuse)
        assertNull(v.hint)
        assertNull(v.blocked)
        assertNull(v.pending)
        assertFalse(v.expired)
        assertEquals("expire dans 4 min", v.expiry)
        assertEquals("3f9c", v.digest)
        assertEquals(card.text, v.text)
    }

    @Test fun `hors ligne, aucun bouton — rien n'est mis en file`() {
        val v = view(online = false)
        assertFalse(v.canAccept)
        assertFalse(v.canRefuse)
        assertEquals("Hors ligne : tu pourras décider au retour de la connexion.", v.hint)
    }

    @Test fun `bloquée — seul le refus, et la raison est dite`() {
        val v = view(card.copy(blocked = "l'outil a changé"))
        assertFalse(v.canAccept)
        assertTrue(v.canRefuse)
        assertEquals("Ne peut pas partir tel quel : l'outil a changé", v.blocked)
        assertNull(v.hint)
        assertEquals("Ne peut pas partir tel quel : raison non précisée", view(card.copy(blocked = "  ")).blocked)
    }

    @Test fun `expirée — accepter s'éteint et la carte le dit`() {
        val v = view(wall = card.expiresAt!!)
        assertTrue(v.expired)
        assertFalse(v.canAccept)
        assertTrue(v.canRefuse)
        assertEquals("expirée", v.expiry)
        assertEquals("Le délai est passé : seul le refus reste possible.", v.hint)
        // Une seconde avant, elle valait encore.
        assertTrue(view(wall = card.expiresAt - 1_000).canAccept)
    }

    @Test fun `sans empreinte ou lue en partie, on n'accepte pas ce qu'on n'a pas vu`() {
        val noDigest = view(card.copy(digest = ""))
        assertFalse(noDigest.canAccept)
        assertTrue(noDigest.canRefuse)
        assertEquals("Ce qui partirait n'a pas pu être relu : seul le refus est possible.", noDigest.hint)
        val cut = view(card.copy(complete = false))
        assertFalse(cut.canAccept)
        assertTrue(cut.canRefuse)
        assertEquals("Trop longue pour être montrée en entier ici : seul le refus est possible.", cut.hint)
    }

    @Test fun `une décision partie éteint les deux boutons, jusqu'à sa réponse ou 30 s`() {
        val pending = PendingDecision(ApprovalDecision.ACCEPT, sentAtElapsedMs = 100_000)
        val waiting = view(pending = pending, elapsed = 100_000 + Approvals.PENDING_TIMEOUT_MS - 1)
        assertEquals(ApprovalDecision.ACCEPT, waiting.pending)
        assertFalse(waiting.canAccept)
        assertFalse(waiting.canRefuse)
        assertEquals("Accord envoyé…", waiting.hint)
        assertEquals("Refus envoyé…", view(pending = pending.copy(decision = ApprovalDecision.REFUSE)).hint)

        val stale = view(pending = pending, elapsed = 100_000 + Approvals.PENDING_TIMEOUT_MS)
        assertNull(stale.pending)
        assertTrue(stale.canAccept)
        assertTrue(stale.canRefuse)
    }

    @Test fun `un titre vide prend un titre de repli`() {
        assertEquals(Approvals.FALLBACK_TITLE, view(card.copy(title = "  ")).title)
    }

    @Test fun `les vues suivent la liste, chacune avec sa décision en attente`() {
        val state = Approvals.sent(Approvals.received(listOf(card, other)), 906, ApprovalDecision.REFUSE, 100_000)
        val views = Approvals.views(state, online = true, nowWallMs = now, nowElapsedMs = 100_000)
        assertEquals(listOf(905L, 906L), views.map { it.id })
        assertNull(views[0].pending)
        assertEquals(ApprovalDecision.REFUSE, views[1].pending)
        assertNull(views[1].expiry)
    }

    // ── Le temps ─────────────────────────────────────────────────────────────────────────

    @Test fun `le compte à rebours, arrondi à la minute supérieure`() {
        fun label(leftMs: Long) = Approvals.expiryLabel(now + leftMs, now)
        assertNull(Approvals.expiryLabel(null, now))
        assertEquals("expirée", label(0))
        assertEquals("expirée", label(-60_000))
        assertEquals("expire dans moins d'une minute", label(30_000))
        assertEquals("expire dans 1 min", label(60_000))
        assertEquals("expire dans 4 min", label(3 * 60_000 + 10_000))
        assertEquals("expire dans 59 min", label(59 * 60_000))
        assertEquals("expire dans 1 h", label(59 * 60_000 + 1))
        assertEquals("expire dans 2 h", label(120 * 60_000))
        assertEquals("expire dans 2 h 05", label(125 * 60_000))
        assertEquals("expire dans 23 h 59", label(23 * 3_600_000L + 59 * 60_000))
        assertEquals("expire dans 3 j", label(3 * 24 * 3_600_000L))
    }

    @Test fun `on recalcule toutes les 30 s, plus tôt à une échéance, jamais plus vite qu'une seconde`() {
        assertEquals(Approvals.TICK_MS, Approvals.nextTickMs(ApprovalsState(), now, 0))
        assertEquals(Approvals.TICK_MS, Approvals.nextTickMs(Approvals.received(listOf(other)), now, 0))
        val soon = Approvals.received(listOf(card.copy(expiresAt = now + 5_000), other))
        assertEquals(5_000L, Approvals.nextTickMs(soon, now, 0))
        val imminent = Approvals.received(listOf(card.copy(expiresAt = now + 10)))
        assertEquals(Approvals.MIN_TICK_MS, Approvals.nextTickMs(imminent, now, 0))
        val past = Approvals.received(listOf(card.copy(expiresAt = now - 10)))
        assertEquals(Approvals.TICK_MS, Approvals.nextTickMs(past, now, 0))
        val waiting = Approvals.sent(Approvals.received(listOf(other)), 906, ApprovalDecision.ACCEPT, 0)
        assertEquals(8_000L, Approvals.nextTickMs(waiting, now, Approvals.PENDING_TIMEOUT_MS - 8_000))
    }

    // ── Le sort d'une décision ───────────────────────────────────────────────────────────

    @Test fun `chaque sort se dit en français, et un statut inconnu n'est jamais un succès`() {
        val approved = Approvals.resultMessage(MikaProtocol.APPROVAL_APPROVED)
        assertEquals("Accepté : la demande part.", approved)
        assertEquals("Refusé : rien ne partira.", Approvals.resultMessage(MikaProtocol.APPROVAL_REJECTED))
        val others = listOf(
            MikaProtocol.APPROVAL_REJECTED, MikaProtocol.APPROVAL_UNKNOWN, MikaProtocol.APPROVAL_CHANGED,
            MikaProtocol.APPROVAL_BLOCKED, MikaProtocol.APPROVAL_EXPIRED, MikaProtocol.APPROVAL_FORBIDDEN,
            "", "APPROVED", "approved ", "ok",
        )
        val messages = others.map(Approvals::resultMessage)
        for (m in messages) {
            assertNotEquals(approved, m)
            assertFalse(m, m.startsWith("Accepté"))
        }
        // Les six autres statuts connus disent chacun autre chose.
        assertEquals(6, messages.take(6).toSet().size)
        assertEquals("Décision non prise : rien n'est parti.", Approvals.resultMessage("ok"))
    }
}
