package fr.qwartz.mika.service

import fr.qwartz.mika.data.chat.ChatEvent
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NotificationPolicyTest {
    private val background = NotificationPolicy.Context(foreground = false, lastReadId = 10, lastNotifiedId = 12, cursorBefore = 12)
    private fun mika(id: Long?, text: String = "coucou", inner: Boolean = false) =
        StoredMessage(text, Sender.MIKA, 0, id = id, inner = inner)

    @Test fun `une nouvelle parole de Mika, app en arrière-plan`() {
        assertTrue(NotificationPolicy.shouldNotify(mika(13), background))
    }

    @Test fun `jamais au premier plan`() {
        assertFalse(NotificationPolicy.shouldNotify(mika(13), background.copy(foreground = true)))
    }

    @Test fun `ni un murmure, ni un message vide, ni ses propres messages`() {
        assertFalse(NotificationPolicy.shouldNotify(mika(13, inner = true), background))
        assertFalse(NotificationPolicy.shouldNotify(mika(13, text = "  "), background))
        assertFalse(NotificationPolicy.shouldNotify(StoredMessage("moi", Sender.USER, 0, id = 13), background))
    }

    @Test fun `rien de déjà lu ou déjà notifié, rien sans identifiant`() {
        assertFalse(NotificationPolicy.shouldNotify(mika(12), background))
        assertFalse(NotificationPolicy.shouldNotify(mika(10), background.copy(lastNotifiedId = 0)))
        assertFalse(NotificationPolicy.shouldNotify(mika(null), background))
    }

    @Test fun `pas la toute première synchronisation`() {
        assertFalse(NotificationPolicy.shouldNotify(mika(13), background.copy(cursorBefore = 0)))
    }

    @Test fun `pas la réponse à une question posée depuis un autre appareil`() {
        val own = setOf("c1")
        assertTrue(NotificationPolicy.isReplyToOtherDevice("c-web-9") { it in own })
        assertFalse(NotificationPolicy.isReplyToOtherDevice("c1") { it in own })
        assertFalse(NotificationPolicy.isReplyToOtherDevice(null) { it in own })
        assertFalse(NotificationPolicy.shouldNotify(mika(13), background, replyToOtherDevice = true))
    }

    @Test fun `un rattrapage, une notification - les cinq dernières lignes et le reste compté`() {
        val s = NotificationPolicy.summarize((1..8).map { "m$it" })
        assertEquals(listOf("m4", "m5", "m6", "m7", "m8"), s.lines)
        assertEquals(3, s.more)
        assertEquals(0, NotificationPolicy.summarize(listOf("seul")).more)
    }

    private fun spoke(vararg ids: Long, live: Boolean = false, cid: String? = null, before: Long = 12, elsewhere: Set<Long> = emptySet()) =
        ChatEvent.MikaSpoke(ids.map { mika(it, "m$it") }, live, cid, before, elsewhere)

    @Test fun `le plan - ce qui est nouveau est notifié, le dernier notifié avance`() {
        val plan = NotificationPolicy.plan(spoke(13, 14, live = true, cid = "c1"), background) { it == "c1" }
        assertEquals(listOf(13L, 14L), plan.notify.map { it.id })
        assertEquals(14L, plan.lastNotifiedId)
        assertFalse(plan.alertOnce)
    }

    @Test fun `le dernier notifié avance même quand rien n'est notifié`() {
        // Au premier plan, à la première synchronisation, en réponse à un autre appareil : écarté pour de bon.
        val foreground = NotificationPolicy.plan(spoke(20), background.copy(foreground = true)) { false }
        assertTrue(foreground.notify.isEmpty())
        assertEquals(20L, foreground.lastNotifiedId)
        val first = NotificationPolicy.plan(spoke(30, 31, before = 0), background.copy(lastNotifiedId = 0)) { false }
        assertTrue(first.notify.isEmpty())
        assertEquals(31L, first.lastNotifiedId)
        val other = NotificationPolicy.plan(spoke(40, live = true, cid = "c-web"), background) { false }
        assertTrue(other.notify.isEmpty())
        assertEquals(40L, other.lastNotifiedId)
    }

    @Test fun `le dernier notifié ne recule jamais`() {
        val plan = NotificationPolicy.plan(spoke(5), background.copy(lastNotifiedId = 50)) { false }
        assertEquals(50L, plan.lastNotifiedId)
        assertTrue(plan.notify.isEmpty())
    }

    @Test fun `un rattrapage - une seule mise à jour, sans resonner, sans les réponses faites ailleurs`() {
        val plan = NotificationPolicy.plan(spoke(13, 15, 16, elsewhere = setOf(15)), background) { false }
        assertEquals(listOf(13L, 16L), plan.notify.map { it.id })
        assertTrue(plan.alertOnce)
        assertEquals(16L, plan.lastNotifiedId)
    }

    @Test fun `elle écrit la première - pas de corrélation, notifié`() {
        val plan = NotificationPolicy.plan(spoke(13, live = true, cid = null), background) { false }
        assertEquals(listOf(13L), plan.notify.map { it.id })
    }

    @Test fun `les lignes de la notification - sans doublon, dans l'ordre, sans le lu`() {
        val shown = listOf(NotificationPolicy.Line(13, "a", 1), NotificationPolicy.Line(14, "b", 2))
        val merged = NotificationPolicy.merge(shown, listOf(mika(16, "d"), mika(14, "b"), mika(15, "c")), lastReadId = 13)
        assertEquals(listOf(14L, 15L, 16L), merged.map { it.id })
        assertEquals(listOf("b", "c", "d"), merged.map { it.text })
    }

    @Test fun `les lignes gardées sont bornées`() {
        val many = (1L..80L).map { mika(it, "m$it") }
        val merged = NotificationPolicy.merge(emptyList(), many, lastReadId = 0)
        assertEquals(NotificationPolicy.MAX_KEPT, merged.size)
        assertEquals(80L, merged.last().id)
        val s = NotificationPolicy.summarize(merged.map { it.text })
        assertEquals(listOf("m76", "m77", "m78", "m79", "m80"), s.lines)
        assertEquals(NotificationPolicy.MAX_KEPT - 5, s.more)
    }

    // ── ADR 0077 : ce que Firebase apporte, app fermée ──

    private val closed = NotificationPolicy.PushContext(foreground = false, online = false, lastReadId = 10, cursor = 12, pushed = emptySet())

    @Test fun `une parole venue par Firebase - app fermee, ou ouverte sans connexion`() {
        assertTrue(NotificationPolicy.shouldNotifyPush(13, closed))
        assertTrue(NotificationPolicy.shouldNotifyPush(13, closed.copy(foreground = true)))  // hors de chez soi, app ouverte
        assertFalse(NotificationPolicy.shouldNotifyPush(13, closed.copy(foreground = true, online = true)))  // la connexion l'apporte
    }

    @Test fun `une parole venue par Firebase - jamais lue, deja dans le fil, ni deja notifiee par Firebase`() {
        assertFalse(NotificationPolicy.shouldNotifyPush(12, closed))  // la connexion l'a apportée
        assertFalse(NotificationPolicy.shouldNotifyPush(10, closed.copy(cursor = 0)))  // lue
        assertFalse(NotificationPolicy.shouldNotifyPush(13, closed.copy(pushed = setOf(13))))
    }

    @Test fun `Firebase dans le desordre - le message d'avant arrive apres, il est notifie quand meme`() {
        var pushed = emptyList<Long>()
        for (id in listOf(101L, 100L)) {
            assertTrue(NotificationPolicy.shouldNotifyPush(id, closed.copy(pushed = pushed.toSet())))
            pushed = NotificationPolicy.rememberPushed(pushed, id)
        }
        assertFalse(NotificationPolicy.shouldNotifyPush(100, closed.copy(pushed = pushed.toSet())))  // un doublon
        val many = (1L..250L).fold(emptyList<Long>()) { acc, id -> NotificationPolicy.rememberPushed(acc, id) }
        assertEquals(NotificationPolicy.MAX_PUSHED, many.size)
        assertEquals(250L, many.last())
    }

    @Test fun `la conversation ouverte ne garde que ce que le fil n'a pas encore`() {
        val lines = listOf(NotificationPolicy.Line(20, "vue", 0), NotificationPolicy.Line(21, "pas encore", 0))
        assertEquals(listOf(21L), NotificationPolicy.unseen(lines, cursor = 20).map { it.id })
        assertEquals(emptyList<NotificationPolicy.Line>(), NotificationPolicy.unseen(lines, cursor = 30))
    }

    @Test fun `marquer comme lu va jusqu'a ce que la notification montrait`() {
        val lines = listOf(NotificationPolicy.Line(25, "venue par Firebase", 0))
        assertEquals(25L, NotificationPolicy.readUpTo(lines, cursor = 20))
        assertEquals(30L, NotificationPolicy.readUpTo(lines, cursor = 30))
        assertEquals(20L, NotificationPolicy.readUpTo(emptyList(), cursor = 20))
    }

    @Test fun `les lignes venues par Firebase se melangent sans doublon`() {
        val shown = listOf(NotificationPolicy.Line(13, "a", 1))
        val merged = NotificationPolicy.mergeLines(shown, listOf(NotificationPolicy.Line(14, "b", 2), NotificationPolicy.Line(13, "a", 1)), lastReadId = 10)
        assertEquals(listOf(13L, 14L), merged.map { it.id })
    }
}
