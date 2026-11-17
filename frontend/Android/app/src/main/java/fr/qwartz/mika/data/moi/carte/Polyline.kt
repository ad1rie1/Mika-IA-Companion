package fr.qwartz.mika.data.moi.carte

import kotlin.math.roundToLong

/*
 * Le tracé d'un itinéraire, tel que le serveur le rend (`shape`) : l'algorithme des polylines, à six décimales — le
 * même que `backendv2/src/mika/ports/maps.py` (`decode_polyline6`, `encode_polyline6`) et que
 * `frontendv2/src/map/polyline.ts`. Des entiers longs jusqu'au bout (une longitude de 180° y tient, ses écarts aussi),
 * puis divisés par 10⁶.
 */

/** Un tracé illisible ou tronqué : comme le serveur, une erreur. */
class PolylineException(message: String) : IllegalArgumentException(message)

/** Les points (lat, lon) d'un tracé encodé. Illisible ou tronqué : [PolylineException]. */
fun decodePolyline6(text: String): List<LatLon> {
    val points = ArrayList<LatLon>()
    var index = 0
    var lat = 0L
    var lon = 0L
    val n = text.length
    while (index < n) {
        val deltas = LongArray(2)
        for (k in 0..1) {
            var result = 0L
            var shift = 0
            while (true) {
                if (index >= n) throw PolylineException("un tracé tronqué")
                val byte = text[index].code - 63
                index += 1
                if (byte !in 0..63) throw PolylineException("un tracé illisible")
                result = result or ((byte and 0x1f).toLong() shl shift)
                shift += 5
                if (shift > 60) throw PolylineException("un tracé illisible")
                if (byte < 0x20) break
            }
            // le signe est dans le bit le plus bas (zigzag)
            deltas[k] = if (result and 1L == 1L) -((result + 1) / 2) else result / 2
        }
        lat += deltas[0]
        lon += deltas[1]
        points.add(LatLon(lat / 1e6, lon / 1e6))
    }
    return points
}

/** L'inverse de [decodePolyline6] (les tests, et un tracé qu'on reposerait tel quel). */
fun encodePolyline6(points: List<LatLon>): String {
    val out = StringBuilder()
    var lastLat = 0L
    var lastLon = 0L
    for (p in points) {
        val ilat = (p.lat * 1e6).roundToLong()
        val ilon = (p.lon * 1e6).roundToLong()
        for (delta in longArrayOf(ilat - lastLat, ilon - lastLon)) {
            var value = if (delta < 0) -2 * delta - 1 else 2 * delta
            while (value >= 0x20) {
                out.append(((0x20 or (value and 0x1f).toInt()) + 63).toChar())
                value = value shr 5
            }
            out.append((value.toInt() + 63).toChar())
        }
        lastLat = ilat
        lastLon = ilon
    }
    return out.toString()
}

/** Un tracé lisible, ou rien : une forme abîmée ne fait jamais tomber l'écran (on relie alors les points). */
fun safeDecode(text: String?): List<LatLon> {
    if (text.isNullOrEmpty()) return emptyList()
    return try {
        decodePolyline6(text).filter { validPoint(it.lat, it.lon) }
    } catch (_: PolylineException) {
        emptyList()
    }
}
