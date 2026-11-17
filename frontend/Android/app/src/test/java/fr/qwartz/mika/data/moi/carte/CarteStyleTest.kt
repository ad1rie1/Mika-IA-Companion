package fr.qwartz.mika.data.moi.carte

import fr.qwartz.mika.core.MikaJson
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Le style de la carte : les calques tirés du web dans les assets (`tools/carte_style.mjs`, dont `--check` garde la
 * fraîcheur), et ce que l'app y pose au moment de charger — les tuiles, les polices et les icônes de ce serveur seul.
 */
class CarteStyleTest {
    private val base = "http://192.168.1.22:8001"
    private val lille = MapFond(
        ready = true,
        kind = MapFond.KIND_VECTOR,
        minzoom = 0,
        maxzoom = 15,
        bounds = listOf(-5.2, 41.3, 9.6, 51.1),
        attribution = "© OpenStreetMap",
        tiles = "/api/moi/carte/fond/tiles/{z}/{x}/{y}?v=1a2b3c4d5e6f",
        glyphs = "/api/moi/carte/fond/fonts/{fontstack}/{range}.pbf?v=1a2b3c4d5e6f",
        sprite = "/api/moi/carte/fond/sprites/~1a2b3c4d5e6f/v4",
    )

    /** Les calques d'un thème, tels que l'app les lit (les tests JVM tournent depuis le dossier du module). */
    private fun layers(dark: Boolean): CarteStyle.Layers =
        CarteStyle.parse(File("src/main/assets/${CarteStyle.asset(dark)}").readText())!!

    private fun built(fond: MapFond, dark: Boolean = false, at: String = base): JsonObject =
        MikaJson.parseToJsonElement(CarteStyle.build(fond, at, layers(dark))!!).jsonObject

    private fun JsonObject.str(key: String) = (this[key] as? JsonPrimitive)?.content

    /** Toutes les chaînes d'un JSON, à toute profondeur. */
    private fun strings(e: JsonElement): List<String> = when (e) {
        is JsonPrimitive -> if (e.isString) listOf(e.content) else emptyList()
        is JsonArray -> e.flatMap { strings(it) }
        is JsonObject -> e.values.flatMap { strings(it) }
    }

    @Test fun `les calques clairs et sombres sont tirés du web, sans les points d'intérêt qui n'apprennent rien`() {
        for (dark in listOf(false, true)) {
            val l = layers(dark)
            assertEquals(if (dark) "dark" else "light", l.flavor)
            assertTrue(l.layers.size > 40)
            val pois = l.layers.map { it.jsonObject }.single { it.str("id") == "pois" }
            val filter = pois["filter"].toString()
            assertTrue(filter.contains("\"attraction\"") && filter.contains("\"immeuble\"") && filter.contains("\"hôtel particulier\""))
            // chaque calque qui lit des tuiles lit celles du fond (`carte`), et les noms sont en français
            assertTrue(l.layers.map { it.jsonObject }.all { it.str("source") == null || it.str("source") == CarteStyle.SOURCE })
            assertTrue(l.layers.toString().contains("name:fr"))
        }
        assertNull(CarteStyle.parse("pas du json"))
        assertNull(CarteStyle.parse("""{"layers":[]}"""))
    }

    @Test fun `une carte vectorielle, ses tuiles, ses polices et ses icônes sur ce serveur, rien d'autre`() {
        val style = built(lille, dark = true)
        val source = style["sources"]!!.jsonObject[CarteStyle.SOURCE]!!.jsonObject
        assertEquals("vector", source.str("type"))
        // collés tels quels : {z}, {fontstack} restent pour MapLibre
        assertEquals("$base/api/moi/carte/fond/tiles/{z}/{x}/{y}?v=1a2b3c4d5e6f", source["tiles"]!!.jsonArray.single().jsonPrimitive.content)
        assertEquals("$base/api/moi/carte/fond/fonts/{fontstack}/{range}.pbf?v=1a2b3c4d5e6f", style.str("glyphs"))
        assertEquals("$base/api/moi/carte/fond/sprites/~1a2b3c4d5e6f/v4/dark", style.str("sprite"))
        assertEquals(listOf(-5.2, 41.3, 9.6, 51.1), source["bounds"]!!.jsonArray.map { it.jsonPrimitive.content.toDouble() })
        assertEquals("© OpenStreetMap", source.str("attribution"))
        assertEquals("15", source.str("maxzoom"))
        // aucune adresse du dehors, nulle part dans le style
        val addresses = strings(style).filter { it.startsWith("http") || it.startsWith("//") || it.contains("://") }
        assertTrue(addresses.isNotEmpty())
        assertTrue(addresses.toString(), addresses.all { it.startsWith("$base/") })
        assertEquals(layers(true).layers.size, style["layers"]!!.jsonArray.size)
    }

