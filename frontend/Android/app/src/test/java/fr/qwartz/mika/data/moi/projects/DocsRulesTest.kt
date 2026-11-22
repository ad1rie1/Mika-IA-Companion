package fr.qwartz.mika.data.moi.projects

import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Les règles pures de l'onglet Documentation : **les transformations de la barre d'outils de l'éditeur** (chacune agit
 * sur la sélection, se défait en la refaisant, et rend la sélection où l'on continue d'écrire), « Entrée » qui poursuit
 * une liste, l'arborescence des pages, le chemin d'une page nouvelle, ce qu'une page montre (ses images de l'espace
 * seulement, rien dans un bloc de code), le brouillon et son conflit, les gestes, l'ordre des décisions.
 */
class DocsRulesTest {
    private fun sel(e: Edit) = e.text.substring(e.start, e.end)

    // ── L'éditeur ──

    @Test fun `gras - la sélection s'entoure, se défait en le refaisant, un blanc au bord reste dehors`() {
        val bold = MdEdit.bold(Edit("un mot", 3, 6))
        assertEquals("un **mot**", bold.text)
        assertEquals("mot", sel(bold))
        // le refaire sur la même sélection retire les marques
        assertEquals(Edit("un mot", 3, 6), MdEdit.bold(bold))
        // la sélection qui prend les marques avec elle
        assertEquals(Edit("mot", 0, 3), MdEdit.bold(Edit("**mot**", 0, 7)))
        // un blanc sélectionné au bord ne passe pas dans le gras (« ** mot ** » ne se lit pas)
        val spaced = MdEdit.bold(Edit("a mot  b", 1, 6))
        assertEquals("a **mot**  b", spaced.text)
        assertEquals("mot", sel(spaced))
        // rien que des blancs : rien ne change
        assertEquals(Edit("a   b", 1, 4), MdEdit.bold(Edit("a   b", 1, 4)))
    }

    @Test fun `gras sans sélection - les marques se posent, le curseur au milieu, et s'en vont si rien n'y est écrit`() {
        val open = MdEdit.bold(Edit("ab", 1))
        assertEquals(Edit("a****b", 3), open)
        assertEquals(Edit("ab", 1), MdEdit.bold(open))
    }

    @Test fun `italique - une étoile, qui ne se confond pas avec le gras`() {
        val it = MdEdit.italic(Edit("mot", 0, 3))
        assertEquals("*mot*", it.text)
        assertEquals("mot", sel(it))
        assertEquals(Edit("mot", 0, 3), MdEdit.italic(it))
        // dans du gras : l'italique s'ajoute, puis se retire sans toucher au gras
        val both = MdEdit.italic(Edit("**mot**", 2, 5))
        assertEquals("***mot***", both.text)
        assertEquals("mot", sel(both))
        assertEquals(Edit("**mot**", 2, 5), MdEdit.italic(both))
        // le curseur dans un gras vide : l'italique s'y pose, il ne mange pas une étoile du gras
        assertEquals("***" + "***", MdEdit.italic(Edit("****", 2)).text)
    }

    @Test fun `code - en ligne dans une phrase, en bloc sur plusieurs lignes ou sur une ligne vide`() {
        val inline = MdEdit.code(Edit("lance ls ici", 6, 8))
        assertEquals("lance `ls` ici", inline.text)
        assertEquals("ls", sel(inline))
        assertEquals(Edit("lance ls ici", 6, 8), MdEdit.code(inline))
        val block = MdEdit.code(Edit("a\nb\nc", 0, 5))
        assertEquals("```\na\nb\nc\n```", block.text)
        assertEquals("a\nb\nc", sel(block))
        // au milieu d'un texte : le bloc prend ses propres lignes
        assertEquals("avant\n```\nx\ny\n```\naprès", MdEdit.code(Edit("avant x\ny après", 6, 9)).text)
        // sur une ligne vide : un bloc vide, le curseur dedans
        val empty = MdEdit.code(Edit("x\n\ny", 2))
        assertEquals("x\n```\n\n```\ny", empty.text)
        assertEquals(6, empty.start)
        assertEquals(6, empty.end)
    }

