package fr.qwartz.mika.ui.components

import fr.qwartz.mika.ui.Route
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Où aller après un geste de Paramètres : seulement sur la page qui l'a fait. Un « Retirer » qui répond après qu'on a
 * quitté sa page ne ferme pas la page suivante de la même sorte (une autre boîte), une création ne la remplace pas.
 */
class PageMovesTest {
    private suspend fun PageMoves.next(): Move? = withTimeoutOrNull(200) { moved.first() }

    @Test fun `le geste fini sur sa page la fait bouger`() = runBlocking {
        val moves = PageMoves()
        moves.send(Move.Back, from = "e1|boite-a", now = "e1|boite-a")
        assertEquals(Move.Back, moves.next())
    }

    @Test fun `quittée avant la réponse - la page suivante de la même sorte ne reçoit rien`() = runBlocking {
        val moves = PageMoves()
        // « Retirer » la boîte A, retour avant la réponse : personne n'écoute, le geste attend
        moves.send(Move.Back, from = "e1|boite-a", now = "e1|boite-a")
        // la boîte B s'ouvre
        moves.reopened()
        assertNull(moves.next())
    }

    @Test fun `la réponse arrive après l'ouverture suivante - rien`() = runBlocking {
        val moves = PageMoves()
        moves.reopened()
        moves.send(Move.Replace(Route.SettingsPage("boite", "boite-c")), from = "e1|", now = "e2|")
        assertNull(moves.next())
    }
}
