package fr.qwartz.mika.ui.chat

import fr.qwartz.mika.data.chat.MessageAttachment
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId

/** « Fichiers échangés » (ADR 0215) : les siens et les tiens, tant qu'ils sont gardés. */
class ExchangedFilesTest {
    private val zone = ZoneId.of("Europe/Paris")
    private fun at(h: Int, m: Int) = LocalDateTime.of(2026, 11, 17, h, m).atZone(zone).toInstant().toEpochMilli()
    private val now = at(15, 0)
    private val idA = "a".repeat(32)
    private val idB = "b".repeat(32)
    private val idC = "c".repeat(32)

    private val hers = StoredMessage("voilà", Sender.MIKA, at(13, 32), id = 2, localId = 2).apply {
        attachments = listOf(
            MessageAttachment("comparaison-devis.csv", "file", "text/csv", 4_096, id = idA, url = "/files/$idA", available = true),
            MessageAttachment("corneilles.png", "image", "image/png", 80_000, id = idB, url = "/files/$idB", available = false),
        )
    }
    private val mine = StoredMessage("regarde [tableau-blanc.jpg]", Sender.USER, at(14, 5), id = 3, localId = 3, cid = "c3").apply {
        attachments = listOf(MessageAttachment("tableau-blanc.jpg", "image", "image/jpeg", 1_800_000, local = "tableau-blanc.jpg"))
    }
    private val kept = StoredMessage("le devis [devis.pdf]", Sender.USER, at(13, 31), id = 1, localId = 1).apply {
        attachments = listOf(MessageAttachment("devis.pdf", "file", "application/pdf", 212_000, id = idC, url = "/files/$idC", available = true))
    }
    // une pièce d'un autre appareil, sans de quoi la reprendre : rien à lister
    private val bare = StoredMessage("vieux [scan.pdf]", Sender.USER, at(9, 0), id = 0, localId = 9).apply {
        attachments = listOf(MessageAttachment("scan.pdf"))
    }

    @Test fun `les siens et les tiens, le plus récent d'abord, ce qui ne se reprend pas ne se liste pas`() {
        val all = ExchangedFiles.of(listOf(kept, hers, mine, bare))
        assertEquals(listOf("tableau-blanc.jpg", "comparaison-devis.csv", "corneilles.png", "devis.pdf"), all.map { it.att.name })
        val (photo, csv, crows, pdf) = all
        assertTrue(photo.image && !photo.hers && photo.local && !photo.fetchable)
        assertTrue(csv.hers && csv.fetchable && !csv.image)
        assertTrue(crows.removed && !crows.fetchable)
        assertTrue(pdf.fetchable && !pdf.hers)
        assertEquals(all.size, all.map { it.key }.toSet().size)
    }

    @Test fun `les puces - tout, les siens, les tiens`() {
        val all = ExchangedFiles.of(listOf(kept, hers, mine))
        assertEquals(4, ExchangedFiles.filter(all, FilesChip.ALL).size)
        assertEquals(listOf("comparaison-devis.csv", "corneilles.png"), ExchangedFiles.filter(all, FilesChip.HERS).map { it.att.name })
        assertEquals(listOf("tableau-blanc.jpg", "devis.pdf"), ExchangedFiles.filter(all, FilesChip.YOURS).map { it.att.name })
    }

    @Test fun `ce qu'en dit sa ligne - taille, de qui, quand, et s'il n'est plus là`() {
        val all = ExchangedFiles.of(listOf(kept, hers, mine))
        val byName = all.associateBy { it.att.name }
        assertEquals("4 Ko · Mika · aujourd'hui 13:32", ExchangedFiles.detail(byName.getValue("comparaison-devis.csv"), now, zone))
        assertEquals("207 Ko · toi · aujourd'hui 13:31", ExchangedFiles.detail(byName.getValue("devis.pdf"), now, zone))
        assertTrue(ExchangedFiles.detail(byName.getValue("corneilles.png"), now, zone).endsWith("plus disponible"))
        assertTrue(ExchangedFiles.detail(byName.getValue("tableau-blanc.jpg"), now, zone).endsWith("sur ce téléphone seulement"))
        assertFalse(ExchangedFiles.detail(byName.getValue("devis.pdf"), now, zone).contains("seulement"))
    }
}
