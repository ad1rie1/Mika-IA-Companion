package fr.qwartz.mika.ui

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
}
