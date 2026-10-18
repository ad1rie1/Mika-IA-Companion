package fr.qwartz.mika.ui.chat

import fr.qwartz.mika.data.chat.ChatSync
import fr.qwartz.mika.data.chat.MessageStatus
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
import fr.qwartz.mika.data.chat.WorkCard
import fr.qwartz.mika.data.chat.WorkStep
import fr.qwartz.mika.data.net.ToolUse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId

class ChatItemsTest {
    private val zone = ZoneId.of("Europe/Paris")
    private fun at(y: Int, mo: Int, d: Int, h: Int = 12) =
        LocalDateTime.of(y, mo, d, h, 0).atZone(zone).toInstant().toEpochMilli()

    private val now = at(2026, 10, 4, 21)

    private fun msg(text: String, sender: Sender, id: Long?, ts: Long, localId: Long = id ?: 0) =
        StoredMessage(text, sender, ts, id = id, localId = localId,
            status = if (sender == Sender.USER) MessageStatus.SENT else null)

    @Test fun `séparateurs de date - aujourd'hui, hier, un jour de la semaine, l'année si elle diffère`() {
        val items = ChatItems.build(
            listOf(
                msg("vieux", Sender.USER, 1, at(2025, 12, 31)),
                msg("samedi", Sender.USER, 2, at(2026, 9, 26)),
                msg("hier", Sender.MIKA, 3, at(2026, 10, 3)),
                msg("ce soir", Sender.USER, 4, at(2026, 10, 4, 20)),
            ),
            nowMs = now, zone = zone,
        )
        val labels = items.filterIsInstance<ChatItem.DateSeparator>().map { it.label }
        assertEquals(listOf("mercredi 31 décembre 2025", "samedi 26 septembre", "Hier", "Aujourd'hui"), labels)
    }

    @Test fun `un message relu plus tôt dans l'ordre ne fait pas revenir la date en arrière`() {
        val items = ChatItems.build(
            listOf(msg("a", Sender.USER, 1, at(2026, 10, 4)), msg("b", Sender.MIKA, 2, at(2026, 10, 3))),
            nowMs = now, zone = zone,
        )
        assertEquals(1, items.count { it is ChatItem.DateSeparator })
    }

    @Test fun `lu une fois que Mika a répondu après, pas avant`() {
        val items = ChatItems.build(
            listOf(
                msg("q1", Sender.USER, 1, at(2026, 10, 4)),
                msg("r1", Sender.MIKA, 2, at(2026, 10, 4)),
                msg("q2", Sender.USER, 3, at(2026, 10, 4)),
            ),
            nowMs = now, zone = zone,
        )
        val bubbles = items.filterIsInstance<ChatItem.Bubble>()
        assertTrue(bubbles[0].read)
        assertFalse(bubbles[2].read)
    }

    @Test fun `notes sous la bulle, troncature en tête, frappe en bas`() {
        val asleep = msg("tu dors ?", Sender.USER, 5, at(2026, 10, 4)).apply { waiting = ChatSync.ASLEEP }
        val partial = msg("photos", Sender.USER, 6, at(2026, 10, 4)).apply {
            note = "Non transmis à Mika : gros.png (trop volumineux)"
            replyNote = "Mika n'a pas pu répondre — réessaie."
            replyHref = "https://ailleurs.test"
        }
        val items = ChatItems.build(listOf(asleep, partial), truncated = true, typing = true, nowMs = now, zone = zone)
        assertTrue(items.first() is ChatItem.TruncatedNote)
        assertTrue(items.last() is ChatItem.Typing)
        val notes = items.filterIsInstance<ChatItem.Note>()
        assertEquals(
            listOf(ChatSync.ASLEEP_NOTE, "Non transmis à Mika : gros.png (trop volumineux)", "Mika n'a pas pu répondre — réessaie."),
            notes.map { it.text },
        )
        assertEquals(null, notes.last().href)
    }

    @Test fun `pensées et notes système rangées après le curseur de leur arrivée`() {
        val thought = StoredMessage("hmm…", Sender.MIKA, at(2026, 10, 4), after = 1, inner = true, localId = -1)
        val error = StoredMessage("Désolée…", Sender.MIKA, at(2026, 10, 4), after = 2, source = "error", localId = -2)
        val items = ChatItems.build(
            listOf(msg("a", Sender.USER, 1, at(2026, 10, 4)), msg("b", Sender.MIKA, 2, at(2026, 10, 4))),
            ephemeral = listOf(thought, error), nowMs = now, zone = zone,
        ).filter { it !is ChatItem.DateSeparator }
        assertEquals(
            listOf("Bubble", "Thought", "Bubble", "SystemNote"),
            items.map { it::class.simpleName },
        )
        assertEquals(items.size, items.map { it.key }.toSet().size)
    }

