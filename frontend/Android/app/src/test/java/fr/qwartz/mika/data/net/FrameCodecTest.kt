package fr.qwartz.mika.data.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Les trames telles que `adapters/web/protocol.py` les écrit (fixtures sous `resources/frames/`). */
class FrameCodecTest {
    private fun fixture(name: String): String =
        requireNotNull(javaClass.classLoader?.getResource("frames/$name")) { "fixture $name" }.readText()

    private inline fun <reified T : ServerFrame> decode(name: String): T {
        val frame = FrameCodec.decode(fixture(name))
        assertTrue("$name → $frame", frame is T)
        return frame as T
    }

    @Test fun `une parole complète`() {
        val s = decode<ServerFrame.Speech>("speech.json")
        assertEquals("Coucou ! [LAUGH] Tu m'as manqué.", s.text)
        assertEquals("happy", s.emotion)
        assertEquals(0.72, s.emotionIntensity, 1e-9)
        assertEquals(listOf(BlendPart("happy", 0.8), BlendPart("playful", 0.35)), s.emotionBlend)
        assertEquals(42L, s.messageId)
        assertEquals(41L, s.userMessageId)
        assertEquals("cabc-1", s.clientMsgId)
        assertFalse(s.isInner)
        assertTrue(s.attachments.isEmpty())
    }

    @Test fun `une pensée à voix haute n'a pas d'identifiant`() {
        val s = decode<ServerFrame.Speech>("speech_inner.json")
        assertTrue(s.isInner)
        assertNull(s.messageId)
        assertNull(s.clientMsgId)
    }

    @Test fun `elle dort — une parole sans texte rattachée au message`() {
        val s = decode<ServerFrame.Speech>("speech_asleep.json")
        assertEquals("", s.text)
        assertEquals(MikaProtocol.VOICE_REASON_ASLEEP, s.voiceReason)
        assertEquals(57L, s.userMessageId)
        assertEquals("cnuit-3", s.clientMsgId)
    }

    @Test fun `la réponse de repli vient de la machine`() {
        val s = decode<ServerFrame.Speech>("speech_error.json")
        assertEquals(MikaProtocol.SOURCE_ERROR, s.source)
        assertNull(s.messageId)
    }

    @Test fun `les fichiers de Mika arrivent avec la parole`() {
        val s = decode<ServerFrame.Speech>("speech_files.json")
        val f = s.attachments.single()
        assertEquals("0123456789abcdef0123456789abcdef", f.id)
        assertEquals("courses.md", f.name)
        assertEquals("text/markdown", f.mime)
        assertEquals(312L, f.size)
        assertEquals("/files/0123456789abcdef0123456789abcdef", f.url)
        assertEquals(true, f.available)
    }

    @Test fun `un historique garde ses lignes lisibles et écarte la ligne cassée`() {
        val h = decode<ServerFrame.History>("history.json")
        assertTrue(h.isInitial)
        val messages = h.messages!!
        assertEquals(listOf(10L, 11L), messages.map { it.id })
        assertEquals("a1b2c3d4e5f60708", h.life)
        assertTrue(h.truncated)
        assertFalse(h.reset)
        assertEquals(11L, h.lastId)
        assertEquals(1759572002000.5, messages[1].ts!!, 1e-3)
        assertEquals(listOf(AttachmentRef(name = "chat.png", kind = "image")), messages[0].attachments)
        assertEquals(false, messages[1].attachments.single().available)
    }

    @Test fun `un historique sans liste de messages reste un historique`() {
        val h = FrameCodec.decode("""{"type":"history","mode":"catchup","last_id":3}""") as ServerFrame.History
        assertNull(h.messages)
        assertEquals(3L, h.lastId)
    }

    @Test fun `un accusé porte ce qui a été écarté`() {
        val a = decode<ServerFrame.Ack>("ack_rejected.json")
        assertEquals("c42", a.clientMsgId)
        assertEquals("accepted", a.status)
        assertEquals(
            listOf(RejectedAttachment("gros.png", "too_large"), RejectedAttachment("6e.pdf", "too_many")),
            a.rejectedAttachments,
        )
    }

