package fr.qwartz.mika.ui.chat

import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
import fr.qwartz.mika.data.net.StrandInfo
import fr.qwartz.mika.ui.Route
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** « Rechercher » : ce qui se cherche où, et comment se classe ce qui est trouvé (`frontendv2/src/shell/palette.ts`). */
class SearchRulesTest {
    private fun msg(text: String, ts: Long, sender: Sender = Sender.MIKA, strand: String? = null, inner: Boolean = false) =
        StoredMessage(text, sender, ts, id = ts, localId = ts, strand = strand, inner = inner)

    @Test fun `sans accents ni casse, les espaces resserrées`() {
        assertEquals("ecrire a mika", SearchRules.fold("  Écrire   À\tMIKA "))
        assertEquals("lefevre", SearchRules.fold("Lefèvre"))
    }

    @Test fun `un message se cherche dans tout son texte, le plus récent d'abord, dix au plus`() {
        val long = "Je te fais le point sur la semaine, parce qu'il s'est passé pas mal de choses à l'atelier depuis lundi. " +
            "Le devis de la papeterie expire le 20 novembre,\net l'imprimerie attend un bon pour accord signé avant jeudi."
        val all = listOf(
            msg(long, 1),
            msg("le budget arrive trop tard", 2),
            msg("pensée sur le budget", 3, inner = true), // une pensée à voix haute ne se cherche pas
            msg("le Budget du projet", 4, Sender.USER),
            msg("le budget de Lefèvre", 5, strand = "devis"),
        )
        val (chat, strands) = SearchRules.messages(all, "BUDGET", operator = true)
        assertEquals(listOf(4L, 2L), chat.map { it.message.ts })
        assertEquals(listOf("devis"), strands.map { it.strand })
        // ses fils de travail ne sont qu'à son opératrice
        assertTrue(SearchRules.messages(all, "budget", operator = false).second.isEmpty())

        val (found, _) = SearchRules.messages(all, "IMPRIMERIE attend", operator = false)
        val hit = found.single()
        assertTrue(hit.title.startsWith("…"))
        assertTrue(hit.title.contains("imprimerie attend un bon"))
        assertTrue(hit.title.length <= 72)

        val many = (1..30L).map { msg("le devis $it", it) }
        assertEquals(SearchRules.MAX_PER_GROUP, SearchRules.messages(many, "devis", operator = false).first.size)
        assertEquals(30L, SearchRules.messages(many, "devis", operator = false).first.first().message.ts)
        assertTrue(SearchRules.messages(many, "  ", operator = false).first.isEmpty())
    }

    @Test fun `le passage trouvé - coupé entre deux mots, « … » aux coupes, sinon le début`() {
        val text = "Un deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze quinze seize dix-sept dix-huit dix-neuf vingt."
        val out = SearchRules.excerpt(text, "quatorze")
        assertTrue(out.startsWith("…") && out.endsWith("…"))
        val inner = out.substring(1, out.length - 1)
        val at = text.indexOf(inner)
        assertTrue(inner.contains("quatorze"))
        assertTrue(at > 0)
        assertEquals(' ', text[at - 1])
        assertEquals(' ', text[at + inner.length])
        assertEquals("Écrire à Mika", SearchRules.excerpt("Écrire à Mika", "ecrire"))
        assertEquals(text.take(69).trimEnd() + "…", SearchRules.excerpt(text, "absent"))
        // de quoi surligner, aux positions du texte d'origine (accents compris)
        assertEquals(0 until 6, SearchRules.matchRange("Écrire à Mika", "ecrire"))
        assertNull(SearchRules.matchRange("Écrire à Mika", "lire"))
    }

    @Test fun `ses fils de travail, par leur titre, leur description ou leur premier message`() {
        val strands = listOf(
            StrandInfo("devis", title = "Devis Lefèvre", description = "Comparer au budget"),
            StrandInfo("nas", opener = "un script de sauvegarde du NAS"),
            StrandInfo("vide"),
        )
        assertEquals(listOf("devis"), SearchRules.strands(strands, "lefevre").map { it.strand.id })
        assertEquals(listOf("devis"), SearchRules.strands(strands, "budget").map { it.strand.id })
        val nas = SearchRules.strands(strands, "sauvegarde").single()
        assertEquals("un script de sauvegarde du NAS", nas.title)
        assertTrue(SearchRules.strands(strands, "").isEmpty())
    }

    private val screens = listOf(
        ScreenEntry("Chat", "la conversation avec Mika", Route.Chat),
        ScreenEntry("Mail", "tes boîtes", Route.Mail),
        ScreenEntry("Mail › Ses brouillons", "ce qu'elle a préparé", Route.MailDrafts, parent = Route.Mail),
        ScreenEntry("Paramètres", "ton compte", Route.Settings),
        ScreenEntry("Paramètres › Boîtes mail", "tes boîtes, celles qu'on te partage", Route.SettingsPage("boites"), Route.Settings),
        ScreenEntry("Paramètres › Téléphones", "ce téléphone et les autres", Route.SettingsPage("telephones"), Route.Settings),
        ScreenEntry("Téléphone", "tes messages lus", Route.Phone()),
    )

    @Test fun `les écrans - le titre qui commence par ce qu'on cherche, puis un mot, puis le reste`() {
        // sans rien de tapé : les rubriques seules
        assertEquals(listOf("Chat", "Mail", "Paramètres", "Téléphone"), SearchRules.screens(screens, "").map { it.title })
        // « telephone » : la page (« › Téléphones ») et la rubrique commencent toutes deux ainsi : l'ordre du tiroir
        assertEquals(
            listOf("Paramètres › Téléphones", "Téléphone"),
            SearchRules.screens(screens, "telephone").map { it.title },
        )
        // « boites » : la page dont un mot commence ainsi, puis ce qui ne le dit que dans sa ligne
        assertEquals(
            listOf("Paramètres › Boîtes mail", "Mail"),
            SearchRules.screens(screens, "boites").map { it.title },
        )
        // « brouillons » : un mot du titre
        assertEquals(listOf("Mail › Ses brouillons"), SearchRules.screens(screens, "brouillons").map { it.title })
        assertTrue(SearchRules.screens(screens, "introuvable").isEmpty())
    }

    @Test fun `où chercher - la loupe du chat part de la conversation, le serveur seulement à deux lettres`() {
        assertEquals(SearchChip.CHAT, SearchRules.chipFor("chat"))
        assertEquals(SearchChip.ALL, SearchRules.chipFor("all"))
        assertTrue(SearchRules.showsMail(SearchChip.ALL) && SearchRules.showsTeams(SearchChip.ALL) && SearchRules.showsChat(SearchChip.ALL))
        assertTrue(!SearchRules.showsMail(SearchChip.CHAT) && !SearchRules.showsScreens(SearchChip.CHAT))
        assertTrue(SearchRules.showsScreens(SearchChip.SCREENS) && !SearchRules.showsChat(SearchChip.SCREENS))
        assertNull(SearchRules.remoteQuery(" a "))
        assertEquals("le devis", SearchRules.remoteQuery("  le   devis "))
    }
}
