package fr.qwartz.mika.ui.chat

import fr.qwartz.mika.avatar3d.Utterance
import fr.qwartz.mika.data.chat.MessageAttachment
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ConversationCuesTest {
    private fun bubble(id: Long, sender: Sender, text: String, attachments: List<MessageAttachment> = emptyList()) =
        ChatItem.Bubble("m$id", StoredMessage(text, sender, ts = id, localId = id, attachments = attachments), read = false)

    private val opening = listOf(bubble(1, Sender.USER, "salut"), bubble(2, Sender.MIKA, "coucou !"))

    @Test fun `le fil vu à l'ouverture ne se récite pas`() {
        val cues = ConversationCues()
        assertNull(cues.onItems(opening, watching = true))
    }

    @Test fun `sa réponse qui arrive sous nos yeux, elle la dit — sans les marques du Markdown`() {
        val cues = ConversationCues()
        cues.onItems(opening, watching = true)
        val cue = cues.onItems(opening + bubble(3, Sender.MIKA, "c'est **vraiment** chouette"), watching = true)
        assertEquals(ConversationCues.Cue.Speak("m3", "c'est vraiment chouette"), cue)
    }

    @Test fun `un message qui part, elle le lit, pièces jointes comprises`() {
        val cues = ConversationCues()
        cues.onItems(opening, watching = true)
        val photo = MessageAttachment("photo.jpg", "image")
        val cue = cues.onItems(opening + bubble(3, Sender.USER, "regarde", listOf(photo)), watching = true)
        assertEquals(ConversationCues.Cue.Read("m3", "regarde".length + 12), cue)
    }

    @Test fun `ce qui arrive écran éteint, ou plusieurs bulles d'un coup, n'est pas une conversation en cours`() {
        val cues = ConversationCues()
        cues.onItems(opening, watching = true)
        assertNull(cues.onItems(opening + bubble(3, Sender.MIKA, "tu es là ?"), watching = false))
        // Et revenir sur l'écran ne la fait pas réciter ce qu'elle a dit en notre absence.
        assertNull(cues.onItems(opening + bubble(3, Sender.MIKA, "tu es là ?"), watching = true))
        val caughtUp = opening + bubble(3, Sender.MIKA, "tu es là ?") + bubble(4, Sender.MIKA, "bon…") + bubble(5, Sender.MIKA, "à plus")
        assertNull(cues.onItems(caughtUp, watching = true))
    }

    @Test fun `une bulle qui n'est pas la dernière du fil ne parle pas`() {
        val cues = ConversationCues()
        cues.onItems(opening, watching = true)
        val late = listOf(bubble(1, Sender.USER, "salut"), bubble(9, Sender.MIKA, "rangée plus haut"), bubble(2, Sender.MIKA, "coucou !"))
        assertNull(cues.onItems(late, watching = true))
    }

    @Test fun `lire prend un coup d'œil pour trois mots, quelques secondes au plus pour un paragraphe`() {
        assertEquals(1.1f, ConversationCues.readingSeconds(3), 1e-6f)
        assertTrue(ConversationCues.readingSeconds(60) in 2f..3.5f)
        assertEquals(3.5f, ConversationCues.readingSeconds(2_000), 1e-6f)
    }
}

class SpeechTrackTest {
    private var now = 1_000_000_000L
    private val track = SpeechTrack { now }
    private fun seconds(s: Float) = (s * 1e9f).toLong()

    @Test fun `une réplique s'écrit à son débit et finit quand tout est dit`() {
        track.say("a", "x".repeat(32))
        val u = track.of("a")!!
        assertEquals(Utterance.SPEAKING_CPS, u.charsPerSecond, 1e-6f)
        now += seconds(1f)
        assertEquals(16f, u.revealAt(now), 0.01f)
        assertEquals(16, u.cursorAt(now))
        now += seconds(1.01f)
        assertTrue(u.finished(now))
        assertEquals(32f, u.revealAt(now), 1e-6f)
    }

    @Test fun `une longue réponse accélère plutôt que de faire attendre, jusqu'à un plafond`() {
        assertEquals(Utterance.SPEAKING_CPS, Utterance.charsPerSecond(40), 1e-6f)
        assertEquals(200f / Utterance.TARGET_SECONDS, Utterance.charsPerSecond(200), 1e-4f)
        assertEquals(Utterance.MAX_CPS, Utterance.charsPerSecond(2_000), 1e-6f)
    }

    @Test fun `deux bulles coup sur coup se disent l'une après l'autre, un souffle entre les deux`() {
        track.say("a", "x".repeat(16))
        now += seconds(0.2f)
        track.say("b", "y".repeat(16))
        val a = track.of("a")!!
        val b = track.of("b")!!
        assertEquals(a.endNanos + Utterance.GAP_NANOS, b.startNanos)
        assertEquals(0f, b.revealAt(now), 0f)
    }

    @Test fun `toucher la bulle affiche tout, et la suivante vient aussitôt`() {
        track.say("a", "x".repeat(64))
        track.say("b", "y".repeat(16))
        now += seconds(1f)
        track.skip("a")
        val a = track.of("a")!!
        assertTrue(a.finished(now))
        assertEquals(64f, a.revealAt(now), 0f)
        assertEquals(now + Utterance.GAP_NANOS, track.of("b")!!.startNanos)
    }

    @Test fun `quand la personne écrit à son tour, tout ce qui reste s'affiche`() {
        track.say("a", "x".repeat(64))
        track.say("b", "y".repeat(16))
        now += seconds(0.5f)
        track.skipAll()
        assertTrue(track.utterances.all { it.finished(now) })
        assertEquals(16f, track.of("b")!!.revealAt(now), 0f)
    }

    @Test fun `une réplique finie depuis longtemps quitte la piste à la suivante`() {
        track.say("a", "x".repeat(16))
        now += seconds(10f)
        track.say("b", "y".repeat(16))
        assertNull(track.of("a"))
        assertEquals(now, track.of("b")!!.startNanos)
    }
}
