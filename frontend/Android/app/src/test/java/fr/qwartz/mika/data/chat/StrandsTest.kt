package fr.qwartz.mika.data.chat

import fr.qwartz.mika.data.net.MikaProtocol
import fr.qwartz.mika.data.net.StrandInfo
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

/** Les fils de travail du mode pro (ADR 0164), sans écran : identifiants, liste, nom, commandes du champ. */
class StrandsTest {
    @Test fun `un identifiant neuf est accepté par le serveur, et deux de suite diffèrent`() {
        val random = Random(7)
        val a = Strands.newId(1_790_000_000_000, random)
        val b = Strands.newId(1_790_000_000_000, random)
        assertTrue(a, MikaProtocol.STRAND_ID.matches(a) && a.startsWith("s"))
        assertTrue(a != b)
        assertTrue(Strands.isValidId(a))
        assertFalse(Strands.isValidId("pas un id !"))
        assertFalse(Strands.isValidId("x".repeat(41)))
        assertFalse(Strands.isValidId(null))
    }

    @Test fun `les commandes du champ, et le reste part tel quel`() {
        assertEquals(Strands.Command.Clear, Strands.parse("/clear"))
        assertEquals(Strands.Command.Clear, Strands.parse("  /nouveau  "))
        assertEquals(Strands.Command.Rename("Devis IN"), Strands.parse("/renommer   Devis IN"))
        assertEquals(Strands.Command.Rename(""), Strands.parse("/renommer"))
        assertEquals(Strands.Command.Describe("Le commercial d'IN\nmontants HT"),
            Strands.parse("/description Le commercial d'IN\nmontants HT"))
        assertEquals(Strands.Command.Archive, Strands.parse("/archiver"))
        assertEquals(Strands.Command.Unarchive, Strands.parse("/désarchiver"))
        assertEquals(Strands.Command.Unarchive, Strands.parse("/DESARCHIVER"))
        assertEquals(Strands.Command.Help, Strands.parse("/aide"))
        assertEquals(Strands.Command.Unknown("/supprime"), Strands.parse("/supprime tout"))
        // un message ordinaire, et l'échappement : un seul slash part
        assertNull(Strands.parse("liste moi les devis"))
        assertNull(Strands.parse("//clear n'est pas une commande"))
        assertEquals("/clear n'est pas une commande", Strands.unescape("//clear n'est pas une commande"))
        assertEquals("a/b", Strands.unescape("a/b"))
    }

    @Test fun `le nom d'un fil - son titre, sinon le début de son premier message`() {
        assertEquals("Devis IN", Strands.label(StrandInfo("s1", title = "  Devis IN ", opener = "liste")))
        assertEquals("liste moi les devis", Strands.label(StrandInfo("s1", opener = "liste  moi\nles devis")))
        val long = Strands.label(StrandInfo("s1", opener = "a".repeat(100)))!!
        assertEquals(48, long.length)
        assertTrue(long.endsWith("…"))
        assertNull(Strands.label(StrandInfo("s1")))
        assertNull(Strands.label(null))
    }

    @Test fun `la liste - le serveur, puis ce qu'il ne connaît pas encore, du plus récent au plus ancien`() {
        val server = listOf(
            StrandInfo("devis", title = "Devis", count = 4, lastAt = 300),
            StrandInfo("code", count = 2, lastAt = 100, archived = true),
        )
        val messages = listOf(
            StoredMessage("ordinaire", Sender.USER, 50, id = 1),
            StoredMessage("dans devis", Sender.USER, 60, id = 2, strand = "devis"),
            // un fil dont les messages sont là avant sa liste : nommé par son premier message à elle
            StoredMessage("trouve le bug", Sender.USER, 200, id = 9, strand = "bug"),
            StoredMessage("Voilà.", Sender.MIKA, 210, id = 10, strand = "bug"),
        )
        val shown = Strands.visible(server, messages, active = "neuf", nowMs = 400)
        assertEquals(listOf("neuf", "devis", "bug", "code"), shown.map { it.id })
        val bug = shown.first { it.id == "bug" }
        assertEquals(2, bug.count)
        assertEquals("trouve le bug", bug.opener)
        assertEquals(0, shown.first { it.id == "neuf" }.count)
        // un fil connu du serveur ne se double pas, même actif ; sans fil actif, rien de neuf
        assertEquals(listOf("devis", "bug", "code"), Strands.visible(server, messages, "devis", 400).map { it.id })
        assertEquals(2, Strands.localCount(messages, "bug"))
    }
}
