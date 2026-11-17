package fr.qwartz.mika.ui.carte

import fr.qwartz.mika.data.moi.carte.AlongState
import fr.qwartz.mika.data.moi.carte.Place
import fr.qwartz.mika.data.moi.carte.Trip
import fr.qwartz.mika.data.moi.carte.TripDay
import fr.qwartz.mika.data.moi.carte.TripLeg
import fr.qwartz.mika.data.moi.carte.TripRoute
import fr.qwartz.mika.data.moi.carte.TripRouteDay
import fr.qwartz.mika.data.moi.carte.TripStop
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Glisser un arrêt (R4-01) : la ligne sous le doigt se retrouve par sa clé dans la liste du moment, jamais par sa place.
 * Les scénarios de la relecture : des tronçons arrivés après l'ouverture, « Sur la route » ouvert, un geste qui a changé
 * l'ordre, un autre jour. La liste « d'avant » est celle que le geste d'une poignée gardait quand sa ligne est apparue.
 */
class TripEditorRowsTest {
    private fun stop(id: String) = TripStop(id, "Arrêt $id", "", 45.0, 5.0, "", "toi")

    private val abc = Trip(id = "640", title = "Les Alpes", days = listOf(TripDay(1, "", listOf(stop("A"), stop("B"), stop("C")))))

    private fun leg(from: String, to: String) = TripLeg(from, to, 100_000.0, 3_600.0)

    private val abcRoute = TripRoute(days = listOf(TripRouteDay(1, legs = listOf(leg("A", "B"), leg("B", "C")))))

    private val closed = AlongState("640")

    /** La hauteur de chaque sorte de ligne à l'écran, en pixels. */
    private fun height(row: EditorRow): Int = when (row) {
        is EditorRow.DayHead -> 56
        is EditorRow.Stop -> 60
        is EditorRow.Leg -> 24
        EditorRow.AlongHead -> 100
        is EditorRow.AlongPlace -> 56
        else -> 48
    }

    /** La mise en page de ces lignes, l'une sous l'autre. */
    private fun layout(rows: List<EditorRow>): List<RowBox> {
        var y = 0
        return rows.map { r -> RowBox(r.key, y, height(r)).also { y += it.size } }
    }

    /** De combien glisser [stop] pour que son milieu tombe dans la moitié haute (ou basse) de la ligne [onto]. */
    private fun dyOnto(boxes: List<RowBox>, stop: String, onto: String, upper: Boolean): Float {
        val from = boxes.single { it.key == stopKey(stop) }
        val to = boxes.single { it.key == onto }
        val y = to.offset + to.size * (if (upper) 0.25f else 0.75f)
        return y - (from.offset + from.size / 2f)
    }

    @Test fun `des tronçons arrivés après l'ouverture - C lâché sur la moitié haute de B va avant B`() {
        val atOpening = editorRows(abc, null, closed, alongOpen = false)
        val now = editorRows(abc, abcRoute, closed, alongOpen = false)
        assertEquals(listOf("day:1", "stop:A", "leg:B", "stop:B", "leg:C", "stop:C", "add:1", "add-day"), now.map { it.key })
        val boxes = layout(now)
        val dy = dyOnto(boxes, "C", "stop:B", upper = true)
        assertEquals(DropTarget(1, "B"), dropTarget(boxes, now, "C", dy))
        // la liste de l'ouverture (sans tronçons) : la place de B à l'écran y désigne C, sa clé désigne bien B
        assertTrue(atOpening.indexOfFirst { it.key == "stop:C" } == boxes.indexOfFirst { it.key == "stop:B" })
        assertEquals(DropTarget(1, "B"), dropTarget(boxes, atOpening, "C", dy))
        // A lâché sous C : à la fin du jour, pas sur « Ajouter un jour »
        assertEquals(DropTarget(1, null), dropTarget(boxes, now, "A", dyOnto(boxes, "A", "stop:C", upper = false)))
        assertEquals(DropTarget(1, null), dropTarget(boxes, atOpening, "A", dyOnto(boxes, "A", "stop:C", upper = false)))
        // sur un tronçon : avant l'arrêt où il arrive
        assertEquals(DropTarget(1, "C"), dropTarget(boxes, now, "A", dyOnto(boxes, "A", "leg:C", upper = true)))
    }

