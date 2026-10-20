package fr.qwartz.mika.data.phone

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** La file (ADR 0120) : bornée (les plus anciens tombent), dédoublonnée, partie par lots dans l'ordre d'arrivée. */
class PhoneQueueTest {
    private fun msg(i: Int, text: String = "message $i") =
        PhoneMessage(id = "id$i", app = "whatsapp", thread = "t", text = text, time = i.toLong())

    @Test fun `les messages s'ajoutent dans l'ordre, une seule fois`() {
        val a = PhoneQueue.add(PhoneQueueState(), listOf(msg(1), msg(2), msg(2)))
        assertEquals(2, a.added)
        assertEquals(listOf("id1", "id2"), a.state.messages.map { it.id })
        val b = PhoneQueue.add(a.state, listOf(msg(2), msg(3)))
        assertEquals(1, b.added)
        assertEquals(listOf("id1", "id2", "id3"), b.state.messages.map { it.id })
    }

    @Test fun `un message parti ne repart pas quand la notification le redit`() {
        val a = PhoneQueue.add(PhoneQueueState(), listOf(msg(1), msg(2))).state
        val sent = PhoneQueue.without(a, setOf("id1", "id2"))
        assertTrue(sent.messages.isEmpty())
        val again = PhoneQueue.add(sent, listOf(msg(1), msg(2), msg(3)))
        assertEquals(1, again.added)
        assertEquals(listOf("id3"), again.state.messages.map { it.id })
    }

    @Test fun `au-delà de 500 les plus anciens tombent`() {
        var s = PhoneQueueState()
        s = PhoneQueue.add(s, (1..450).map { msg(it) }).state
        s = PhoneQueue.add(s, (451..520).map { msg(it) }).state
        assertEquals(PhoneQueue.MAX_MESSAGES, s.messages.size)
        assertEquals("id21", s.messages.first().id)
        assertEquals("id520", s.messages.last().id)
    }

    @Test fun `la file tient aussi en caractères`() {
        val big = "x".repeat(4_000)
        val s = PhoneQueue.add(PhoneQueueState(), (1..150).map { msg(it, big) }).state
        assertTrue(s.messages.sumOf { it.text.length } <= PhoneQueue.MAX_CHARS)
        assertEquals("id150", s.messages.last().id)
        assertEquals(100, s.messages.size)
    }

    @Test fun `les lots partent par 200, les plus anciens d'abord`() {
        val s = PhoneQueue.add(PhoneQueueState(), (1..450).map { msg(it) }).state
        val batch = PhoneQueue.batch(s)
        assertEquals(PhoneQueue.BATCH, batch.size)
        assertEquals("id1", batch.first().id)
        val next = PhoneQueue.batch(PhoneQueue.without(s, batch.map { it.id }.toSet()))
        assertEquals("id201", next.first().id)
    }

    @Test fun `le dernier sort d'une proposition l'emporte`() {
        var s = PhoneQueue.settle(PhoneQueueState(), PhoneSettled(1, "ignored"))
        s = PhoneQueue.settle(s, PhoneSettled(2, "sent"))
        s = PhoneQueue.settle(s, PhoneSettled(1, "copied", "no_action"))
        assertEquals(listOf(PhoneSettled(2, "sent"), PhoneSettled(1, "copied", "no_action")), s.settled)
        // un sort redit pendant l'envoi survit à l'accusé de l'ancien
        val batch = PhoneQueue.settledBatch(s)
        s = PhoneQueue.settle(s, PhoneSettled(2, "other"))
        assertEquals(listOf(PhoneSettled(2, "other")), PhoneQueue.withoutSettled(s, batch).settled)
    }
}
