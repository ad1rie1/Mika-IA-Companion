package fr.qwartz.mika.data.moi.carte

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.asin
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.log2
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

/*
 * Les calculs d'une carte, sans aucune dépendance (ADR 0193, 0194), portés de `frontend/Web/src/map/mapgeo.ts` : ce que
 * la carte du serveur couvre, le cercle d'une précision et le zoom qui le montre, la zone qui tient des points, une
 * distance à vol d'oiseau.
 */

/** Un point, en degrés. */
data class LatLon(val lat: Double, val lon: Double)

/** Ouest, sud, est, nord, en degrés. */
data class Bounds(val west: Double, val south: Double, val east: Double, val north: Double)

/** Le rayon moyen de la Terre, en mètres. */
private const val EARTH_M = 6_371_008.8

private fun rad(deg: Double) = deg * PI / 180
private fun deg(rad: Double) = rad * 180 / PI

/** Un point valide : deux nombres finis dans leurs bornes. */
fun validPoint(lat: Double?, lon: Double?): Boolean =
    lat != null && lon != null && lat.isFinite() && lon.isFinite() && abs(lat) <= 90 && abs(lon) <= 180

/** La carte montre-t-elle ce point ? Une archive dit sa zone ; un serveur `{z}/{x}/{y}`, partout. */
fun covers(fond: MapFond?, lat: Double, lon: Double): Boolean {
    if (fond == null || !fond.ready || fond.tiles.isBlank()) return false
    val b = fond.bounds ?: return true
    if (b.size != 4) return true
    return lon >= b[0] && lon <= b[2] && lat >= b[1] && lat <= b[3]
}

/** La carte couvre-t-elle tous ces points (aucun : non) ? */
fun coversAll(fond: MapFond?, points: List<LatLon>): Boolean =
    points.isNotEmpty() && points.all { covers(fond, it.lat, it.lon) }

/** Un cercle de [meters] autour du point, en polygone fermé (lon, lat) : juste à tous les zooms. */
fun circle(lat: Double, lon: Double, meters: Double, steps: Int = 64): List<LatLon> {
    val d = max(1.0, meters) / EARTH_M
    val la = rad(lat)
    val lo = rad(lon)
    return (0..steps).map { i ->
        val t = 2 * PI * i / steps
        val la2 = asin(sin(la) * cos(d) + cos(la) * sin(d) * cos(t))
        val lo2 = lo + atan2(sin(t) * sin(d) * cos(la), cos(d) - sin(la) * sin(la2))
        LatLon(deg(la2), deg(lo2))
    }
}

/** Le zoom qui montre sa précision en entier : le quartier autour pour quelques mètres, plus large au-delà. */
fun zoomFor(meters: Double): Double {
    val m = max(15.0, if (meters.isFinite() && meters > 0) meters else 15.0)
    return max(11.0, min(16.0, 17 - log2(m / 40)))
}

/** La distance à vol d'oiseau entre deux points, en mètres. */
fun meters(a: LatLon, b: LatLon): Double {
    val p1 = rad(a.lat)
    val p2 = rad(b.lat)
    val dp = p2 - p1
    val dl = rad(b.lon - a.lon)
    val x = sin(dp / 2) * sin(dp / 2) + cos(p1) * cos(p2) * sin(dl / 2) * sin(dl / 2)
    return 2 * EARTH_M * asin(min(1.0, sqrt(x)))
}

/** La zone qui tient ces points (aucun : `null`). Un seul point : une zone sans largeur, que l'écran élargit. */
fun boundsOf(points: List<LatLon>): Bounds? {
    val ok = points.filter { it.lat.isFinite() && it.lon.isFinite() }
    if (ok.isEmpty()) return null
    return Bounds(ok.minOf { it.lon }, ok.minOf { it.lat }, ok.maxOf { it.lon }, ok.maxOf { it.lat })
}

/** Une zone élargie d'au moins [minDeg] degrés (un point seul, deux points voisins : un quartier autour). */
fun widened(b: Bounds, minDeg: Double = 0.02): Bounds {
    val dx = max(0.0, minDeg - (b.east - b.west)) / 2
    val dy = max(0.0, minDeg - (b.north - b.south)) / 2
    return Bounds(max(-180.0, b.west - dx), max(-85.0, b.south - dy), min(180.0, b.east + dx), min(85.0, b.north + dy))
}