    @Test fun `libellé du jour`() {
        val today = LocalDate.of(2026, 10, 4)
        assertEquals("Aujourd'hui", ChatItems.dayLabel(today, today))
        assertEquals("Hier", ChatItems.dayLabel(today.minusDays(1), today))
        assertEquals("samedi 4 octobre 2025", ChatItems.dayLabel(LocalDate.of(2025, 10, 4), today))
    }

    @Test fun `sa réponse en plusieurs bulles - une ligne vide les sépare, la dernière porte l'heure et les fichiers`() {
        val items = ChatItems.build(
            listOf(msg("réunion à 9h\n\npas la tête à ça", Sender.USER, 1, now), msg("c'est quoi comme réunion ?\n\nen tout cas, bon courage", Sender.MIKA, 2, now)),
            nowMs = now, zone = zone,
        ).filterIsInstance<ChatItem.Bubble>()
        assertEquals(listOf("m1", "m2", "m2.1"), items.map { it.key })
        assertEquals(listOf(null, "c'est quoi comme réunion ?", "en tout cas, bon courage"), items.map { it.part })
        assertEquals(listOf(true, false, true), items.map { it.last })
    }

    @Test fun `une réponse pro est une seule bulle, ses outils relus en une ligne (ADR 0116)`() {
        val ask = msg("trouve le devis", Sender.USER, 1, now).apply { mode = "pro" }
        val reply = msg("Voilà :\n\n- le devis\n\n- la date", Sender.MIKA, 2, now).apply {
            mode = "pro"
            tools = listOf(ToolUse("email_search", true), ToolUse("email_read", false))
        }
        val bubbles = ChatItems.build(listOf(ask, reply), nowMs = now, zone = zone).filterIsInstance<ChatItem.Bubble>()
        assertEquals(listOf("m1", "m2"), bubbles.map { it.key })
        assertEquals(listOf(null, null), bubbles.map { it.part })
        assertEquals("email_search ✓ · email_read ✗", bubbles[1].toolsLine)
        assertEquals(null, bubbles[0].toolsLine)
        // sans outils, pas de ligne
        val bare = ChatItems.build(listOf(reply.copy(tools = emptyList())), nowMs = now, zone = zone)
            .filterIsInstance<ChatItem.Bubble>().single()
        assertEquals(null, bare.toolsLine)
    }

    @Test fun `sa carte de travail tient la place de « Mika écrit… », puis se replie au-dessus de sa réponse`() {
        val tool = WorkStep.Tool("t1", "email_search", "{}", ok = true)
        // le message vient de partir (pas encore d'identifiant) : la carte va en bas, sans « Mika écrit… »
        val pending = StoredMessage("trouve le devis", Sender.USER, now, cid = "c1", localId = 1, status = MessageStatus.SENT, mode = "pro")
        val live = WorkCard("e1", replyTo = 11, steps = listOf(tool))
        val during = ChatItems.build(listOf(pending), typing = true, nowMs = now, zone = zone, work = listOf(live))
            .filter { it !is ChatItem.DateSeparator }
        assertEquals(listOf("Bubble", "Work"), during.map { it::class.simpleName })
        assertEquals(false, (during.last() as ChatItem.Work).folded)

        // sa réponse est là : repliée juste au-dessus d'elle, et la ligne des outils ne s'ajoute pas
        val asked = msg("trouve le devis", Sender.USER, 11, now).apply { mode = "pro" }
        val reply = msg("Voilà le devis", Sender.MIKA, 12, now).apply {
            mode = "pro"
            tools = listOf(ToolUse("email_search", true))
        }
        val answered = live.copy(answered = true, answerId = 12)
        val after = ChatItems.build(listOf(asked, reply), typing = true, nowMs = now, zone = zone, work = listOf(answered))
            .filter { it !is ChatItem.DateSeparator }
        assertEquals(listOf("Bubble", "Work", "Bubble", "Typing"), after.map { it::class.simpleName })
        assertEquals(true, (after[1] as ChatItem.Work).folded)
        assertEquals(null, (after[2] as ChatItem.Bubble).toolsLine)
        assertEquals(after.size, after.map { it.key }.toSet().size)

        // le message a son identifiant, la réponse n'est pas encore là : la carte le suit
        val following = ChatItems.build(
            listOf(asked, msg("autre chose", Sender.USER, 13, now)), nowMs = now, zone = zone, work = listOf(live),
        ).filter { it !is ChatItem.DateSeparator }
        assertEquals(listOf("Bubble", "Work", "Bubble"), following.map { it::class.simpleName })

        // répondue mais sans plus rien où se mettre : elle ne se montre pas
        val orphan = ChatItems.build(listOf(msg("salut", Sender.USER, 40, now)), nowMs = now, zone = zone, work = listOf(answered))
        assertTrue(orphan.none { it is ChatItem.Work })
    }
}