    @Test fun `titre - le niveau se pose sur la ligne, tourne, et le curseur garde sa place`() {
        val h2 = MdEdit.heading(Edit("Titre", 2), 2)
        assertEquals(Edit("## Titre", 5), h2)
        assertEquals(2, MdEdit.headingAt(h2))
        // le même niveau redit : du texte
        assertEquals(Edit("Titre", 2), MdEdit.heading(h2, 2))
        // un autre niveau remplace
        assertEquals("### Titre", MdEdit.heading(h2, 3).text)
        // la touche tourne : texte, 1, 2, 3, texte
        var e = Edit("Titre", 5)
        val seen = (1..4).map {
            e = MdEdit.headingNext(e)
            e.text
        }
        assertEquals(listOf("# Titre", "## Titre", "### Titre", "Titre"), seen)
        // sur plusieurs lignes choisies, les lignes vides ne bougent pas
        assertEquals("# a\n\n# b", MdEdit.heading(Edit("a\n\nb", 0, 4), 1).text)
    }

    @Test fun `listes - à puces, à cocher, numérotée - sur les lignes choisies, l'une se change en l'autre`() {
        val bullets = MdEdit.list(Edit("a\nb", 0, 3), MdEdit.ListKind.BULLET)
        assertEquals("- a\n- b", bullets.text)
        assertEquals("- a\n- b", sel(bullets))
        assertEquals(Edit("a\nb", 0, 3), MdEdit.list(bullets, MdEdit.ListKind.BULLET))
        val tasks = MdEdit.list(bullets, MdEdit.ListKind.TASK)
        assertEquals("- [ ] a\n- [ ] b", tasks.text)
        assertEquals("1. a\n2. b", MdEdit.list(tasks, MdEdit.ListKind.NUMBER).text)
        // une ligne vide au milieu ne compte pas, et ne reçoit pas de marque
        assertEquals("1. a\n\n2. b", MdEdit.list(Edit("a\n\nb", 0, 4), MdEdit.ListKind.NUMBER).text)
        // le curseur seul : sa ligne, et il suit ; un retrait reste
        assertEquals(Edit("- ", 2), MdEdit.list(Edit("", 0), MdEdit.ListKind.BULLET))
        assertEquals(Edit("  - a", 5), MdEdit.list(Edit("  a", 3), MdEdit.ListKind.BULLET))
        // une case cochée reste une liste à cocher : la refaire la retire
        assertEquals("fait", MdEdit.list(Edit("- [x] fait", 3), MdEdit.ListKind.TASK).text)
        // une sélection qui finit en début de ligne ne prend pas cette ligne
        assertEquals("- a\nb", MdEdit.list(Edit("a\nb", 0, 2), MdEdit.ListKind.BULLET).text)
    }

    @Test fun `citation - sur les lignes choisies, et se retire`() {
        val quoted = MdEdit.quote(Edit("a\nb", 0, 3))
        assertEquals("> a\n> b", quoted.text)
        assertEquals(Edit("a\nb", 0, 3), MdEdit.quote(quoted))
        assertEquals(Edit("> mot", 5), MdEdit.quote(Edit("mot", 3)))
    }

    @Test fun `lien - la sélection devient son texte, sinon l'adresse, sélectionnée pour l'écrire par-dessus`() {
        val url = "https://exemple.invalid/doc"
        val link = MdEdit.link(Edit("voir la doc ici", 8, 11), url)
        assertEquals("voir la [doc]($url) ici", link.text)
        // le curseur est après le lien
        assertEquals(" ici", link.text.substring(link.start))
        assertEquals(link.start, link.end)
        val bare = MdEdit.link(Edit("ab", 1), url)
        assertEquals("a[$url]($url)b", bare.text)
        assertEquals(url, sel(bare))
        // un blanc au bord de la sélection reste hors du lien ; sans adresse, rien ne change
        assertEquals("a [mot]($url) b", MdEdit.link(Edit("a mot b", 1, 6), url).text)
        assertEquals(Edit("ab", 1), MdEdit.link(Edit("ab", 1), "  "))
    }

    @Test fun `image - sur sa propre ligne, là où est le curseur, avec son texte tiré de son nom`() {
        val e = MdEdit.image(Edit("Avant\nAprès", 5), "schema-reseau.png")
        assertEquals("Avant\n\n![schema reseau](images/schema-reseau.png)\n\nAprès", e.text)
        assertEquals("\nAprès", e.text.substring(e.start))
        // dans une page vide, ou en fin de page : pas de ligne vide en trop avant, une fin de ligne après
        assertEquals(Edit("![a](images/a.png)\n", 19), MdEdit.image(Edit("", 0), "a.png"))
        assertEquals("x\n\n![a](images/a.png)\n", MdEdit.image(Edit("x\n\n", 3), "a.png").text)
        assertEquals("![schema reseau](images/schema-reseau.png)", imageMarkdown("schema-reseau.png"))
    }

