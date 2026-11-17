package fr.qwartz.mika.ui.chat

import fr.qwartz.mika.data.approvals.Approvals
import fr.qwartz.mika.data.approvals.PendingDecision
import fr.qwartz.mika.data.moi.Counts
import fr.qwartz.mika.data.moi.mail.DraftStates
import fr.qwartz.mika.data.moi.mail.MailDraft
import fr.qwartz.mika.data.moi.mail.MailPerson
import fr.qwartz.mika.data.moi.teams.ReplyStates
import fr.qwartz.mika.data.moi.teams.TeamsReply
import fr.qwartz.mika.data.net.ApprovalCard
import fr.qwartz.mika.data.net.ApprovalDecision
import fr.qwartz.mika.ui.Route
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** La ligne repliée au-dessus du champ (ADR 0235, point 4), ses brouillons (ADR 0191) et « Tout accepter » (ADR 0170). */
class ChatTrayTest {
    private val now = 1_790_600_000_000L
    private val meteo = ApprovalCard(905, "Demander la météo de dimanche", "lieu : Mont des Cats", "3f9c", expiresAt = now + 4 * 60_000, capability = "mcp.call")
    private val push = ApprovalCard(906, "Pousser le dépôt", "git push origin main", "ab12", expiresAt = now + 12 * 60_000, capability = "project.push")
    private val mailCard = ApprovalCard(907, "Envoyer « Re: Présentation »", "À : claire@…", "cd34", expiresAt = now + 60_000, capability = "email.send", draft = "d-claire")
    private val teamsCard = ApprovalCard(908, "Répondre à Claire dans Teams", "Oui je l'ai vu", "ef56", capability = "teams.send", draft = "r-claire")

    private fun views(vararg cards: ApprovalCard, online: Boolean = true, pending: Map<Long, PendingDecision> = emptyMap()) =
        cards.map { Approvals.view(it, pending[it.id], online, now, 100_000) }

    private val claire = MailDraft(
        id = "d-claire", state = DraftStates.WAITING, decides = true, subject = "Re: Présentation de jeudi",
        toPeople = listOf(MailPerson("Claire Dubois", "claire@example.test")),
    )
    private val reply = TeamsReply(
        id = "r-claire", conversation = "pro~19:abc", title = "Claire Dubois", state = ReplyStates.WAITING,
        body = "Oui je l'ai vu, merci !",
    )

    @Test fun `une carte de mail qui nomme son brouillon, une réponse Teams, des liens, jamais leurs boutons`() {
        assertEquals(DraftPlace.MAIL, ChatTray.place("email.send", "d-1"))
        assertNull(ChatTray.place("email.send", "")) // sans brouillon nommé, la carte reste ici
        assertEquals(DraftPlace.TEAMS, ChatTray.place("teams.send", ""))
        assertNull(ChatTray.place("mcp.call", "d-1"))

        val tray = ChatTray.build(views(meteo, mailCard, teamsCard), null, null, null, now)
        assertEquals(listOf(905L), tray.accords.map { it.id })
        assertEquals(
            listOf(Route.MailDraft("d-claire"), Route.TeamsReplies),
            tray.drafts.map { it.route },
        )
        assertEquals(2, tray.draftCount)
        // le compte à rebours : l'accord le plus proche qui se décide ici (pas le brouillon qui expire avant)
        assertEquals(now + 4 * 60_000, tray.soonest)
    }

    @Test fun `ses brouillons lus et les cartes ne comptent qu'une fois, les pastilles disent au moins combien`() {
        val tray = ChatTray.build(views(meteo, mailCard, teamsCard), Counts(mail = 1, teams = 1), listOf(claire), listOf(reply), now)
        assertEquals(2, tray.draftCount)
        val (mail, teams) = tray.drafts
        assertEquals("Re: Présentation de jeudi", mail.title)
        assertEquals("→ Claire Dubois", mail.detail)
        assertEquals(Route.MailDraft("d-claire"), mail.route)
        // une réponse Teams mène à sa discussion, où sa carte rose se décide
        assertEquals(Route.TeamsThread("pro~19:abc"), teams.route)
        assertEquals("« Oui je l'ai vu, merci ! »", teams.detail)

        // les pastilles en disent plus que ce qu'on a lu : un lien vers la liste dit combien
        val more = ChatTray.build(views(meteo), Counts(mail = 3), listOf(claire), emptyList(), now)
        assertEquals(3, more.draftCount)
        assertEquals(listOf("d-claire", ""), more.drafts.map { it.id })
        assertEquals(Route.MailDrafts, more.drafts.last().route)
        assertEquals(3, more.drafts.last().count)

        // ni lues ni nommées : les pastilles seules, et le lien vers la liste
        val counted = ChatTray.build(emptyList(), Counts(teams = 2), null, null, now)
        assertEquals(2, counted.draftCount)
        assertEquals(listOf(Route.TeamsReplies), counted.drafts.map { it.route })
        assertTrue(counted.accords.isEmpty())
        assertFalse(counted.isEmpty)
    }

