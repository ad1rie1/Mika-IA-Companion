package fr.qwartz.mika.ui.mail

import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Les ordres d'un modèle de Mail à son écran (R2-03, R2-07) : seul l'écran de la visite où le geste a commencé les
 * suit. Celui d'une visite quittée ne referme pas l'écran ouvert ensuite, même sur le même mail ; une rotation (la même
 * visite) les garde.
 */
class VisitOrdersTest {
    private suspend fun VisitOrders<String>.next(visit: String): String? = withTimeoutOrNull(200) { of(visit).first() }

    @Test fun `le geste fini sur son écran le fait bouger, même après une rotation`() = runBlocking {
        val orders = VisitOrders<String>()
        orders.open("v1")
        orders.send("v1", "retour")
        // l'écran tourne : la même visite revient et lit ce qui l'attendait
        orders.open("v1")
        assertEquals("retour", orders.next("v1"))
    }

    @Test fun `quitté avant la réponse - l'écran suivant ne reçoit rien`() = runBlocking {
        val orders = VisitOrders<String>()
        orders.open("v1")
        orders.send("v1", "retour")
        orders.open("v2")
        assertNull(orders.next("v2"))
    }

    @Test fun `la réponse arrive après l'ouverture suivante - rien`() = runBlocking {
        val orders = VisitOrders<String>()
        orders.open("v1")
        orders.open("v2")
        orders.send("v1", "retour")
        assertNull(orders.next("v2"))
        assertNull(orders.next("v1"))
    }
}