    @Test fun `Entrée poursuit une liste - la marque d'après, le numéro d'après, une case vide - et la finit sur un élément vide`() {
        fun enter(text: String): Edit = MdEdit.continued(Edit(text, text.length), Edit(text + "\n", text.length + 1))
        assertEquals(Edit("- a\n- ", 6), enter("- a"))
        assertEquals(Edit("* a\n* ", 6), enter("* a"))
        assertEquals(Edit("1. a\n2. ", 8), enter("1. a"))
        assertEquals(Edit("9) a\n10) ", 9), enter("9) a"))
        assertEquals("- [x] fait\n- [ ] ", enter("- [x] fait").text)
        assertEquals("  - a\n  - ", enter("  - a").text)
        assertEquals("> a\n> ", enter("> a").text)
        // un élément resté vide : sa marque s'en va, la liste est finie
        assertEquals(Edit("- a\n", 4), enter("- a\n- "))
        assertEquals(Edit("", 0), enter("1. "))
        // ailleurs rien ne change : du texte, un bloc de code, une frappe qui n'est pas « Entrée »
        assertEquals(Edit("texte\n", 6), enter("texte"))
        assertEquals(Edit("```\n- a\n", 8), enter("```\n- a"))
        assertEquals(Edit("- ab", 4), MdEdit.continued(Edit("- a", 3), Edit("- ab", 4)))
        // « Entrée » au milieu d'un élément : la suite passe sur une ligne à sa marque
        assertEquals(Edit("- a\n- b", 6), MdEdit.continued(Edit("- ab", 3), Edit("- a\nb", 4)))
        // une sélection remplacée par « Entrée »
        assertEquals(Edit("- a\n- c", 6), MdEdit.continued(Edit("- abc", 3, 4), Edit("- a\nc", 4)))
    }

    @Test fun `un état d'édition reste dans ses bornes`() {
        assertEquals(Edit("abc", 1, 2), Edit.of("abc", 2, 1))
        assertEquals(Edit("abc", 3, 3), Edit.of("abc", 9))
        assertEquals("b", Edit("abc", 1, 2).selected)
    }

    // ── L'arborescence, les chemins ──

    private fun page(path: String) = DocPage(path = path, name = path.substringAfterLast('/'), folder = path.substringBeforeLast('/', ""))

    @Test fun `l'arborescence - les dossiers d'abord, accueil en tête, un dossier replié cache ce qu'il contient`() {
        val pages = listOf("notes-de-version.md", "guide/installation.md", "accueil.md", "reference/configuration/delais.md", "guide/connexion-rdp.md", "reference/commandes.md").map(::page)
        val rows = docRows(pages)
        assertEquals(
            listOf("guide", "guide/connexion-rdp.md", "guide/installation.md", "reference", "reference/configuration", "reference/configuration/delais.md", "reference/commandes.md", "accueil.md", "notes-de-version.md"),
            rows.map { it.path },
        )
        assertEquals(listOf(0, 1, 1, 0, 1, 2, 1, 0, 0), rows.map { it.depth })
        assertEquals(listOf(true, false, false, true, true, false, false, false, false), rows.map { it.page == null })
        assertEquals(listOf("guide", "guide/connexion-rdp.md", "guide/installation.md", "reference", "accueil.md", "notes-de-version.md"), docRows(pages, setOf("reference")).map { it.path })
        assertTrue(docRows(emptyList()).isEmpty())
    }

    @Test fun `le chemin d'une page se replie comme le serveur l'attend, sans rien inventer`() {
        assertEquals("depannage-avance", slug("Dépannage avancé.md"))
        assertEquals("guide/avance", folderPath("Guide / Avancé "))
        assertEquals("guide/depannage.md", pagePath("guide", "Dépannage"))
        assertEquals("accueil.md", pagePath("", "Accueil"))
        assertEquals("", pagePath("guide", "???"))
        assertEquals("guide/avance", folderOf("guide/avance/x.md"))
        assertEquals("", folderOf("x.md"))
        assertEquals("x.md", nameOf("guide/x.md"))
        // une image de l'espace, et rien d'autre
        assertEquals("schema.png", spaceImage("images/schema.png"))
        assertEquals("schema.png", spaceImage("./images/schema.png"))
        assertEquals("", spaceImage("https://ailleurs.invalid/images/schema.png"))
        assertEquals("", spaceImage("images/../secret.png"))
        assertEquals("", spaceImage("/images/schema.png"))
        assertEquals(DocTabs.PAGES, DocTabs.of("inconnu"))
        assertEquals("documentation/images", DocTabs.tab(DocTabs.IMAGES))
        assertEquals("documentation", DocTabs.tab(DocTabs.PAGES))
    }

