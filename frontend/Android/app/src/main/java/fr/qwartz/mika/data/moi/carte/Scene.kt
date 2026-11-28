package fr.qwartz.mika.data.moi.carte

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.max

/*
 * Ce qu'une carte montre par-dessus le fond, sans MapLibre ni Compose, porté de `frontend/Web/src/map/scene.ts` (et de
 * `hereFocus`, `pinRank` de `view.ts`) : des épingles (numérotées, lettrées, roses pour ce que Mika a fait ;
 * secondaires, plus petites et sans numéro, pour les lieux d'à côté comme ceux de « Sur la route »), des tracés (un
 * itinéraire calculé, ou des points reliés à vol d'oiseau), la position de la personne et, quand on la connaît, sa
 * précision (un cercle autour) ; la zone qui les tient tous, cercle compris, et comment une vue la cadre (serrée sur
 * l'écran Carte, un quartier autour sur une miniature, quelques fois son rayon autour d'une position seule). La même
 * scène sert la vraie carte et le plan dessiné de repli.
 */

data class ScenePin(
    /** Ce que vise un toucher (un lieu, un arrêt). */
    val id: String,
    val lat: Double,
    val lon: Double,
    /** Dans l'épingle : un numéro, une lettre (A, B), ou rien. */
    val label: String = "",
    /** Ce que Mika a trouvé, proposé ou ajouté : en rose. */
    val mika: Boolean = false,
    /** L'épingle choisie : plus grande, cerclée. */
    val selected: Boolean = false,
    /** Une épingle secondaire (un lieu d'à côté, pas une étape) : plus petite, sans numéro, sous les autres. */
    val minor: Boolean = false,
    /** Son nom, pour un lecteur d'écran. */
    val title: String = "",
)

data class SceneLine(
    val points: List<LatLon>,
    /** Ce qu'elle a montré : en rose. */
    val mika: Boolean = false,
    /** Des points reliés à vol d'oiseau (pas un trajet calculé) : en pointillés. */
    val straight: Boolean = false,
)

/** La position de la personne (son téléphone) ; [accuracyM] : sa précision, un cercle autour (sans : le point seul). */
data class SceneHere(val lat: Double, val lon: Double, val accuracyM: Double? = null)

data class Scene(
    val pins: List<ScenePin> = emptyList(),
    val lines: List<SceneLine> = emptyList(),
    val here: SceneHere? = null,
) {
    val isEmpty: Boolean get() = pins.isEmpty() && lines.isEmpty() && here == null

    companion object {
        val EMPTY = Scene()
    }
}

/** Un degré de latitude, en mètres (le rayon moyen de la Terre de `MapGeo.kt`). */
const val M_PER_DEG = 111_195.0

/** Le plus petit plan autour d'une position seule, en mètres : sa rue et ses voisines. */
const val HERE_SPAN_M = 300.0

/** Le rayon de la précision d'une position, en mètres : un nombre fini et positif, sinon 0 (aucun cercle). */
fun hereRadius(here: SceneHere?): Double {
    val r = here?.accuracyM ?: return 0.0
    return if (r.isFinite() && r > 0) r else 0.0
}

/** Le même rayon en degrés de latitude (0 : aucun cercle), pour le poser sur un dessin. */
fun hereRadiusDeg(here: SceneHere?): Double = hereRadius(here) / M_PER_DEG

/** Une position valide ; son rayon reste s'il est un nombre fini et positif, sinon le point seul. */
private fun cleanHere(here: SceneHere?): SceneHere? {
    if (here == null || !validPoint(here.lat, here.lon)) return null
    return if (here.accuracyM == null || hereRadius(here) > 0) here else SceneHere(here.lat, here.lon)
}

/** Ses épingles et ses tracés valides seulement (des coordonnées hors de la Terre ne se posent pas). */
fun cleanScene(scene: Scene): Scene = Scene(
    pins = scene.pins.filter { validPoint(it.lat, it.lon) },
    lines = scene.lines
        .map { l -> l.copy(points = l.points.filter { validPoint(it.lat, it.lon) }) }
        .filter { it.points.size >= 2 },
    here = cleanHere(scene.here),
)

/** La position et, si elle a un rayon, les quatre bords de son cercle (nord, sud, est, ouest). */
private fun herePoints(here: SceneHere): List<LatLon> {
    val dLat = hereRadiusDeg(here)
    if (dLat <= 0) return listOf(LatLon(here.lat, here.lon))
    val dLon = dLat / max(0.01, cos(here.lat * PI / 180))
    return listOf(
        LatLon(here.lat + dLat, here.lon),
        LatLon(here.lat - dLat, here.lon),
        LatLon(here.lat, here.lon + dLon),
        LatLon(here.lat, here.lon - dLon),
    )
}