    @Test fun `ce qui ne t'attend pas ne se montre pas, au-delà de quatre, la liste`() {
        val refused = claire.copy(id = "d-2", state = DraftStates.REFUSED)
        val notMine = claire.copy(id = "d-3", decides = false) // une boîte qu'on te partage : son propriétaire décide
        val answered = reply.copy(id = "r-2", answered = true) // tu as répondu autrement (ADR 0199)
        val tray = ChatTray.build(emptyList(), Counts(), listOf(refused, notMine), listOf(answered), now)
        assertTrue(tray.isEmpty)

        val five = (1..5).map { claire.copy(id = "d-$it") }
        val capped = ChatTray.build(emptyList(), Counts(mail = 5), five, null, now)
        assertEquals(5, capped.draftCount)
        assertEquals(ChatTray.MAX_DRAFTS_PER_PLACE + 1, capped.drafts.size)
        assertEquals(5, capped.drafts.last().count)
    }

    @Test fun `le compte à rebours, arrondi à la minute supérieure, en ambre sous cinq minutes`() {
        assertEquals("4 min", ChatTray.countdown(now + 3 * 60_000 + 1, now))
        assertEquals("< 1 min", ChatTray.countdown(now + 30_000, now))
        assertEquals("2 h 05", ChatTray.countdown(now + (2 * 60 + 5) * 60_000L, now))
        assertEquals("1 h", ChatTray.countdown(now + 60 * 60_000L, now))
        assertEquals("3 j", ChatTray.countdown(now + 3 * 24 * 60 * 60_000L, now))
        assertNull(ChatTray.countdown(now, now))
        assertNull(ChatTray.countdown(null, now))
        assertTrue(ChatTray.urgent(now + 4 * 60_000, now))
        assertFalse(ChatTray.urgent(now + 6 * 60_000, now))
        assertFalse(ChatTray.urgent(now - 1, now))
        // une carte expirée ne compte plus
        val expired = meteo.copy(expiresAt = now - 1)
        assertNull(ChatTray.build(views(expired), null, null, null, now).soonest)
    }

    @Test fun `repliée par défaut, elle se déplie pour un accord jamais vu, pas pour un brouillon`() {
        assertEquals(setOf(905L), ChatTray.newAccords(listOf(meteo, mailCard, teamsCard), emptySet()))
        assertEquals(setOf(906L), ChatTray.newAccords(listOf(meteo, push), setOf(905L)))
        assertTrue(ChatTray.newAccords(listOf(meteo), setOf(905L)).isEmpty())
    }

    @Test fun `Tout accepter - en mode pro, une opératrice, deux accords ou plus`() {
        val two = ChatTray.build(views(meteo, push, mailCard), null, null, null, now)
        assertTrue(ChatTray.offersAcceptAll(pro = true, operator = true, tray = two))
        assertFalse(ChatTray.offersAcceptAll(pro = false, operator = true, tray = two))
        assertFalse(ChatTray.offersAcceptAll(pro = true, operator = false, tray = two))
        val one = ChatTray.build(views(meteo, mailCard), null, null, null, now)
        assertFalse(ChatTray.offersAcceptAll(pro = true, operator = true, tray = one))
    }

    @Test fun `Tout accepter ne prend que ce que Accepter permettrait, jamais un brouillon`() {
        val blocked = push.copy(id = 910, blocked = "l'outil a changé")
        val expired = push.copy(id = 911, expiresAt = now - 1)
        val cut = push.copy(id = 912, complete = false)
        val noDigest = push.copy(id = 913, digest = "")
        val waiting = push.copy(id = 914)
        val all = views(
            meteo, push, mailCard, teamsCard, blocked, expired, cut, noDigest, waiting,
            pending = mapOf(914L to PendingDecision(ApprovalDecision.ACCEPT, 99_000)),
        )
        assertEquals(listOf(905L, 906L), ChatTray.acceptAllTargets(all).map { it.id })
        // hors ligne, rien
        assertTrue(ChatTray.acceptAllTargets(views(meteo, push, online = false)).isEmpty())
    }

    @Test fun `au moment de partir, une carte qui a changé ou disparu reste à la personne`() {
        val shown = views(meteo).single()
        assertEquals(905L, ChatTray.stillAcceptable(shown, views(meteo))?.id)
        assertNull(ChatTray.stillAcceptable(shown, views(meteo.copy(digest = "9999"))))
        assertNull(ChatTray.stillAcceptable(shown, views(push)))
        assertNull(ChatTray.stillAcceptable(shown, views(meteo, online = false)))
        assertNull(ChatTray.stillAcceptable(shown, views(meteo, pending = mapOf(905L to PendingDecision(ApprovalDecision.REFUSE, 99_000)))))
    }
}