    // ── Ce qu'une page montre ──

    @Test fun `une page en morceaux - ses images de l'espace se montrent, celles d'ailleurs se disent, rien n'est lu dans un bloc de code`() {
        val text = "# Titre\n\n![Le schéma](images/schema.png)\n\nTexte ![x](https://ailleurs.invalid/a.png \"Vu ailleurs\") suite\n\n```\n![pas une image](images/code.png)\n- [ ] pas une case\n```\n- [ ] à faire\n- [x] fait"
        val blocks = docBlocks(text)
        assertEquals(
            listOf(
                DocBlock.Text("# Titre"),
                DocBlock.Image("schema.png", "Le schéma"),
                DocBlock.Text("Texte"),
                DocBlock.Elsewhere("https://ailleurs.invalid/a.png", "Vu ailleurs"),
                DocBlock.Text("suite\n\n```\n![pas une image](images/code.png)\n- [ ] pas une case\n```\n- ☐ à faire\n- ☑ fait"),
            ),
            blocks,
        )
        // aucune adresse d'ailleurs ne devient une image à charger, quelle que soit sa forme
        for (src in listOf("http://x.invalid/a.png", "//x.invalid/a.png", "data:image/png;base64,AAAA", "file:///a.png", "images/../../a.png", "javascript:x")) {
            assertTrue(src, docBlocks("![a]($src)").single() is DocBlock.Elsewhere)
        }
        assertTrue(docBlocks("").isEmpty())
        assertEquals(listOf(1 to "Titre", 2 to "Partie une"), headingsOf("# Titre\n```\n# pas un titre\n```\n## Partie `une`"))
    }

    // ── Le brouillon ──

    @Test fun `le brouillon - enregistrer nomme la version lue, un refus garde le texte, reprendre repart de la version actuelle`() {
        val d = Draft.of(DocPage(path = "guide/installation.md", version = 3, text = "lu"))
        assertFalse(d.dirty)
        val typed = d.typed("écrit")
        assertTrue(typed.dirty)
        assertEquals(DocSave("guide/installation.md", "écrit", "mot", 3), saveOf(typed, "  mot  "))
        assertEquals(WORD_MAX, saveOf(typed, "x".repeat(500)).word.length)
        // refusé : les mots du serveur, et ce qui est écrit reste ; c'est un conflit si la page relue a bougé
        val current = DocPage(path = "guide/installation.md", version = 5, text = "le sien")
        assertTrue(typed.movedOn(current))
        val refused = typed.refused("Cette page a changé depuis ta lecture : elle en est à la version 5, écrite par elle.", typed.movedOn(current))
        assertTrue(refused.conflict)
        assertEquals("écrit", refused.text)
        assertEquals(3, refused.base)
        assertFalse(typed.refused("Tu lis la documentation de ce projet sans pouvoir l'écrire.").conflict)
        // le serveur répond 409 à d'autres refus : la page en est toujours à la version lue, ou n'existe plus — pas un conflit
        assertFalse(typed.movedOn(current.copy(version = 3)))
        assertFalse(typed.movedOn(null))
        assertFalse(typed.refused("Ce texte est déjà celui de la page : rien n'a été enregistré.", typed.movedOn(current.copy(version = 3))).conflict)
        // une page nouvelle qui existe déjà a « bougé » : on reprend sur elle
        assertTrue(Draft.fresh("guide/installation.md", "x").movedOn(current))
        // on continue de taper : le refus reste dit
        assertEquals(refused.refusal, refused.typed("écrit encore").refusal)
        // reprendre : la version actuelle devient le départ, le texte tapé reste entier
        val rebased = refused.rebased(DocPage(path = "guide/installation.md", version = 5, text = "le sien"))
        assertEquals(5, rebased.base)
        assertEquals("écrit", rebased.text)
        assertEquals("", rebased.refusal)
        assertTrue(rebased.dirty && !rebased.conflict)
        assertEquals(5, saveOf(rebased, "").base)
        // enregistré : la version rendue devient la version lue
        val saved = rebased.saved(6)
        assertEquals(6, saved.base)
        assertFalse(saved.dirty)
        // une page nouvelle : rien n'est lu, son premier texte est à enregistrer
        val fresh = Draft.fresh("guide/depannage.md", "# Dépannage\n")
        assertEquals(0, saveOf(fresh, "").base)
        assertTrue(fresh.dirty)
    }

