package fr.qwartz.mika.data.files

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AttachmentPolicyTest {
    private data class F(val name: String, val size: Long)
    private val mo = 1024L * 1024

    private fun admit(already: Int, vararg files: F) = AttachmentPolicy.admit(already, files.toList(), { it.name }, { it.size })

    @Test fun `au-delà de cinq, les suivants sont ignorés et comptés`() {
        val r = admit(3, F("a", 1), F("b", 1), F("c", 1), F("d", 1))
        assertEquals(listOf("a", "b"), r.accepted.map { it.name })
        assertEquals(listOf("2 fichiers ignorés : maximum 5 pièces jointes."), r.notices)
        assertEquals(listOf("1 fichier ignoré : maximum 5 pièces jointes."), admit(4, F("a", 1), F("b", 1)).notices)
    }

    @Test fun `un fichier trop lourd dit sa taille, un fichier illisible le dit aussi`() {
        val r = admit(0, F("photo.jpg", (7.2 * mo).toLong()), F("note.txt", -1), F("ok.png", 10))
        assertEquals(listOf("ok.png"), r.accepted.map { it.name })
        assertEquals(
            listOf("photo.jpg ignoré : 7,2 Mo (maximum 5 Mo).", "note.txt illisible : non joint."),
            r.notices,
        )
    }

    @Test fun `ce qui ne peut pas partir est dit avant l'envoi`() {
        assertEquals("Message vide.", AttachmentPolicy.checkSend("", emptyList()))
        assertNull(AttachmentPolicy.checkSend("salut", emptyList()))
        assertEquals(
            "Message trop long : 2000 caractères au plus.",
            AttachmentPolicy.checkSend("x".repeat(2001), emptyList()),
        )
        val three = List(3) { StagedFile("f$it.jpg", "image/jpeg", "/x", 4 * mo) }
        assertEquals(AttachmentPolicy.TOO_HEAVY, AttachmentPolicy.checkSend("", three))
        assertNull(AttachmentPolicy.checkSend("", three.take(2)))
    }

    @Test fun `la sorte suit le type`() {
        assertEquals("image", AttachmentPolicy.kindOf("image/png"))
        assertEquals("audio", AttachmentPolicy.kindOf("audio/ogg"))
        assertEquals("file", AttachmentPolicy.kindOf("application/pdf"))
    }

    @Test fun `les tailles sous les puces, et la réduction dite`() {
        assertEquals("312 o", AttachmentPolicy.humanSize(312))
        assertEquals("12 Ko", AttachmentPolicy.humanSize(12 * 1024))
        assertEquals("7,2 Mo", AttachmentPolicy.humanSize((7.2 * mo).toLong()))
        assertEquals("photo.jpg réduite pour tenir sous 5 Mo.", AttachmentPolicy.reduced("photo.jpg", toFitMessage = false))
        assertEquals("photo.jpg réduite pour tenir dans un seul message.", AttachmentPolicy.reduced("photo.jpg", toFitMessage = true))
    }
}
