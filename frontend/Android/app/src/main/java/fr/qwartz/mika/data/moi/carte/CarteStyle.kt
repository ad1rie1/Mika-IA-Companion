package fr.qwartz.mika.data.moi.carte

import fr.qwartz.mika.core.MikaJson
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.putJsonObject

/**
 * Le style d'une carte (ADR 0193, 0194), sans MapLibre : la carte de ce serveur seulement — ses tuiles, ses polices,
 * ses icônes —, claire ou sombre. C'est la moitié de `frontend/Web/src/map/mapstyle.ts` qui dépend de la carte servie ;
 * l'autre — les calques de Protomaps, leurs couleurs, leurs noms en français, sans les points d'intérêt qui n'apprennent
 * rien — est tirée du web par `frontend/Android/tools/carte_style.mjs` dans les assets (`carte/style-clair.json`,
 * `carte/style-sombre.json`), jamais écrite à la main.
 *
 * Les chemins du serveur se collent tels quels sur son adresse ([base] : l'adresse canonique de la session) : `{z}`,
 * `{fontstack}` y restent, et MapLibre les remplace. Sans polices, les noms s'effacent ; sans icônes, les symboles
 * aussi — jamais une police ou une planche venue d'ailleurs. Une carte `image` : un style raster simple.
 */
object CarteStyle {
    /** La source du fond, celle des calques tirés du web. */
    const val SOURCE = "carte"
    const val ASSET_LIGHT = "carte/style-clair.json"
    const val ASSET_DARK = "carte/style-sombre.json"

    /** La planche d'icônes et ses calques, tels que l'outil les a tirés du web. */
    data class Layers(val flavor: String, val layers: JsonArray)

    /** Lire un fichier de l'outil ; illisible (un asset abîmé) : `null`, et la carte garde son plan. */
    fun parse(text: String): Layers? = try {
        val root = MikaJson.parseToJsonElement(text).jsonObject
        val flavor = (root["flavor"] as? JsonPrimitive)?.content ?: return null
        val layers = root["layers"]?.jsonArray ?: return null
        Layers(flavor, layers)
    } catch (_: IllegalArgumentException) {
        null
    }

    /** L'asset d'un thème. */
    fun asset(dark: Boolean): String = if (dark) ASSET_DARK else ASSET_LIGHT

    /**
     * Le style complet, en JSON, de [fond] sur ce serveur ([base]) ; [layers] : les calques du thème (inutiles pour une
     * carte `image`). Une carte vectorielle sans ses calques (un asset illisible) n'a pas de style : `null`, le plan.
     */
    fun build(fond: MapFond, base: String, layers: Layers?): String? {
        val at = { path: String -> base.trimEnd('/') + path }
        if (fond.kind != MapFond.KIND_IMAGE && layers == null) return null
        val style = if (fond.kind == MapFond.KIND_IMAGE || layers == null) {
            buildJsonObject {
                put("version", 8)
                putJsonObject("sources") { put(SOURCE, source(fond, "raster", at)) }
                putJsonArray("layers") {
                    add(buildJsonObject { put("id", SOURCE); put("type", "raster"); put("source", SOURCE) })
                }
            }
        } else {
            val glyphs = fond.glyphs?.takeIf { it.isNotBlank() }
            val sprite = fond.sprite?.takeIf { it.isNotBlank() }
            buildJsonObject {
                put("version", 8)
                if (glyphs != null) put("glyphs", at(glyphs))
                if (sprite != null) put("sprite", "${at(sprite)}/${layers.flavor}")
                putJsonObject("sources") { put(SOURCE, source(fond, "vector", at)) }
                put("layers", kept(layers.layers, glyphs != null, sprite != null))
            }
        }
        return style.toString()
    }

    /** La source du fond : ses tuiles sur ce serveur, sa mention, ses zooms et sa zone. */
    private fun source(fond: MapFond, type: String, at: (String) -> String): JsonObject = buildJsonObject {
        put("type", type)
        putJsonArray("tiles") { add(JsonPrimitive(at(fond.tiles))) }
        if (type == "raster") put("tileSize", 256)
        put("attribution", fond.attribution.ifBlank { "© OpenStreetMap" })
        put("minzoom", fond.minzoom)
        put("maxzoom", fond.maxzoom)
        fond.zone?.let { z ->
            putJsonArray("bounds") {
                add(JsonPrimitive(z.west))
                add(JsonPrimitive(z.south))
                add(JsonPrimitive(z.east))
                add(JsonPrimitive(z.north))
            }
        }
    }

    /**
     * Les calques que cette carte peut dessiner : un symbole perd son texte sans polices, son icône sans planche, et
     * s'efface s'il ne lui reste ni l'un ni l'autre (le web fait pareil, `mapStyle`).
     */
    fun kept(layers: JsonArray, glyphs: Boolean, sprite: Boolean): JsonArray = buildJsonArray {
        for (element in layers) {
            val layer = element as? JsonObject ?: continue
            if ((layer["type"] as? JsonPrimitive)?.content != "symbol") {
                add(layer)
                continue
            }
            val layout = (layer["layout"] as? JsonObject).orEmpty().toMutableMap<String, JsonElement>()
            if (!glyphs) layout.remove("text-field")
            if (!sprite) layout.remove("icon-image")
            if ("text-field" !in layout && "icon-image" !in layout) continue
            add(JsonObject(layer + ("layout" to JsonObject(layout))))
        }
    }
}
