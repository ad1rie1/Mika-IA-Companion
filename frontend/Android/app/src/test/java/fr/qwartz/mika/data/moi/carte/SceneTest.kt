package fr.qwartz.mika.data.moi.carte

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs

/**
 * Ce qu'une carte montre et comment une vue la cadre (`map/scene.ts`, `map/mapgeo.ts`, `hereFocus` et `pinRank` de
 * `map/view.ts`), portés du web : leurs cas viennent de `frontendv2/src/map/map.test.ts`.
 */
class SceneTest {
    private val lille = MapFond(
        ready = true,
        kind = "vecteur",
        bounds = listOf(-5.2, 41.3, 9.6, 51.1),
        tiles = "/api/moi/carte/fond/tiles/{z}/{x}/{y}?v=1a2b3c4d5e6f",
    )

    @Test fun `ce que la carte du serveur couvre`() {
        assertTrue(covers(lille, 50.63, 3.06))
        assertFalse(covers(lille, 40.4, -3.7)) // Madrid : hors de la zone de l'archive
        assertTrue(covers(lille.copy(bounds = null), -33.8, 151.2)) // un serveur {z}/{x}/{y} : partout
        assertFalse(covers(lille.copy(ready = false), 50.63, 3.06))
        assertFalse(covers(lille.copy(tiles = ""), 50.63, 3.06))
        assertFalse(covers(null, 50.63, 3.06))
        assertTrue(coversAll(lille, listOf(LatLon(50.6, 3.0), LatLon(48.85, 2.35))))
        assertFalse(coversAll(lille, emptyList()))
        assertEquals(Bounds(-5.2, 41.3, 9.6, 51.1), lille.zone)
        assertNull(lille.copy(bounds = listOf(9.6, 41.3, -5.2, 51.1)).zone) // ouest ≥ est : illisible
    }

    @Test fun `un cercle, un zoom, une distance, une zone`() {
        val ring = circle(50.6365, 3.0635, 120.0)
        assertEquals(65, ring.size)
        assertEquals(ring.first().lat, ring.last().lat, 1e-9) // fermé
        val north = ring.maxOf { it.lat }
        assertEquals(120.0, meters(LatLon(50.6365, 3.0635), LatLon(north, 3.0635)), 0.5)
        assertEquals(16.0, zoomFor(12.0), 0.0) // quelques mètres : le quartier autour
        assertEquals(11.0, zoomFor(50_000.0), 0.0) // au plus large
        assertEquals(17 - kotlin.math.log2(400.0 / 40), zoomFor(400.0), 1e-9)
        assertTrue(abs(meters(LatLon(50.6365, 3.0635), LatLon(48.8566, 2.3522)) - 204_000) < 2_000) // Lille-Paris
        assertEquals(Bounds(2.0, 45.0, 3.0, 50.0), boundsOf(listOf(LatLon(50.0, 3.0), LatLon(45.0, 2.0), LatLon(Double.NaN, 9.0))))
        assertNull(boundsOf(emptyList()))
        val w = widened(Bounds(3.0, 50.0, 3.0, 50.0))
        assertEquals(0.02, w.east - w.west, 1e-9)
        assertEquals(0.02, w.north - w.south, 1e-9)
    }

    @Test fun `seules les coordonnées valides se posent`() {
        val clean = cleanScene(
            Scene(
                pins = listOf(ScenePin("a", 50.6, 3.0), ScenePin("b", 120.0, 3.0)),
                lines = listOf(SceneLine(listOf(LatLon(50.0, 3.0), LatLon(Double.NaN, 3.0))), SceneLine(listOf(LatLon(50.0, 3.0), LatLon(49.0, 3.0)))),
                here = SceneHere(50.6, 3.0, accuracyM = -4.0),
            ),
        )
        assertEquals(listOf("a"), clean.pins.map { it.id })
        assertEquals(1, clean.lines.size) // un tracé d'un seul point valide ne se pose pas
        assertEquals(SceneHere(50.6, 3.0), clean.here) // une précision illisible : le point seul
        assertNull(cleanScene(Scene(here = SceneHere(Double.NaN, 3.0))).here)
    }

