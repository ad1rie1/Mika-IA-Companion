package fr.qwartz.mika.ui

import fr.qwartz.mika.core.DeepLinks
import fr.qwartz.mika.data.moi.carte.Place
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class BackStackTest {
    private val viewer = Route.Viewer("a".repeat(32), "chat.png", "/files/" + "a".repeat(32), "image/png", 12)

    @Test fun `la conversation est au fond, et revenir y sort de l'app`() {
        val root = BackStack()
        assertEquals(Route.Chat, root.top)
        assertFalse(root.canPop)
        assertNull(root.pop())
    }

    @Test fun `empiler puis revenir`() {
        val s = BackStack().push(Route.Mind)
        assertEquals(Route.Mind, s.top)
        assertTrue(s.canPop)
        assertEquals(BackStack(), s.pop())
    }

    @Test fun `jamais deux fois le même écran - on revient à lui`() {
        val s = BackStack().push(Route.Mind).push(Route.Settings).push(Route.Mind)
        assertEquals(listOf(Route.Chat, Route.Mind), s.routes)
        assertSame(s, s.push(Route.Mind))
    }

    @Test fun `la conversation ramène à la racine`() {
        val s = BackStack().push(Route.Settings).push(viewer).push(Route.Chat)
        assertEquals(BackStack(), s)
    }

    @Test fun `une image remplace l'image ouverte`() {
        val other = viewer.copy(fileId = "b".repeat(32), name = "autre.png")
        val s = BackStack().push(viewer).push(other)
        assertEquals(listOf(Route.Chat, other), s.routes)
    }

    @Test fun `la pile se garde et se relit, une pile illisible redevient la conversation`() {
        val s = BackStack().push(Route.Mind).push(viewer)
        assertEquals(s, BackStack.decode(s.encode()))
        assertEquals(BackStack(), BackStack.decode("pas du json"))
        assertEquals(BackStack(), BackStack.decode(null))
        assertEquals(BackStack(), BackStack.decode("""[{"type":"settings"}]"""))
    }

    @Test fun `les liens des notifications`() {
        assertEquals(listOf(Route.Chat, Route.Settings), BackStack.forDeepLink(DeepLinks.SETTINGS).routes)
        assertEquals(listOf(Route.Chat), BackStack.forDeepLink(DeepLinks.CHAT).routes)
        assertEquals(listOf(Route.Chat), BackStack.forDeepLink("inconnu").routes)
    }

    @Test fun `une rubrique du tiroir s'ouvre juste au-dessus du chat (ADR 0235)`() {
        val deep = BackStack().open(Route.Mail).push(Route.MailMessage("pro:<a@b>")).push(Route.MailDraft("d1"))
        assertEquals(Route.Mail, deep.section)
        val teams = deep.open(Route.Teams)
        assertEquals(listOf(Route.Chat, Route.Teams), teams.routes)
        assertEquals(BackStack(), teams.open(Route.Chat))
        assertEquals(Route.Chat, BackStack().section)
    }

    @Test fun `un autre onglet remplace le sommet sans s'empiler`() {
        val s = BackStack().open(Route.Carte()).replaceTop(Route.Carte("voyages"))
        assertEquals(listOf(Route.Chat, Route.Carte("voyages")), s.routes)
        assertEquals(BackStack(), s.pop())
        assertEquals(listOf(Route.Chat, Route.Tools("services")), BackStack().replaceTop(Route.Tools("services")).routes)
    }

    @Test fun `les rubriques sont celles du tiroir`() {
        val top = listOf(Route.Chat, Route.Mail, Route.Teams, Route.Carte(), Route.Phone(), Route.Tools(), Route.Settings)
        assertTrue(top.all { it.isTopLevel })
        assertFalse(Route.Mind.isTopLevel)
        assertFalse(Route.MailDraft("d").isTopLevel)
        assertFalse(Route.SettingsPage("compte").isTopLevel)
    }

    @Test fun `les pages de Paramètres s'empilent sur ce qui y mène (lot 5)`() {
        val fromPhone = BackStack().open(Route.Phone()).push(Route.SettingsPage("telephones"))
        assertEquals(listOf(Route.Chat, Route.Phone(), Route.SettingsPage("telephones")), fromPhone.routes)
        assertEquals(Route.Phone(), fromPhone.section)
        val account = BackStack().open(Route.Mail).open(Route.Settings).push(Route.SettingsPage("compte"))
        assertEquals(listOf(Route.Chat, Route.Settings, Route.SettingsPage("compte")), account.routes)
        // une boîte créée prend la place de la page « nouvelle boîte » : retour ramène à la liste
        val made = BackStack().open(Route.Settings).push(Route.SettingsPage("boites")).push(Route.SettingsPage("boite"))
            .replaceTop(Route.SettingsPage("boite", "pro-1"))
        assertEquals(listOf(Route.Chat, Route.Settings, Route.SettingsPage("boites"), Route.SettingsPage("boite", "pro-1")), made.routes)
        assertEquals(made, BackStack.decode(made.encode()))
        assertEquals(Route.SettingsPage("boites"), made.pop()?.top)
    }

    @Test fun `les onglets d'Outils se remplacent, et Outils ouvert depuis un fil y ramène (lot 5b)`() {
        val drawer = BackStack().open(Route.Tools()).replaceTop(Route.Tools("services")).replaceTop(Route.Tools("droits"))
        assertEquals(listOf(Route.Chat, Route.Tools("droits")), drawer.routes)
        assertEquals(listOf(Route.Chat), drawer.pop()?.routes)
        // « Comment ça part » d'un fil Teams : Outils par-dessus, ses onglets ne s'empilent pas, retour ramène au fil
        val fromThread = BackStack().open(Route.Teams).push(Route.TeamsThread("t1~a")).push(Route.Tools()).replaceTop(Route.Tools("accords"))
        assertEquals(listOf(Route.Chat, Route.Teams, Route.TeamsThread("t1~a"), Route.Tools("accords")), fromThread.routes)
        assertEquals(Route.TeamsThread("t1~a"), fromThread.pop()?.top)
        assertEquals(fromThread, BackStack.decode(fromThread.encode()))
    }

    @Test fun `les onglets de la Carte se remplacent, « Itinéraire jusqu'ici » porte son arrivée (lot 6a)`() {
        val camping = Place(id = "l12", name = "Camping de l'Horizon", kindFr = "Camping", lat = 45.866, lon = 6.141, town = "Sévrier")
        val s = BackStack().open(Route.Carte()).replaceTop(Route.Carte("itineraire", to = camping))
        assertEquals(listOf(Route.Chat, Route.Carte("itineraire", to = camping)), s.routes)
        assertTrue(s.top.isTopLevel)
        assertEquals(s, BackStack.decode(s.encode())) // le lieu se garde avec la pile (une rotation, un processus tué)
        assertEquals(listOf(Route.Chat, Route.Carte("voyages")), s.replaceTop(Route.Carte("voyages")).routes)
        assertEquals(listOf(Route.Chat), s.pop()?.routes)
        // depuis la Position du Téléphone, « Ouvrir dans Carte » : la rubrique, seule au-dessus du chat
        assertEquals(listOf(Route.Chat, Route.Carte()), BackStack().open(Route.Phone("position")).open(Route.Carte()).routes)
    }

    @Test fun `un voyage s'ouvre par-dessus la liste, un regard se montre dans son onglet (lot 6b)`() {
        // « En faire un voyage » d'Itinéraire, « Nouveau voyage » d'Explorer : la liste, puis le voyage par-dessus
        val made = BackStack().open(Route.Carte("itineraire")).replaceTop(Route.Carte("voyages")).push(Route.Trip("640"))
        assertEquals(listOf(Route.Chat, Route.Carte("voyages"), Route.Trip("640")), made.routes)
        assertFalse(made.top.isTopLevel)
        assertEquals(Route.Carte("voyages"), made.pop()?.top) // supprimé, ou « retour » : la liste
        // introuvable (404) : « Tes voyages » rouvre la rubrique seule
        assertEquals(listOf(Route.Chat, Route.Carte("voyages")), made.open(Route.Carte("voyages")).routes)
        // un regard d'Explorer « Ouvrir dans Itinéraire » : l'onglet remplacé, le regard avec lui ; « Ouvrir le voyage » s'empile
        val look = BackStack().push(Route.Carte("explorer", look = "812")).replaceTop(Route.Carte("itineraire", look = "812"))
        assertEquals(listOf(Route.Chat, Route.Carte("itineraire", look = "812")), look.routes)
        assertEquals(Route.Trip("640"), look.push(Route.Trip("640")).top)
        assertEquals(look, BackStack.decode(look.encode()))
    }

    @Test fun `une pile de rubriques se garde et se relit`() {
        val s = BackStack().open(Route.Carte("voyages")).push(Route.Trip("12")).push(Route.Mind)
        assertEquals(s, BackStack.decode(s.encode()))
        assertEquals(listOf(Route.Chat, Route.Mail, Route.MailDrafts), BackStack.forDeepLink(DeepLinks.MAIL_DRAFTS).routes)
    }

    @Test fun `la conversation est à l'écran seulement au sommet de la pile`() {
        assertTrue(BackStack().showsChat)
        assertFalse(BackStack().open(Route.Mail).showsChat)
        assertFalse(BackStack().push(Route.Mind).showsChat)
        assertFalse(BackStack().push(viewer).showsChat)
        assertFalse(BackStack().push(Route.Search("chat")).showsChat)
        assertTrue(BackStack().open(Route.Teams).pop()!!.showsChat)
    }
}
