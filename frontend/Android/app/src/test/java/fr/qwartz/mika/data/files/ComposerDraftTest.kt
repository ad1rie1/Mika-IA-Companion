package fr.qwartz.mika.data.files

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ComposerDraftTest {
    private fun f(n: Int) = StagedFile("f$n.jpg", "image/jpeg", "/staging/f$n", 10L * n)

    @Test fun `aller-retour, et un brouillon illisible est vide`() {
        val d = ComposerDraft("salut", listOf(f(1)))
        assertEquals(d, ComposerDraft.decode(d.encode()))
        assertEquals(ComposerDraft(), ComposerDraft.decode("{pas du json"))
        assertEquals(ComposerDraft(), ComposerDraft.decode(null))
        assertTrue(ComposerDraft().isEmpty)
    }

    @Test fun `un partage s'ajoute à ce qui est tapé`() {
        val m = ComposerDraft("je voulais te dire", listOf(f(1))).merge(ComposerDraft("https://ex.fr", listOf(f(2)), listOf("x réduite")))
        assertEquals("je voulais te dire\nhttps://ex.fr", m.draft.text)
        assertEquals(listOf(f(1), f(2)), m.draft.files)
        assertEquals(listOf("x réduite"), m.notices)
        assertTrue(m.dropped.isEmpty())
        assertTrue(m.draft.notices.isEmpty())
    }

    @Test fun `au-delà de cinq fichiers, les suivants sont rendus et comptés`() {
        val m = ComposerDraft("", (1..4).map(::f)).merge(ComposerDraft("", (5..7).map(::f)))
        assertEquals((1..5).map(::f), m.draft.files)
        assertEquals(listOf(f(6), f(7)), m.dropped)
        assertEquals(listOf("2 fichiers ignorés : maximum 5 pièces jointes."), m.notices)
    }

    @Test fun `le texte reste sous la limite d'un message`() {
        val m = ComposerDraft("a".repeat(1990)).merge(ComposerDraft("b".repeat(50)))
        assertEquals(2000, m.draft.text.length)
        assertEquals(listOf("Texte partagé coupé à 2000 caractères."), m.notices)
    }
}