    @Test fun `un second accusé dit pourquoi la réponse ne viendra pas`() {
        val a = decode<ServerFrame.Ack>("ack_no_reply.json")
        assertEquals("no_reply", a.status)
        assertEquals("no_model", a.reason)
        assertEquals("/inspecteur/reglages/fournisseurs", a.href)
        assertNotNull(a.detail)
    }

    @Test fun `une humeur entre deux tours`() {
        val e = decode<ServerFrame.EmotionUpdate>("emotion_update.json")
        assertEquals("curious", e.emotion)
        assertEquals(0.41, e.emotionIntensity, 1e-9)
        assertEquals(2, e.emotionBlend.size)
    }

    @Test fun `un état intérieur complet`() {
        val s = decode<ServerFrame.InnerStateUpdate>("inner_state_full.json").state
        assertEquals("awake", s.sleepPhase)
        assertEquals(0.734, s.energy!!, 1e-9)
        assertEquals("desk", s.place)
        val circadian = s.circadian!!
        assertEquals("evening", circadian.phase)
        assertEquals(21.0, circadian.hour, 0.0)
        assertEquals(0.9, s.drives!!["curiosity"]!!.tension, 1e-9)
        assertEquals(0.62, s.estime!!, 1e-9)
        assertEquals(true, s.personScope)
        assertEquals("Adrien", s.identity!!.knownAs)
        assertEquals("Son journal d'hier", s.todayJournal!!.title)
        assertEquals("associative", s.lastDream!!.dreamType)
        assertEquals("Je suis quelqu'un qui…", s.selfNarrative!!.content)
        assertEquals("impersonnel", s.projects!!.single().modeLabel)
        assertEquals("friend", s.personProfile!!.closeness)
        assertEquals(listOf("Lui envoyer le lien"), s.pendingCommitments)
        assertTrue(s.malformed.isEmpty())
    }

    @Test fun `un état intérieur minimal ne parle de personne`() {
        val s = decode<ServerFrame.InnerStateUpdate>("inner_state_minimal.json").state
        assertEquals("rem", s.sleepPhase)
        assertEquals(false, s.personScope)
        assertNull(s.identity)
        assertNull(s.todayJournal)
        assertEquals(emptyList<Rumination>(), s.ruminations)
    }

    @Test fun `une section malformée est isolée, le reste du panneau passe`() {
        val s = decode<ServerFrame.InnerStateUpdate>("inner_state_malformed.json").state
        assertEquals("deep_sleep", s.sleepPhase)
        assertNull(s.energy)
        assertNull(s.circadian)
        assertNull(s.drives)
        assertEquals(setOf("energy", "circadian", "drives"), s.malformed)
        assertEquals("ok", s.ruminations!!.single().summary)
        assertEquals("Toujours là.", s.selfNarrative!!.content)
    }

    @Test fun `un type inconnu est ignoré, pas fatal`() {
        assertEquals(ServerFrame.Unknown("avatar_state"), FrameCodec.decode("""{"type":"avatar_state","state":{}}"""))
    }

    @Test fun `une trame d'un type connu mais illisible devient inconnue`() {
        assertEquals(ServerFrame.Unknown("ack"), FrameCodec.decode("""{"type":"ack","client_msg_id":{"x":1}}"""))
    }

    @Test fun `sans type ou sans JSON, rien`() {
        assertNull(FrameCodec.decode("{pas du json"))
        assertNull(FrameCodec.decode("""{"text":"sans type"}"""))
        assertNull(FrameCodec.decode("""[1,2]"""))
        assertNull(FrameCodec.decode("""{"type":3}"""))
        assertNull(FrameCodec.decode(""))
    }

    @Test fun `un pong renvoie l'heure telle quelle`() {
        assertEquals(ServerFrame.Pong(1.7e12), FrameCodec.decode("""{"type":"pong","t":1700000000000}"""))
        assertEquals(ServerFrame.Pong(null), FrameCodec.decode("""{"type":"pong","t":null}"""))
    }

    @Test fun `les trames de contrôle du client, au JSON exact`() {
        assertEquals("""{"type":"sync","after_id":42}""", FrameCodec.sync(42))
        assertEquals("""{"type":"ping","t":1700000000123}""", FrameCodec.ping(1_700_000_000_123))
        assertEquals("""{"type":"presence","here":true}""", FrameCodec.presence(true))
        assertEquals("""{"type":"presence","here":false}""", FrameCodec.presence(false))
    }
}
