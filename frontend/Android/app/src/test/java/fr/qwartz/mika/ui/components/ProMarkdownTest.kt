package fr.qwartz.mika.ui.components

import fr.qwartz.mika.ui.components.ProMarkdown.Block
import fr.qwartz.mika.ui.components.ProMarkdown.Span
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Le Markdown d'une réponse pro (ADR 0116) : ce que l'analyseur en fait, sans écran. */
class ProMarkdownTest {
    @Test fun `gras, italique, code en ligne, une marque sans partenaire reste du texte`() {
        assertEquals(
            listOf(
                Span("un "), Span("mot", bold = true), Span(", un "), Span("autre", italic = true), Span(" et "),
                Span("x = 1", code = true), Span(" puis **seul"),
            ),
            ProMarkdown.inline("un **mot**, un *autre* et `x = 1` puis **seul"),
        )
        assertEquals(listOf(Span("a "), Span("b", bold = true, italic = true), Span(" c")), ProMarkdown.inline("a ***b*** c"))
        assertEquals(listOf(Span("un "), Span("gras dans l'", italic = true), Span("italique", bold = true, italic = true)),
            ProMarkdown.inline("un *gras dans l'**italique***"))
        assertEquals(listOf(Span("2 * 3 * 4")), ProMarkdown.inline("2 * 3 * 4"))
    }

    @Test fun `un nom d'outil ou de variable n'est jamais en italique, un échappement est un caractère`() {
        assertEquals(listOf(Span("appelle memory_search puis email_read_all")), ProMarkdown.inline("appelle memory_search puis email_read_all"))
        assertEquals(listOf(Span("un "), Span("vrai", italic = true), Span(" mot")), ProMarkdown.inline("un _vrai_ mot"))
        assertEquals(listOf(Span("*pas* d'italique")), ProMarkdown.inline("\\*pas\\* d'italique"))
        // dans le code, rien n'est interprété
        assertEquals(listOf(Span("**x** et _y_", code = true)), ProMarkdown.inline("`**x** et _y_`"))
        assertEquals(listOf(Span("a`b", code = true)), ProMarkdown.inline("``a`b``"))
    }

    @Test fun `seuls les liens http(s) sont des liens`() {
        assertEquals(
            listOf(Span("voir "), Span("la doc", url = "https://exemple.org/doc"), Span(".")),
            ProMarkdown.inline("voir [la doc](https://exemple.org/doc \"titre\")."),
        )
        // un lien javascript: ou un fichier local ne garde que son texte
        assertEquals(listOf(Span("clique ici")), ProMarkdown.inline("[clique ici](javascript:alert(1))"))
        assertEquals(listOf(Span("ouvre ça")), ProMarkdown.inline("ouvre [ça](file:///etc/passwd)"))
        // une adresse nue, sans la ponctuation qui la suit
        assertEquals(
            listOf(Span("c'est sur "), Span("http://a.b/c?d=1", url = "http://a.b/c?d=1"), Span(", voilà")),
            ProMarkdown.inline("c'est sur http://a.b/c?d=1, voilà"),
        )
        assertTrue(ProMarkdown.isSafeUrl("HTTPS://exemple.org"))
        assertFalse(ProMarkdown.isSafeUrl("https://exemple.org/\"onclick"))
        assertFalse(ProMarkdown.isSafeUrl("ftp://exemple.org"))
        assertEquals(listOf("la doc" to "https://exemple.org/doc"), ProMarkdown.links("[la doc](https://exemple.org/doc) et [x](mailto:a@b)"))
    }

    @Test fun `titres, listes, citation, filet, paragraphes`() {
        val text = """
            # Le devis de Paul
            Voilà ce que j'ai trouvé :
            sur deux lignes

            - le **montant** : 1 200 €
            - la date
              qui continue
                - un détail
            1. d'abord
            2) ensuite

            > il a écrit ça
            ---
            ### Fin
        """.trimIndent()
        assertEquals(
            listOf(
                Block.Heading(1, listOf(Span("Le devis de Paul"))),
                Block.Paragraph(listOf(Span("Voilà ce que j'ai trouvé :\nsur deux lignes"))),
                Block.Item("•", 0, listOf(Span("le "), Span("montant", bold = true), Span(" : 1 200 €"))),
                Block.Item("•", 0, listOf(Span("la date qui continue"))),
                Block.Item("▪", 2, listOf(Span("un détail"))),
                Block.Item("1.", 0, listOf(Span("d'abord"))),
                Block.Item("2)", 0, listOf(Span("ensuite"))),
                Block.Quote(listOf(Span("il a écrit ça"))),
                Block.Rule,
                Block.Heading(3, listOf(Span("Fin"))),
            ),
            ProMarkdown.parse(text),
        )
        // un mot-dièse n'est pas un titre, du gras en début de ligne n'est pas une liste
        assertEquals(listOf(Block.Paragraph(listOf(Span("#motdièse")))), ProMarkdown.parse("#motdièse"))
        assertEquals(listOf(Block.Paragraph(listOf(Span("gras", bold = true), Span(" ici")))), ProMarkdown.parse("**gras** ici"))
    }

    @Test fun `les blocs de code gardent tout, langage compris, un bloc jamais fermé reste un bloc`() {
        val text = "Lance :\n\n```bash\n  ls -la   # **pas du gras**\n\n<b>rien</b>\n```\nfini"
        assertEquals(
            listOf(
                Block.Paragraph(listOf(Span("Lance :"))),
                Block.Code("  ls -la   # **pas du gras**\n\n<b>rien</b>", "bash"),
                Block.Paragraph(listOf(Span("fini"))),
            ),
            ProMarkdown.parse(text),
        )
        assertEquals(listOf(Block.Code("a\nb", "")), ProMarkdown.parse("```\na\nb"))
        assertEquals(listOf(Block.Code("ls -la", "")), ProMarkdown.parse("```ls -la```"))
        // un tableau se montre tel quel, en chasse fixe
        assertEquals(listOf(Block.Code("| a | b |\n|---|---|\n| 1 | 2 |", "")), ProMarkdown.parse("| a | b |\n|---|---|\n| 1 | 2 |"))
    }

    @Test fun `du HTML reste du texte`() {
        assertEquals(
            listOf(Block.Paragraph(listOf(Span("<script>alert(1)</script> et "), Span("<i>", code = true)))),
            ProMarkdown.parse("<script>alert(1)</script> et `<i>`"),
        )
    }

    @Test fun `le texte sans ses marques, pour le lecteur d'écran et la copie`() {
        assertEquals(
            "Titre\nun mot important\n• a\n  ◦ b\n1. c\nprint(1)",
            ProMarkdown.plain("# Titre\n\nun mot **important**\n\n- a\n  - b\n1. c\n\n---\n\n```py\nprint(1)\n```"),
        )
    }
}
