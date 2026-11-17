package fr.qwartz.mika.data.moi.carte

import java.text.Normalizer
import java.time.ZoneId
import java.util.Locale

/*
 * Les règles d'Itinéraire, sans Compose ni réseau, portées de `frontendv2/src/screens/carte/format.ts`, `view.ts` et
 * `itinerary.ts` sans changer leurs règles : ses points (choisis ou seulement tapés), ce qui fait un itinéraire (un point
 * retapé rend le trajet montré passé), tes choix face à ceux d'un trajet de Mika (son mode et ses cases se montrent sans
 * devenir les tiens), ce qu'on en dit, son GPX fait sur le téléphone et le nom de son fichier.
 */

/** Un point d'un itinéraire : ce qu'on a tapé ([query]) ou le nom du point choisi, et ses coordonnées une fois choisi. */
data class ItiPoint(val query: String = "", val name: String = "", val lat: Double? = null, val lon: Double? = null) {
    val chosen: Boolean get() = lat != null && lon != null
}

/** Un point choisi : son nom et ses coordonnées. */
data class NamedPoint(val name: String, val lat: Double, val lon: Double)

/** Sa position, en point d'un itinéraire (son nom, celui du lieu : c'est lui qu'un voyage gardera). */
fun herePoint(lat: Double, lon: Double, label: String): ItiPoint {
    val l = label.trim()
    return ItiPoint(query = if (l.isNotEmpty()) "Ma position · $l" else "Ma position", name = l.ifEmpty { "Ma position" }, lat = lat, lon = lon)
}

/** Un lieu (d'Explorer, d'une proposition, d'un regard), en point d'un itinéraire. */
fun pointOf(p: Place): ItiPoint = ItiPoint(query = p.name, name = p.name, lat = p.at?.lat, lon = p.at?.lon)

/** Les points qu'on a choisis (avec leurs coordonnées), dans l'ordre. */
fun chosenPoints(points: List<ItiPoint>): List<NamedPoint> =
    points.mapNotNull { p -> if (p.lat != null && p.lon != null) NamedPoint(p.name.ifBlank { p.query }, p.lat, p.lon) else null }

/** Un point tapé qu'on n'a pas encore choisi dans ses propositions : il n'a pas de coordonnées. */
fun typedPoint(points: List<ItiPoint>): Boolean = points.any { it.query.isNotBlank() && !it.chosen }

/** Ce qui fait un itinéraire : ses points choisis dans l'ordre, son mode, ce qu'il évite (en voiture seulement). */
fun itiKey(points: List<ItiPoint>, mode: String, avoid: List<String>): String = buildString {
    append(chosenPoints(points).joinToString(";") { "${it.lat},${it.lon}" })
    append('|').append(mode).append('|')
    append(if (mode == "voiture") avoid.sorted().joinToString(",") else "")
}

/** La lettre d'un point : A au départ, B à l'arrivée, le numéro d'une étape. */
fun pointLetter(i: Int, n: Int): String = when (i) {
    0 -> "A"
    n - 1 -> "B"
    else -> i.toString()
}

/** « Itinéraire de Lille à Annecy » ; moins de deux points : « Itinéraire ». */
fun routeTitle(chosen: List<NamedPoint>): String =
    if (chosen.size >= 2) "Itinéraire de ${chosen.first().name} à ${chosen.last().name}" else "Itinéraire"

/** « Lille → Annecy » : le nom d'un voyage ou d'un GPX fait d'un itinéraire. */
fun routeName(chosen: List<NamedPoint>): String = "${chosen.first().name} → ${chosen.last().name}"

// ── Les choix d'un itinéraire ───────────────────────────────────────────

/** Le mode d'un itinéraire et ce qu'il évite (en voiture seulement). */
data class RouteChoices(val mode: String = "voiture", val avoid: List<String> = emptyList())

/** Un geste de la personne : un mode, ou une case cochée ou décochée. */
sealed interface RouteChoice {
    data class Mode(val mode: String) : RouteChoice
    data class Avoid(val avoid: String, val on: Boolean) : RouteChoice
}

/**
 * Le mode et ce qu'évite le trajet montré : ceux du trajet de Mika qu'on ouvre ([regard], tel qu'elle l'a gardé), sinon
 * les tiens ([own]). Ce qu'un regard ne dit pas (un regard d'avant ne dit pas ce qu'il évitait), ce sont les tiens. Rien
 * n'écrit [own] ici : son trajet se montre sans devenir ton choix.
 */
fun routeChoices(own: RouteChoices, regard: RegardRoute?): RouteChoices {
    val mode = regard?.mode?.takeIf { it in MODES } ?: own.mode
    val said = regard?.avoid
    val avoid = if (said != null) AVOIDS.filter { it in said } else own.avoid
    return RouteChoices(mode, avoid)
}

/**
 * Des choix après un geste (un mode, une case) : seul ce que le geste touche change. Il s'applique au trajet montré
 * comme à tes choix — une case touchée sur le trajet de Mika ne fait pas tiennes les autres cases qu'il avait cochées.
 */
