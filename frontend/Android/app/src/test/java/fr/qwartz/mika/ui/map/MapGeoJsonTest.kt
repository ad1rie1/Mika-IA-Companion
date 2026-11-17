package fr.qwartz.mika.ui.map

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.moi.carte.LatLon
import fr.qwartz.mika.data.moi.carte.Scene
import fr.qwartz.mika.data.moi.carte.SceneHere
import fr.qwartz.mika.data.moi.carte.SceneLine
import fr.qwartz.mika.data.moi.carte.ScenePin
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Ce que la vraie carte pose par-dessus le fond, en GeoJSON (lon, lat) : les épingles, les tracés, la position. */
class MapGeoJsonTest {
    private val colors = MapColors(accent = 1, onAccent = 2, mika = 3, onMika = 4, raised = 5, ink = 6)

    private fun features(json: String) = MikaJson.parseToJsonElement(json).jsonObject["features"]!!.jsonArray.map { it.jsonObject }

    private fun JsonObject.prop(key: String) = this["properties"]!!.jsonObject[key]!!.jsonPrimitive.content

    @Test fun `les épingles, leur image, leur rang, ce qu'un toucher vise`() {
        val scene = Scene(
            pins = listOf(
                ScenePin("l1", 45.9, 6.1, selected = true),
                ScenePin("s", 45.8, 6.2, label = "3", minor = true),
                ScenePin("m", 45.7, 6.3, label = "2", mika = true),
            ),
        )
        val pins = features(pinsJson(scene, colors))
        assertEquals(listOf("l1", "s", "m"), pins.map { it.prop("id") })
        assertEquals(listOf("3", "0", "2"), pins.map { it.prop("rank") })
        val point = pins[0]["geometry"]!!.jsonObject["coordinates"]!!.jsonArray.map { it.jsonPrimitive.content.toDouble() }
        assertEquals(listOf(6.1, 45.9), point) // lon, lat
        // une secondaire ne porte pas son numéro ; la choisie a sa propre image
        assertTrue(pins[1].prop("icon").endsWith("-"))
        assertNotEquals(PinImages.name(scene.pins[0], colors), PinImages.name(scene.pins[0].copy(selected = false), colors))
        // un autre thème, d'autres images
        assertNotEquals(PinImages.name(scene.pins[2], colors), PinImages.name(scene.pins[2], colors.copy(mika = 9)))
    }

    @Test fun `les tracés, la position et le cercle de sa précision`() {
        val scene = Scene(
            lines = listOf(SceneLine(listOf(LatLon(45.9, 6.1), LatLon(45.8, 6.2)), mika = true, straight = true)),
            here = SceneHere(50.6365, 3.0635, accuracyM = 120.0),
        )
        val line = features(linesJson(scene)).single()
        assertEquals("true", line.prop("mika"))
        assertEquals("true", line.prop("straight"))
        assertEquals(1, features(hereJson(scene)).size)
        val ring = features(zoneJson(scene)).single()["geometry"]!!.jsonObject["coordinates"]!!.jsonArray.single().jsonArray
        assertEquals(65, ring.size)
        val first = ring.first().jsonArray.map { it.jsonPrimitive.content.toDouble() }
        val last = ring.last().jsonArray.map { it.jsonPrimitive.content.toDouble() }
        assertEquals(first[0], last[0], 1e-9) // fermé
        assertEquals(first[1], last[1], 1e-9)
        // sans rayon : le point seul ; sans position : rien
        assertEquals(0, features(zoneJson(scene.copy(here = SceneHere(50.6, 3.0)))).size)
        assertEquals(0, features(hereJson(Scene.EMPTY)).size)
    }
}
