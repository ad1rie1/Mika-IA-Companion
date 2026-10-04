package fr.qwartz.mika.ui.components

import fr.qwartz.mika.ui.components.InlineMarkup.Block
import fr.qwartz.mika.ui.components.InlineMarkup.Inline
import org.junit.Assert.assertEquals
import org.junit.Test

class InlineMarkupTest {
    @Test fun `gras et code en ligne, une balise sans partenaire reste du texte`() {
        assertEquals(
            listOf(Inline.Text("un "), Inline.Bold("mot"), Inline.Text(" et "), Inline.Code("x = 1"), Inline.Text(" puis **seul")),
            InlineMarkup.parseInline("un **mot** et `x = 1` puis **seul"),
        )
        assertEquals(listOf(Inline.Text("** pas gras**")), InlineMarkup.parseInline("** pas gras**"))
    }

    @Test fun `un bloc de code garde son langage`() {
        assertEquals(
            listOf(Block.Text("Voilà :\n"), Block.Code("print(1)", "python"), Block.Text("\nfini")),
            InlineMarkup.parseBlocks("Voilà :\n```python\nprint(1)\n```\nfini"),
        )
        assertEquals("milieu", InlineMarkup.trimAroundBlocks("\n\nmilieu\n"))
    }

    @Test fun `le texte sans ses marques, pour le lecteur d'écran et la copie`() {
        assertEquals("un mot important et du code", InlineMarkup.plain("un mot **important** et du `code`"))
        assertEquals("voici :\nprint(1)\nfin", InlineMarkup.plain("voici :\n```py\nprint(1)\n```\nfin"))
        assertEquals("**seul", InlineMarkup.plain("**seul"))
    }
}