    @Test fun `« Sur la route » ouvert - ses lignes en tête ne décalent rien, et un lieu n'est pas une cible`() {
        val along = AlongState("640", cat = "dormir", places = listOf(Place(id = "l1", name = "Camping"), Place(id = "l2", name = "Gîte")))
        val before = editorRows(abc, abcRoute, closed, alongOpen = false)
        val now = editorRows(abc, abcRoute, along, alongOpen = true)
        assertEquals(listOf("along-head", "along:0", "along:1", "along-end", "day:1"), now.take(5).map { it.key })
        val boxes = layout(now)
        val dy = dyOnto(boxes, "B", "stop:A", upper = true)
        assertEquals(DropTarget(1, "A"), dropTarget(boxes, now, "B", dy))
        assertEquals(DropTarget(1, "A"), dropTarget(boxes, before, "B", dy))
        // lâché sur un lieu de « Sur la route » : rien
        assertNull(dropTarget(boxes, now, "B", dyOnto(boxes, "B", "along:1", upper = true)))
        // fermé, ou sous deux arrêts : aucune de ses lignes
        assertEquals(before.map { it.key }, editorRows(abc, abcRoute, along, alongOpen = false).map { it.key })
        val lone = abc.copy(days = listOf(TripDay(1, "", listOf(stop("A")))))
        assertTrue(editorRows(lone, null, along, alongOpen = true).none { it is EditorRow.AlongHead })
    }

    @Test fun `un geste a changé l'ordre - l'arrêt d'après se lit dans la liste du moment`() {
        val before = editorRows(abc, null, closed, alongOpen = false)
        // B est monté avant A (le trajet se recalcule : pas de tronçons)
        val moved = abc.copy(days = listOf(TripDay(1, "", listOf(stop("B"), stop("A"), stop("C")))))
        val now = editorRows(moved, null, closed, alongOpen = false)
        val boxes = layout(now)
        val dy = dyOnto(boxes, "C", "stop:B", upper = false)
        // sous B : avant A, qui le suit maintenant
        assertEquals(DropTarget(1, "A"), dropTarget(boxes, now, "C", dy))
        // la liste d'avant le geste dirait « avant C » (lui-même) : le geste ne ferait rien — d'où la liste du moment
        assertEquals(DropTarget(1, "C"), dropTarget(boxes, before, "C", dy))
    }

    @Test fun `un autre jour - sa tête, ses arrêts, sa fin`() {
        val trip = Trip(id = "640", days = listOf(TripDay(1, "", listOf(stop("A"), stop("B"))), TripDay(2, "", listOf(stop("C"), stop("D")))))
        val route = TripRoute(days = listOf(TripRouteDay(1, legs = listOf(leg("A", "B"))), TripRouteDay(2, legs = listOf(leg("B", "C"), leg("C", "D")))))
        val atOpening = editorRows(trip, null, closed, alongOpen = false)
        val now = editorRows(trip, route, closed, alongOpen = false)
        val boxes = layout(now)
        for (rows in listOf(now, atOpening)) {
            assertEquals(DropTarget(2, "C"), dropTarget(boxes, rows, "A", dyOnto(boxes, "A", "day:2", upper = true)))
            assertEquals(DropTarget(2, "D"), dropTarget(boxes, rows, "A", dyOnto(boxes, "A", "stop:D", upper = true)))
            assertEquals(DropTarget(2, null), dropTarget(boxes, rows, "A", dyOnto(boxes, "A", "stop:D", upper = false)))
            assertEquals(DropTarget(2, null), dropTarget(boxes, rows, "A", dyOnto(boxes, "A", "add:2", upper = true)))
            // remonté au jour 1, sous A : avant B
            assertEquals(DropTarget(1, "B"), dropTarget(boxes, rows, "D", dyOnto(boxes, "D", "stop:A", upper = false)))
        }
        // un jour vide : sa ligne « Aucun arrêt » le vise, à sa fin
        val gap = trip.copy(days = trip.days + TripDay(3, "", emptyList()))
        val rows = editorRows(gap, route, closed, alongOpen = false)
        val b = layout(rows)
        assertEquals(DropTarget(3, null), dropTarget(b, rows, "A", dyOnto(b, "A", "empty:3", upper = true)))
        // la ligne glissée hors de la mise en page (sortie de l'écran) : rien
        assertNull(dropTarget(b.filter { it.key != "stop:A" }, rows, "A", 10f))
    }
}