    @Test fun `les gestes d'une page et d'une image - leur route et leur corps`() {
        val restore = docRestoreRequest("a.md", 2, 5)
        assertEquals("documentation/page/revenir", restore.route)
        assertEquals(setOf("path", "version", "base"), restore.body.keys)
        assertEquals(2, (restore.body["version"] as JsonPrimitive).intOrNull)
        assertEquals(5, (restore.body["base"] as JsonPrimitive).intOrNull)
        val move = docMoveRequest("a.md", "guide/a.md")
        assertEquals("documentation/page/deplacer", move.route)
        assertEquals("guide/a.md", (move.body["to"] as JsonPrimitive).content)
        assertEquals("documentation/page/supprimer", docRemoveRequest("a.md").route)
        val drop = docImageRemoveRequest("schema.png")
        assertEquals("documentation/image/retirer", drop.route)
        assertEquals("schema.png", (drop.body["name"] as JsonPrimitive).content)
    }

    @Test fun `les décisions - en vigueur d'abord, puis retirées, puis remplacées - et leurs options écartées`() {
        val items = listOf(Decision(number = 1, status = "superseded"), Decision(number = 2, status = "active"), Decision(number = 4, status = "withdrawn"), Decision(number = 3, status = "active"))
        assertEquals(listOf(2, 3, 4, 1), decisionOrder(items).map { it.number })
        assertEquals(StateTone.DONE, decisionTone("active"))
        assertEquals(StateTone.WAIT, decisionTone("superseded"))
        assertEquals(
            listOf("Un fichier texte libre" to "lisible, mais chaque outil devait deviner", "Une base SQLite" to ""),
            optionLines("Un fichier texte libre : lisible, mais chaque outil devait deviner\n\n  Une base SQLite  \n"),
        )
    }

    @Test fun `une page nouvelle se crée avec son titre - et un brouillon n'est celui que de la page qu'on a lue`() {
        assertEquals(DocSave("guide/depannage.md", "# Dépannage\n\n", NEW_PAGE_WORD, 0), newPageSave("guide/depannage.md", "  Dépannage "))
        assertEquals("Création de la page", NEW_PAGE_WORD)
        // supprimée puis recréée sous le même chemin, c'est une autre page : née à un autre instant
        val read = DocPage(path = "a.md", version = 1, text = "ancien", createdAt = 100)
        val d = Draft.of(read).typed("ancien, repris")
        assertTrue(d.isOf(read.copy(version = 2)))
        assertFalse(d.isOf(DocPage(path = "a.md", version = 1, text = "# Nouvelle", createdAt = 200)))
        // reprendre sur une version, c'est écrire sur la page d'où elle vient
        assertTrue(d.rebased(DocPage(path = "a.md", version = 1, createdAt = 200)).isOf(DocPage(createdAt = 200)))
    }

    @Test fun `une image part telle quelle si l'espace la garde - trop lourde ou d'une sorte qu'il ne garde pas, elle est réencodée`() {
        val limits = DocLimits(imageBytes = 5_242_880, imageKinds = listOf("image/gif", "image/jpeg", "image/png", "image/webp"))
        assertFalse(imageReencoded(limits, 800_000, "image/png"))
        assertFalse(imageReencoded(limits, 5_242_880, "IMAGE/JPEG"))
        // plus lourde que la borne
        assertTrue(imageReencoded(limits, 5_242_881, "image/jpeg"))
        // une photo HEIC, AVIF ou BMP, même légère : le serveur ne garde que PNG, JPEG, GIF et WebP
        assertTrue(imageReencoded(limits, 800_000, "image/heic"))
        assertTrue(imageReencoded(limits, 800_000, "image/avif"))
        assertTrue(imageReencoded(limits, 800_000, "image/bmp"))
        // ce que le serveur ne dit pas ne se devine pas
        assertFalse(imageReencoded(DocLimits(), 50_000_000, "image/heic"))
        assertFalse(imageReencoded(DocLimits(imageBytes = 5_242_880), 800_000, "image/heic"))
    }
}