fun withChoice(choices: RouteChoices, choice: RouteChoice): RouteChoices = when (choice) {
    is RouteChoice.Mode -> if (choice.mode in MODES) RouteChoices(choice.mode, choices.avoid) else choices
    is RouteChoice.Avoid -> if (choice.avoid !in AVOIDS) {
        choices
    } else {
        RouteChoices(choices.mode, AVOIDS.filter { if (it == choice.avoid) choice.on else it in choices.avoid })
    }
}

/** Les cases d'un itinéraire, comme la maquette les dit : « Sans péage »… (« Éviter les péages » pour un lecteur d'écran). */
val AVOID_CHIPS: Map<String, String> = linkedMapOf("peages" to "Sans péage", "autoroutes" to "Sans autoroute", "ferries" to "Sans ferry")

/** Pourquoi les cases ne se cochent pas hors voiture ; en voiture : rien. */
fun avoidNote(mode: String): String = when (mode) {
    "velo" -> "À vélo, le trajet évite d'office péages et autoroutes."
    "pied" -> "À pied, rien à éviter."
    else -> ""
}

// ── Ce qu'on en dit ─────────────────────────────────────────────────────

/** Sous la durée et la distance : « en voiture, avec péages · arrivée vers 15:35 si tu pars maintenant ». */
fun routeFacts(route: Itinerary, mode: String, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    val facts = buildList {
        add(modeWords(mode))
        if (route.hasToll) add("avec péages") else if (mode == "voiture") add("sans péage")
        if (route.hasFerry) add("avec un ferry")
    }
    return listOf(facts.joinToString(", "), arrival(now, route.durationS, zone)).filter { it.isNotBlank() }.joinToString(" · ")
}

/** D'où vient un itinéraire : il ne voit que ses points. */
fun routeSource(route: Itinerary): String =
    "Calculé par ${route.provider.ifBlank { "le serveur d'itinéraires" }}, relayé par ce serveur : il ne voit que les points du trajet, jamais qui tu es."

/** « Envoyer à Mika », d'un itinéraire : « Regarde ce trajet : Lille → Annecy (7 h 05, 751 km en voiture). » */
fun askAboutRoute(names: List<String>, distanceM: Double?, durationS: Double?, mode: String): String {
    val facts = if (distanceM != null && durationS != null) {
        " (${listOf(duration(durationS), km(distanceM)).filter { it.isNotBlank() }.joinToString(", ")} ${modeWords(mode)})"
    } else {
        ""
    }
    return "Regarde ce trajet : ${names.joinToString(" → ")}$facts. "
}

/** Le tracé entier d'un itinéraire calculé : ses tronçons bout à bout (le premier point d'un tronçon est le dernier du précédent). */
fun routeTrack(route: Itinerary): List<LatLon> = route.legs.flatMapIndexed { i, l ->
    val pts = safeDecode(l.shape)
    if (i > 0) pts.drop(1) else pts
}

/** Les consignes d'un itinéraire, de tous ses tronçons. */
fun routeSteps(route: Itinerary): List<Step> = route.legs.flatMap { it.steps }

// ── Le GPX d'un itinéraire ──────────────────────────────────────────────

/** L'espace de noms de GPX 1.1 : un nom que le format exige, jamais une adresse que le téléphone joindrait. */
private const val GPX_NS = "http://www.topografix.com/GPX/1/1"

private fun xml(text: String): String = buildString {
    for (c in text) {
        when (c) {
            '&' -> append("&amp;")
            '<' -> append("&lt;")
            '>' -> append("&gt;")
            '"' -> append("&quot;")
            '\'' -> append("&apos;")
            else -> append(c)
        }
    }
}

private fun fixed(v: Double): String = String.format(Locale.ROOT, "%.6f", v)

/**
 * Un itinéraire en GPX 1.1, fait sur le téléphone (un itinéraire n'est pas encore un voyage : le serveur ne garde que le
 * GPX d'un voyage) : ses points nommés en route (`<rte>`), son tracé en trace (`<trk>`), tout texte échappé.
 */
fun routeGpx(name: String, points: List<NamedPoint>, track: List<LatLon>): String {
    val rte = points.joinToString("\n") { "    <rtept lat=\"${fixed(it.lat)}\" lon=\"${fixed(it.lon)}\"><name>${xml(it.name)}</name></rtept>" }
    val trk = track.joinToString("\n") { "      <trkpt lat=\"${fixed(it.lat)}\" lon=\"${fixed(it.lon)}\"/>" }
    val trace = if (track.isEmpty()) "" else "\n  <trk>\n    <name>${xml(name)}</name>\n    <trkseg>\n$trk\n    </trkseg>\n  </trk>"
    return """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Mika" xmlns="$GPX_NS">
  <metadata><name>${xml(name)}</name></metadata>
  <rte>
    <name>${xml(name)}</name>
$rte
  </rte>$trace
</gpx>
"""
}

private val MARKS = Regex("[̀-ͯ]")
private val UNSAFE = Regex("[^A-Za-z0-9_.-]+")
private val EDGES = Regex("^-+|-+$")

/** Le nom d'un fichier : sans ce qu'un système refuse (« Lille → Annecy » : `Lille-Annecy.gpx`). */
fun fileName(title: String, ext: String): String {
    val base = Normalizer.normalize(title, Normalizer.Form.NFD).replace(MARKS, "").replace(UNSAFE, "-").replace(EDGES, "").take(60)
    return "${base.ifEmpty { "itineraire" }}.$ext"
}
