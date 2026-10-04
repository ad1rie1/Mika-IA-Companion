package fr.qwartz.mika.data.files

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class OutboxFilesTest {
    @get:Rule val folder = TemporaryFolder()

    private fun staged(name: String, bytes: Int): StagedFile {
        val f = File.createTempFile("stage", ".bin", folder.root)
        f.writeBytes(ByteArray(bytes) { 7 })
        return StagedFile(name, "image/png", f.absolutePath, bytes.toLong())
    }

    @Test fun `les fichiers suivent leur message, de la file à l'envoyé`() {
        val files = OutboxFiles(folder.newFolder("app"))
        val s = staged("photo.png", 10)
        val adopted = files.adopt("c1", listOf(s, staged("photo.png", 5)))
        assertEquals(listOf("photo.png", "photo (2).png"), adopted.map { it.file })
        assertFalse(File(s.path).exists())
        assertEquals(10L, files.locate("c1", "photo.png")!!.length())
        files.release("c1")
        assertTrue(files.locate("c1", "photo.png")!!.path.contains("/sent/"))
        assertEquals(10, files.open("c1", "photo.png").use { it.readBytes() }.size)
    }

    @Test fun `un nom ne sort jamais de son dossier`() {
        assertEquals("passwd", OutboxFiles.sanitize("../../etc/passwd"))
        assertEquals("fichier", OutboxFiles.sanitize("..."))
        assertEquals("a_b.txt", OutboxFiles.sanitize("a:b.txt"))
        val files = OutboxFiles(folder.newFolder("app"))
        assertNull(files.locate("c1", "../../secret"))
    }

    @Test fun `le dossier des envoyés tient son budget, les plus anciens partent`() {
        val files = OutboxFiles(folder.newFolder("app"), sentBudgetBytes = 25)
        for (i in 1..3) {
            files.adopt("c$i", listOf(staged("f.bin", 10)))
            files.release("c$i")
            File(folder.root, "app/sent/c$i").setLastModified(1_000L * i)
        }
        files.adopt("c4", listOf(staged("f.bin", 10)))
        files.release("c4")
        assertNull(files.locate("c1", "f.bin"))
        assertNull(files.locate("c2", "f.bin"))
        assertTrue(files.locate("c4", "f.bin") != null)
    }

    @Test fun `un message refusé repart avec ses fichiers, et la déconnexion efface tout`() {
        val files = OutboxFiles(folder.newFolder("app"))
        files.adopt("c1", listOf(staged("a.png", 3)))
        files.release("c1")
        val again = files.restage("c1", listOf("a.png" to "a.png", "disparu.png" to "disparu.png")) { "image/png" }
        assertEquals(listOf("a.png"), again.map { it.name })
        assertTrue(File(again.single().path).exists())
        files.wipe()
        assertNull(files.locate("c1", "a.png"))
        assertFalse(File(again.single().path).exists())
    }
}