    @Test fun `la zone d'une scène tient le cercle de la position`() {
        val here = SceneHere(50.6365, 3.0635, accuracyM = 500.0)
        val b = sceneBounds(Scene(here = here), 0.0)!!
        assertEquals(500.0 / M_PER_DEG, b.north - here.lat, 1e-9)
        assertTrue(b.east - b.west > b.north - b.south) // une longitude vaut moins qu'une latitude à Lille
        assertNull(sceneBounds(Scene.EMPTY))
        // une position seule : quelques fois son rayon, 300 m au moins ; avec des épingles : l'élargissement de la vue
        assertEquals(HERE_SPAN_M / M_PER_DEG, hereSpan(Scene(here = SceneHere(50.0, 3.0, 12.0)))!!, 1e-12)
        assertEquals(5 * 500.0 / M_PER_DEG, hereSpan(Scene(here = here))!!, 1e-12)
        assertNull(hereSpan(Scene(pins = listOf(ScenePin("a", 50.0, 3.0)), here = here)))
        assertNull(hereSpan(Scene(here = SceneHere(50.0, 3.0))))
    }

    @Test fun `le cadrage, serré sur l'écran Carte, un quartier sur une miniature`() {
        assertEquals(Framing(0.002, 56, 17.0), framingFor(true))
        assertEquals(Framing(0.02, 18, 12.5), framingFor(false))
        val two = Scene(pins = listOf(ScenePin("a", 50.6365, 3.0635), ScenePin("b", 50.6366, 3.0636)))
        val screen = sceneFraming(two, interactive = true)!!
        assertEquals(0.002, screen.bounds.east - screen.bounds.west, 1e-9) // des lieux voisins se départagent
        assertEquals(0.02, sceneFraming(two, interactive = false)!!.bounds.east - sceneFraming(two, interactive = false)!!.bounds.west, 1e-9)
        assertNull(sceneFraming(Scene.EMPTY, true))
    }

    @Test fun `une position seule s'ouvre centrée, au zoom de sa précision`() {
        val focus = hereFocus(Scene(here = SceneHere(50.6365, 3.0635, 12.0)))
        assertEquals(HereFocus(LatLon(50.6365, 3.0635), 16.0), focus)
        assertNull(hereFocus(Scene(here = SceneHere(50.6365, 3.0635)))) // sans rayon : le cadrage d'une zone
        assertNull(hereFocus(Scene(pins = listOf(ScenePin("a", 50.0, 3.0)), here = SceneHere(50.6, 3.0, 12.0))))
    }

    @Test fun `ce qui se pose au-dessus de quoi, et ce qui change entre deux scènes`() {
        assertEquals(0, pinRank(ScenePin("s", 0.0, 0.0, minor = true)))
        assertEquals(1, pinRank(ScenePin("t", 0.0, 0.0)))
        assertEquals(2, pinRank(ScenePin("m", 0.0, 0.0, mika = true)))
        assertEquals(3, pinRank(ScenePin("c", 0.0, 0.0, mika = true, selected = true)))
        val a = Scene(pins = listOf(ScenePin("a", 50.0, 3.0)), lines = listOf(SceneLine(listOf(LatLon(50.0, 3.0), LatLon(49.0, 2.0)))))
        assertEquals(sceneKey(a), sceneKey(a.copy()))
        assertNotEquals(sceneKey(a), sceneKey(a.copy(pins = listOf(ScenePin("a", 50.0, 3.0, selected = true)))))
        assertNotEquals(sceneKey(a), sceneKey(a.copy(lines = listOf(SceneLine(listOf(LatLon(50.0, 3.0), LatLon(49.0, 2.1)))))))
        assertNotEquals(sceneKey(a), sceneKey(a.copy(here = SceneHere(50.0, 3.0))))
        val straight = straightLine(listOf(LatLon(50.0, 3.0), LatLon(200.0, 3.0), LatLon(49.0, 2.0)))
        assertNotNull(straight)
        assertTrue(straight!!.straight)
        assertEquals(2, straight.points.size)
        assertNull(straightLine(listOf(LatLon(50.0, 3.0))))
    }
}
