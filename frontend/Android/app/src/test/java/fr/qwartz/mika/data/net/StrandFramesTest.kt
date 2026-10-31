package fr.qwartz.mika.data.net

import fr.qwartz.mika.core.MikaJson
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Les trames des fils de travail (ADR 0164), telles que `adapters/web/protocol.py` les écrit et que
 * `docs/protocole-chat.md` les décrit : la liste `strands`, le sort d'un réglage, le fil sur une parole, une ligne
 * d'historique ou une trame d'outil ; et ce que l'app envoie.
 */
class StrandFramesTest {
    private fun obj(text: String): JsonObject = MikaJson.parseToJsonElement(text).jsonObject

    @Test fun `la liste de ses fils, une entrée mal formée écartée seule`() {
        val f = FrameCodec.decode(
            """{"type":"strands","items":[
              {"id":"s1mx4k2","title":"Devis IN","description":"montants HT","archived":false,"count":12,
               "first_at":1790601612771,"last_at":1790605212771,"opener":"liste moi les devis"},
              {"id":"pas un id !","title":"x"},
              {"id":"s1mx4k2","title":"doublon"},
              {"id":"code","archived":true,"count":"beaucoup"},
              "pas un objet"
            ]}""",
        ) as ServerFrame.Strands
        assertEquals(listOf("s1mx4k2", "code"), f.items.map { it.id })
        val devis = f.items[0]
        assertEquals("Devis IN", devis.title)
        assertEquals("montants HT", devis.description)
        assertEquals(12, devis.count)
        assertEquals(1790605212771L, devis.lastAt)
        assertEquals("liste moi les devis", devis.opener)
        val code = f.items[1]
        assertTrue(code.archived)
        assertEquals(0, code.count)
        // sans liste lisible, la trame est inconnue : la liste affichée ne se vide pas
        assertTrue(FrameCodec.decode("""{"type":"strands","items":"cassé"}""") is ServerFrame.Unknown)
    }

    @Test fun `le sort d'un réglage`() {
        assertEquals(
            ServerFrame.StrandResult("s1", "forbidden"),
            FrameCodec.decode("""{"type":"strand_result","id":"s1","status":"forbidden"}"""),
        )
        assertTrue(FrameCodec.decode("""{"type":"strand_result","id":"!","status":"ok"}""") is ServerFrame.Unknown)
    }

    @Test fun `le fil d'une parole, d'une ligne d'historique et d'une trame d'outil - un identifiant invalide vaut le fil avec elle`() {
        val pro = FrameCodec.decode("""{"type":"speech","text":"Voilà.","mode":"pro","strand":"devis-1","message_id":4}""")
            as ServerFrame.Speech
        assertEquals("devis-1", pro.strand)
        val bad = FrameCodec.decode("""{"type":"speech","text":"Voilà.","strand":"pas un id"}""") as ServerFrame.Speech
        assertNull(bad.strand)
        assertEquals("Voilà.", bad.text)
        val history = FrameCodec.decode(
            """{"type":"history","mode":"catchup","last_id":5,"messages":[
              {"id":4,"role":"user","text":"liste","mode":"pro","strand":"devis-1"},
              {"id":5,"role":"assistant","text":"salut"}]}""",
        ) as ServerFrame.History
        assertEquals(listOf("devis-1", null), history.messages!!.map { it.strand })
        val tool = FrameCodec.decode(
            """{"type":"tool","episode":"e1","reply_to":4,"phase":"start","call_id":"t1","name":"x","strand":"devis-1"}""",
        ) as ServerFrame.Tool
        assertEquals("devis-1", tool.strand)
    }

    @Test fun `la réponse à strand_history - son fil, et s'il en reste`() {
        val f = FrameCodec.decode(
            """{"type":"history","mode":"strand","strand":"devis-1","more":true,"last_id":5,"life":"a41f",
               "messages":[{"id":4,"role":"user","text":"liste","strand":"devis-1"}]}""",
        ) as ServerFrame.History
        assertTrue(f.isStrand)
        assertFalse(f.isInitial)
        assertEquals("devis-1", f.strand)
        assertTrue(f.more)
        assertEquals("devis-1", f.messages!!.single().strand)
    }

    @Test fun `ce que l'app envoie - un réglage entier, borné, et une demande d'historique`() {
        val set = obj(FrameCodec.strand("s1", "  Devis IN  ", "x".repeat(2100), archived = true))
        assertEquals("strand", (set["type"] as JsonPrimitive).content)
        assertEquals("s1", (set["id"] as JsonPrimitive).content)
        assertEquals("Devis IN", (set["title"] as JsonPrimitive).content)
        assertEquals(2000, (set["description"] as JsonPrimitive).content.length)
        assertEquals(true, (set["archived"] as JsonPrimitive).booleanOrNull)
        val ask = obj(FrameCodec.strandHistory("s1"))
        assertEquals("strand_history", (ask["type"] as JsonPrimitive).content)
        assertFalse("before" in ask)
        assertEquals(812L, (obj(FrameCodec.strandHistory("s1", 812))["before"] as JsonPrimitive).longOrNull)
    }

    @Test fun `un message de travail porte son fil, seulement en mode pro`() {
        val pro = obj(ChatFrameWriter.render("liste", "c1", emptyList(), MikaProtocol.CHAT_MODE_PRO, "devis-1"))
        assertEquals("pro", (pro["mode"] as JsonPrimitive).content)
        assertEquals("devis-1", (pro["strand"] as JsonPrimitive).content)
        // sans le mode pro, le serveur l'ignorerait : il ne part pas ; un identifiant invalide non plus
        assertFalse("strand" in obj(ChatFrameWriter.render("salut", "c2", emptyList(), null, "devis-1")))
        assertFalse("strand" in obj(ChatFrameWriter.render("x", "c3", emptyList(), MikaProtocol.CHAT_MODE_PRO, "a b")))
        // la taille annoncée est celle de la trame écrite
        val text = ChatFrameWriter.render("liste é", "c1", emptyList(), MikaProtocol.CHAT_MODE_PRO, "devis-1")
        assertEquals(
            text.toByteArray(Charsets.UTF_8).size.toLong(),
            ChatFrameWriter.frameBytes("liste é", "c1", emptyList(), MikaProtocol.CHAT_MODE_PRO, "devis-1"),
        )
    }
}
