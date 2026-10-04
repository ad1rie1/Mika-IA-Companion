package fr.qwartz.mika.share

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ShareParserTest {
    private val own = setOf("fr.qwartz.mika.debug.files")
    private fun input(action: String? = ShareParser.ACTION_SEND, text: String? = null, subject: String? = null, vararg streams: String) =
        ShareInput(action, "image/*", text, subject, streams.toList())

    @Test fun `une photo partagée`() {
        val r = ShareParser.parse(input(streams = arrayOf("content://media/external/images/12")), own)!!
        assertEquals(listOf("content://media/external/images/12"), r.streams)
        assertNull(r.text)
        assertTrue(r.notices.isEmpty())
    }

    @Test fun `un texte seul pré-remplit la saisie`() {
        val r = ShareParser.parse(input(text = "  regarde ça  "), own)!!
        assertEquals("regarde ça", r.text)
        assertTrue(r.streams.isEmpty())
    }

    @Test fun `une page partagée - son titre et son adresse`() {
        assertEquals("Un article\nhttps://ex.fr/a", ShareParser.parse(input(text = "https://ex.fr/a", subject = "Un article"), own)!!.text)
        // Le titre déjà dans le texte n'est pas répété.
        assertEquals("Un article https://ex.fr/a", ShareParser.parse(input(text = "Un article https://ex.fr/a", subject = "Un article"), own)!!.text)
    }

    @Test fun `plusieurs fichiers, sans doublon`() {
        val r = ShareParser.parse(
            input(ShareParser.ACTION_SEND_MULTIPLE, null, null, "content://a/1", "content://a/2", "content://a/1", " "),
            own,
        )!!
        assertEquals(listOf("content://a/1", "content://a/2"), r.streams)
    }

    @Test fun `ni file, ni notre propre fournisseur - nos fichiers privés ne partent pas`() {
        val r = ShareParser.parse(
            input(
                streams = arrayOf(
                    "file:///data/data/fr.qwartz.mika/databases/mika.db",
                    "content://fr.qwartz.mika.debug.files/shared/x",
                    "content://10@media/external/images/3",
                ),
            ),
            own,
        )!!
        assertEquals(listOf("content://10@media/external/images/3"), r.streams)
        assertEquals(listOf("2 fichiers refusés : source non autorisée."), r.notices)
        assertFalse(ShareParser.isForeignContent("content:///rien", own))
    }

    @Test fun `un texte trop long est coupé, et on le dit`() {
        val r = ShareParser.parse(input(text = "x".repeat(2500)), own)!!
        assertEquals(2000, r.text!!.length)
        assertEquals(listOf("Texte partagé coupé à 2000 caractères."), r.notices)
    }

    @Test fun `rien à partager, ou pas un partage`() {
        assertNull(ShareParser.parse(input(), own))
        assertNull(ShareParser.parse(input(action = "android.intent.action.VIEW", text = "x"), own))
        assertNull(ShareParser.parse(input(action = null, text = "x"), own))
    }
}
