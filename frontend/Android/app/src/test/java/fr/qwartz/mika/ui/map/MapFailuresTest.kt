package fr.qwartz.mika.ui.map

import fr.qwartz.mika.data.moi.carte.LiveFailure
import fr.qwartz.mika.data.moi.carte.MapFond
import fr.qwartz.mika.data.moi.carte.ScenePin
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow

/**
 * Ce qui ne s'est pas dessiné reste à la carte où c'est arrivé (R4-02) : un écran ou une miniature, pas toute la session ;
 * un écran rouvert, ou un autre fond servi, réessaie. Une miniature restée au plan ne prend pas de place (R4-06). Les
 * numéros des épingles dans les couleurs faites pour aller sur elles, en sombre aussi (R4-07).
 */
class MapFailuresTest {
    private val fond = MapFond(ready = true, tiles = "/api/moi/carte/fond/tiles/{z}/{x}/{y}?v=1", bounds = listOf(-5.2, 41.3, 9.6, 51.1))

    @Test fun `l'échec d'un écran reste à lui, se lève avec un autre fond, et un écran rouvert réessaie`() {
        val explorer = LiveRefusal()
        val trip = LiveRefusal()
        explorer.fail(fond, LiveFailure.TILES)
        assertEquals(LiveFailure.TILES, explorer.failure(fond))
        // la Carte d'un voyage, Téléphone › Position, les miniatures : rien de leur côté
        assertNull(trip.failure(fond))
        // le fond relu, le même : l'échec tient ; un autre fond servi (relu après une mise à jour) : il réessaie
        assertEquals(LiveFailure.TILES, explorer.failure(fond.copy()))
        assertNull(explorer.failure(fond.copy(tiles = "/api/moi/carte/fond/tiles/{z}/{x}/{y}?v=2")))
        assertNull(explorer.failure(null))
        // l'écran rouvert a la sienne, neuve
        assertNull(LiveRefusal().failure(fond))
    }

    @Test fun `une miniature en échec rend sa place et garde son plan, les autres continuent`() {
        val slots = MiniSlots(max = 2)
        assertTrue(slots.hold("a", wants = true))
        assertTrue(slots.hold("b", wants = true))
        assertFalse(slots.hold("c", wants = true))
        val freed = slots.freed
        // les tuiles de « a » échouent : son refus est le sien, gardé par la liste (sortie puis revenue, elle le garde)
        slots.refusal("a").fail(fond, LiveFailure.TILES)
        assertEquals(LiveFailure.TILES, slots.refusal("a").failure(fond))
        assertNull(slots.refusal("b").failure(fond))
        assertNull(slots.refusal("c").failure(fond))
        // elle ne dessine plus : sa place se rend, une autre visible la prend
        assertFalse(slots.hold("a", wants = false))
        assertTrue(slots.freed > freed)
        assertTrue(slots.hold("c", wants = true))
        assertTrue(slots.hold("b", wants = true))
    }

    @Test fun `une miniature restée au plan ne prend aucune place`() {
        val slots = MiniSlots()
        // quatre notes hors de la zone du fond, puis une dans la zone
        for (k in listOf("n1", "n2", "n3", "n4")) assertFalse(slots.hold(k, wants = false))
        assertTrue(slots.hold("n5", wants = true))
        // une miniature qui avait sa place et ne dessine plus (sa scène vidée après une relecture) la rend
        assertTrue(slots.hold("n6", wants = true))
        assertTrue(slots.hold("n7", wants = true))
        assertTrue(slots.hold("n8", wants = true))
        assertFalse(slots.hold("n9", wants = true))
        slots.hold("n6", wants = false)
        assertTrue(slots.hold("n9", wants = true))
    }

    // ── R4-07 ──

    private fun luminance(argb: Int): Double {
        fun channel(c: Int): Double {
            val s = c / 255.0
            return if (s <= 0.03928) s / 12.92 else ((s + 0.055) / 1.055).pow(2.4)
        }
        return 0.2126 * channel(argb shr 16 and 0xFF) + 0.7152 * channel(argb shr 8 and 0xFF) + 0.0722 * channel(argb and 0xFF)
    }

    private fun contrast(a: Int, b: Int): Double {
        val la = luminance(a)
        val lb = luminance(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
    }

    @Test fun `le numéro d'une épingle prend la couleur faite pour son corps, lisible en sombre`() {
        // le thème sombre de l'app : l'indigo (`primary`, `onPrimary`) et le rose de Mika (`fill`, `onFill`)
        val primary = 0xFFC1C1FF.toInt()
        val onPrimary = 0xFF22217A.toInt()
        val pink = 0xFFFF76A5.toInt()
        val onPink = 0xFF3E001D.toInt()
        val white = 0xFFFFFFFF.toInt()
        val yours = ScenePin("1", 45.0, 6.0, label = "1")
        val hers = yours.copy(mika = true)
        assertEquals(onPrimary, pinInk(yours, onPrimary, onPink))
        assertEquals(onPink, pinInk(hers, onPrimary, onPink))
        assertTrue(contrast(pinInk(yours, onPrimary, onPink), primary) >= 4.5)
        assertTrue(contrast(pinInk(hers, onPrimary, onPink), pink) >= 4.5)
        // le blanc d'avant, sur ces mêmes corps : illisible
        assertTrue(contrast(white, primary) < 2.0)
        assertTrue(contrast(white, pink) < 3.0)
    }
}