    @Test fun `sans polices, ses noms s'effacent, sans icônes, ses symboles aussi`() {
        val noFonts = built(lille.copy(glyphs = null))
        assertNull(noFonts.str("glyphs"))
        assertFalse(noFonts["layers"].toString().contains("\"text-field\""))
        val noIcons = built(lille.copy(sprite = null))
        assertNull(noIcons.str("sprite"))
        assertFalse(noIcons["layers"].toString().contains("\"icon-image\""))
        assertTrue(noIcons["layers"].toString().contains("\"text-field\""))
        val bare = built(lille.copy(glyphs = null, sprite = null))
        assertTrue(bare["layers"]!!.jsonArray.none { it.jsonObject.str("type") == "symbol" })
        assertTrue(bare["layers"]!!.jsonArray.any { it.jsonObject.str("type") == "fill" })
    }

    @Test fun `une carte image, un style raster simple, une vectorielle sans ses calques, aucun`() {
        val raster = MikaJson.parseToJsonElement(CarteStyle.build(lille.copy(kind = MapFond.KIND_IMAGE, bounds = null), base, null)!!).jsonObject
        val source = raster["sources"]!!.jsonObject[CarteStyle.SOURCE]!!.jsonObject
        assertEquals("raster", source.str("type"))
        assertEquals("256", source.str("tileSize"))
        assertNull(source["bounds"])
        assertEquals(1, raster["layers"]!!.jsonArray.size)
        assertNull(raster.str("glyphs"))
        assertNull(CarteStyle.build(lille, base, null))
    }

    /** Un JSON dont les nombres se comparent par leur valeur (`15` et `15.0` du web et de Kotlin), le reste tel quel. */
    private fun canon(e: JsonElement): JsonElement = when (e) {
        is JsonObject -> JsonObject(e.mapValues { canon(it.value) })
        is JsonArray -> JsonArray(e.map { canon(it) })
        is JsonPrimitive -> if (e.isString) e else e.content.toDoubleOrNull()?.let { JsonPrimitive(it) } ?: e
    }

    /**
     * R4-10 : ce que `CarteStyle` réécrit à la main — la source, `sprite` et `glyphs`, le style raster, la règle qui retire
     * texte et icônes, toute clé racine — est ce que le web compose pour les mêmes entrées. Les références sont le style
     * complet de `mapstyle.ts` pour quelques cartes servies types, écrit par `tools/carte_style.mjs` (`--check` les garde
     * à jour avec le web).
     */
    @Test fun `l'app compose le même style que le web pour les cartes servies de référence`() {
        val text = requireNotNull(javaClass.classLoader?.getResource("carte/styles-web.json")) { "carte/styles-web.json" }.readText()
        val cases = MikaJson.parseToJsonElement(text).jsonObject["cases"]!!.jsonArray.map { it.jsonObject }
        assertTrue(cases.size >= 5)
        for (case in cases) {
            val name = case.str("name")
            val fond = MikaJson.decodeFromJsonElement(MapFond.serializer(), case["info"]!!)
            val dark = case["dark"]!!.jsonPrimitive.content.toBoolean()
            val at = case.str("base")!!
            // comme l'écran : les calques du thème pour une carte vectorielle, aucun pour une carte en images
            val layers = if (fond.kind == MapFond.KIND_IMAGE) null else layers(dark)
            val app = MikaJson.parseToJsonElement(CarteStyle.build(fond, at, layers)!!)
            val web = case["style"]!!
            val a = canon(app).jsonObject
            val w = canon(web).jsonObject
            assertEquals("$name : les clés du style", w.keys, a.keys)
            for (key in w.keys.filter { it != "layers" }) assertEquals("$name : $key", w[key], a[key])
            val wl = w["layers"]!!.jsonArray
            val al = a["layers"]!!.jsonArray
            assertEquals("$name : les calques", wl.map { it.jsonObject.str("id") }, al.map { it.jsonObject.str("id") })
            wl.zip(al).forEach { (x, y) -> assertEquals("$name : le calque ${x.jsonObject.str("id")}", x, y) }
        }
    }

    @Test fun `un serveur sous un préfixe, les chemins se posent sur son adresse`() {
        val style = built(lille, at = "https://mika.example.ts.net/mika")
        assertEquals(
            "https://mika.example.ts.net/mika/api/moi/carte/fond/sprites/~1a2b3c4d5e6f/v4/light",
            style.str("sprite"),
        )
        assertNotNull(style["sources"])
    }
}
