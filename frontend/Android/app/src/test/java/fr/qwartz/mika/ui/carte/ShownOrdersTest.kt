package fr.qwartz.mika.ui.carte

import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.withTimeoutOrNull
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * « En faire un voyage » fini hors de l'onglet Itinéraire (R4-09) : l'ordre d'ouvrir le voyage ne vaut que pour l'onglet
 * à l'écran quand la création finit ; fini ailleurs, l'appelant le dit autrement (un toast avec « Ouvrir »), et l'onglet
 * rouvert plus tard n'emmène nulle part.
 */
class ShownOrdersTest {
    private suspend fun ShownOrders<String>.next(): String? = withTimeoutOrNull(100) { flow.first() }

    @Test fun `fini avec l'onglet à l'écran - suivi`() = runTest {
        val orders = ShownOrders<String>()
        orders.enter()
        assertTrue(orders.send("640"))
        assertEquals("640", orders.next())
    }

    @Test fun `fini ailleurs - rendu à l'appelant, rien n'attend le retour de l'onglet`() = runTest {
        val orders = ShownOrders<String>()
        orders.enter()
        orders.leave()
        assertFalse(orders.send("640"))
        orders.enter()
        assertNull(orders.next())
    }

    @Test fun `un ordre pas encore suivi quand l'onglet s'en va est jeté, une rotation ne perd rien`() = runTest {
        val orders = ShownOrders<String>()
        orders.enter()
        assertTrue(orders.send("640"))
        orders.leave()
        orders.enter()
        assertNull(orders.next())
        // une rotation : le nouvel écran paraît avant que l'ancien s'en aille
        orders.enter()
        assertTrue(orders.send("700"))
        orders.leave()
        assertEquals("700", orders.next())
    }
}