/**
 * La zone qui tient toute la scène, le cercle de la position compris (élargie à [minDeg] degrés au moins autour d'un
 * point seul) ; rien à montrer : `null`.
 */
fun sceneBounds(scene: Scene, minDeg: Double? = null): Bounds? {
    val points = scene.pins.map { LatLon(it.lat, it.lon) } +
        scene.lines.flatMap { it.points } +
        (scene.here?.let { herePoints(it) } ?: emptyList())
    val b = boundsOf(points) ?: return null
    return if (minDeg != null) widened(b, minDeg) else widened(b)
}

/**
 * L'élargissement (en degrés) d'une scène qui n'a que la position et sa précision : quelques fois son rayon, ~300 m au
 * moins. Une scène qui a des épingles ou des tracés, ou une position sans rayon : `null` (l'élargissement de la vue).
 */
fun hereSpan(scene: Scene): Double? {
    val r = hereRadius(scene.here)
    if (r <= 0 || scene.pins.isNotEmpty() || scene.lines.isNotEmpty()) return null
    return max(HERE_SPAN_M, 5 * r) / M_PER_DEG
}

/** Comment une vue cadre ce qu'elle montre : l'élargissement d'une zone trop petite (degrés), ses marges (dp), son zoom le plus serré. */
data class Framing(val minDeg: Double, val paddingDp: Int, val maxZoom: Double)

/**
 * L'écran Carte : des lieux à quelques mètres les uns des autres se départagent (une rue, ~200 m au moins, jusqu'au
 * zoom 17). Une miniature garde un quartier autour (~2 km, jusqu'au zoom 12,5), pour qu'on reconnaisse où c'est.
 */
fun framingFor(interactive: Boolean): Framing =
    if (interactive) Framing(minDeg = 0.002, paddingDp = 56, maxZoom = 17.0) else Framing(minDeg = 0.02, paddingDp = 18, maxZoom = 12.5)

/** Le cadrage d'une scène dans une vue : sa zone, élargie à la mesure de cette vue, ses marges, son plafond ; rien à montrer : `null`. */
data class SceneFrame(val bounds: Bounds, val framing: Framing)

fun sceneFraming(scene: Scene, interactive: Boolean): SceneFrame? {
    val f = framingFor(interactive)
    val bounds = sceneBounds(scene, f.minDeg) ?: return null
    return SceneFrame(bounds, f)
}

/** Une position seule et sa précision, centrée au zoom qui montre son cercle en entier. */
data class HereFocus(val center: LatLon, val zoom: Double)

/**
 * Une scène qui n'a que la position et sa précision (la Position du Téléphone) : son centre et le zoom qui montre son
 * cercle en entier ([zoomFor]), et non le cadrage d'une zone. Toute autre scène : `null`.
 */
fun hereFocus(scene: Scene): HereFocus? {
    val here = scene.here ?: return null
    if (hereSpan(scene) == null) return null
    return HereFocus(LatLon(here.lat, here.lon), zoomFor(hereRadius(here)))
}

/** Ce qui se pose au-dessus de quoi : les secondaires dessous, puis les autres, les siennes, et la choisie en haut. */
fun pinRank(pin: ScenePin): Int = when {
    pin.selected -> 3
    pin.minor -> 0
    pin.mika -> 2
    else -> 1
}

/** Des points reliés dans l'ordre, à vol d'oiseau : le trajet qu'on n'a pas (ou pas encore) calculé. */
fun straightLine(points: List<LatLon>): SceneLine? {
    val ok = points.filter { validPoint(it.lat, it.lon) }
    return if (ok.size >= 2) SceneLine(ok, straight = true) else null
}

/** Une empreinte d'un tracé (ses points peuvent être des milliers) : la même ligne, la même empreinte. */
private fun lineSum(points: List<LatLon>): String {
    var a = 0.0
    var b = 0.0
    points.forEachIndexed { i, p ->
        a = (a + p.lat * (i + 1)) % 1e9
        b = (b + p.lon * (i + 7)) % 1e9
    }
    return "${points.size}:${"%.4f".format(java.util.Locale.ROOT, a)}:${"%.4f".format(java.util.Locale.ROOT, b)}"
}

/** Ce qui change entre deux scènes : rien de changé, rien à reposer. */
fun sceneKey(scene: Scene): String = buildString {
    append(scene.pins.joinToString("|") { "${it.id},${it.lat},${it.lon},${it.label},${it.mika},${it.selected},${it.minor}" })
    append("#")
    append(scene.lines.joinToString("|") { "${it.mika},${it.straight},${lineSum(it.points)}" })
    append("#")
    append(scene.here?.let { "${it.lat},${it.lon},${it.accuracyM}" } ?: "-")
}
