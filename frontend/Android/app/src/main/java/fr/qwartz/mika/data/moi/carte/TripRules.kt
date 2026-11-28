package fr.qwartz.mika.data.moi.carte

import java.time.ZoneId
import kotlin.math.max

/*
 * Les règles d'un voyage, sans Compose ni réseau, portées de `frontend/Web/src/screens/carte/format.ts`, `view.ts` et
 * `map/cards.ts` sans changer leurs règles : l'ordre de ses arrêts et où un geste les met (un geste qui ne change rien,
 * ce qu'en dit un lecteur d'écran), un arrêt retiré, une note changée — montrés avant que le serveur les dise —, ce dont
 * son trajet dépend, le jour et la place d'un lieu croisé le long du trajet (« Sur la route »), ce que la fenêtre d'un
 * voyage envoie, ses épingles et ses tracés, les phrases qu'on prépare pour Mika.
 */

// ── Les arrêts d'un voyage ──────────────────────────────────────────────

/** Un arrêt dans l'ordre du voyage, avec son jour et son numéro (1, 2, 3… d'un bout à l'autre). */
data class OrderedStop(val stop: TripStop, val day: Int, val n: Int)

fun orderedStops(trip: Trip): List<OrderedStop> {
    var n = 0
    return trip.days.flatMap { d -> d.stops.map { OrderedStop(it, d.n, ++n) } }
}

/** Combien d'arrêts a le voyage. */
fun stopCount(trip: Trip): Int = trip.days.sumOf { it.stops.size }

/** L'arrêt [id] du voyage, sinon `null`. */
fun stopOf(trip: Trip, id: String): TripStop? = trip.days.firstNotNullOfOrNull { d -> d.stops.firstOrNull { it.id == id } }

/**
 * Où un arrêt déplacé atterrit : le jour [day], posé avant l'arrêt [before] (ou à la fin du jour si [before] est
 * `null`) — sa place parmi les **autres** arrêts du jour, comme l'API la lit (`plugins/trips::place`) ; −1 : à la fin.
 */
fun dropIndex(trip: Trip, moving: String, day: Int, before: String?): Int {
    val others = trip.days.firstOrNull { it.n == day }?.stops.orEmpty().filter { it.id != moving }
    if (before == null) return -1
    val at = others.indexOfFirst { it.id == before }
    return if (at < 0) -1 else at
}

/** Le voyage tel qu'il sera une fois l'arrêt déplacé (pour le montrer avant que le serveur le dise). */
fun movedTrip(trip: Trip, moving: String, day: Int, index: Int): Trip {
    val stop = stopOf(trip, moving) ?: return trip
    val lastDay = max(day, trip.days.maxOfOrNull { it.n } ?: day)
    val days = (1..lastDay).map { n ->
        val found = trip.days.firstOrNull { it.n == n }
        TripDay(n, found?.date.orEmpty(), found?.stops.orEmpty().filter { it.id != moving })
    }.toMutableList()
    val row = days[day - 1].stops.toMutableList()
    row.add(if (index < 0 || index > row.size) row.size else index, stop)
    days[day - 1] = days[day - 1].copy(stops = row)
    // un voyage va du jour 1 au dernier qui a un arrêt
    while (days.size > 1 && days.last().stops.isEmpty()) days.removeAt(days.lastIndex)
    return trip.copy(days = days)
}

/** Les arrêts de chaque jour, dans l'ordre, sans les jours vides du bout : deux voyages rangés pareil se confondent. */
private fun arrangement(trip: Trip): String {
    val days = trip.days.map { d -> d.stops.joinToString(",") { it.id } }.toMutableList()
    while (days.isNotEmpty() && days.last().isEmpty()) days.removeAt(days.lastIndex)
    return days.joinToString("|")
}

/** Le voyage sans cet arrêt (pour le montrer retiré avant que le serveur le dise). */
fun removedTrip(trip: Trip, stopId: String): Trip {
    val days = trip.days.map { d -> d.copy(stops = d.stops.filter { it.id != stopId }) }.toMutableList()
    while (days.size > 1 && days.last().stops.isEmpty()) days.removeAt(days.lastIndex)
    return trip.copy(days = days)
}

/** Le voyage avec cette note sur cet arrêt (vide : sans note), pour la montrer avant que le serveur le dise. */
fun notedTrip(trip: Trip, stopId: String, note: String): Trip =
    trip.copy(days = trip.days.map { d -> d.copy(stops = d.stops.map { if (it.id == stopId) it.copy(note = note) else it }) })

/** Un geste qui ne change rien (une poignée lâchée où elle était, un tremblement) : rien à envoyer. */
fun noopMove(trip: Trip, moving: String, day: Int, index: Int): Boolean =
    arrangement(movedTrip(trip, moving, day, index)) == arrangement(trip)

/** Ce qu'un lecteur d'écran dit d'un arrêt déplacé : « Reims : jour 1, arrêt 2 sur 3. » */
fun movedWords(trip: Trip, stopId: String): String {
    val day = trip.days.firstOrNull { d -> d.stops.any { it.id == stopId } } ?: return ""
    val at = day.stops.indexOfFirst { it.id == stopId }
    return "${day.stops[at].name.ifBlank { "L'arrêt" }} : jour ${day.n}, arrêt ${at + 1} sur ${day.stops.size}."
}

/** Combien de ses arrêts ont des coordonnées : sous deux, un voyage n'a pas de trajet. */
fun routableStops(trip: Trip): Int = trip.days.sumOf { d -> d.stops.count { validPoint(it.lat, it.lon) } }

/**
 * Ce dont le trajet d'un voyage dépend (`GET …/trajet`) : ses arrêts dans l'ordre, avec leur jour et leurs
 * coordonnées, son mode, ce qu'il évite. La même clé : le trajet calculé vaut encore ; une autre : il se recalcule. Une
 * note, un titre, une date n'y sont pas.
 */
fun tripRouteKey(trip: Trip): String = buildString {
    append(trip.id).append('|').append(trip.mode).append('|').append(trip.avoid.sorted().joinToString(","))
    for (d in trip.days) for (s in d.stops) append('|').append(s.id).append(':').append(d.n).append(':').append(s.lat).append(':').append(s.lon)
}

/**
 * Monter ([delta] −1) ou descendre (+1) un arrêt d'une place, d'un jour à l'autre au besoin : `(jour, index)`, ou
 * `null` (le premier du voyage ne monte pas ; le dernier, seul de son jour, ne descend pas ; pas au-delà du jour 30).
 */
fun stepMove(trip: Trip, moving: String, delta: Int): Pair<Int, Int>? {
    val day = trip.days.firstOrNull { d -> d.stops.any { it.id == moving } } ?: return null
    val at = day.stops.indexOfFirst { it.id == moving }
    val next = at + delta
    if (next >= 0 && next < day.stops.size) return day.n to next
    // au bord du jour : au bout du jour voisin
    val neighbour = day.n + delta
    if (neighbour < 1 || neighbour > CarteLimits.DAYS) return null
    if (delta > 0 && neighbour > trip.days.size && day.stops.size == 1) return null
    return if (delta < 0) neighbour to -1 else neighbour to 0
}

/** Ses arrêts qu'elle a ajoutés. */
fun hersCount(trip: Trip): Int = trip.days.sumOf { d -> d.stops.count { it.hers } }

/** Le titre d'un jour : « Lille → Dijon » ; un seul arrêt : son nom ; aucun : vide. */
fun dayTitle(stops: List<TripStop>): String {
    if (stops.isEmpty()) return ""
    val first = stops.first().name
    val last = stops.last().name
    return if (stops.size == 1 || first == last) first else "$first → $last"
}

/** Le tronçon qui arrive à chaque arrêt (« 2 h 15 · 207 km »), par l'identifiant de l'arrêt. */
fun legsByStop(route: TripRoute?): Map<String, TripLeg> {
    val out = LinkedHashMap<String, TripLeg>()
    for (d in route?.days.orEmpty()) for (leg in d.legs) out[leg.to] = leg
    return out
}

/** « 2 h 15 · 207 km » : un tronçon. */
fun legWords(leg: TripLeg): String = listOf(duration(leg.durationS), km(leg.distanceM)).filter { it.isNotBlank() }.joinToString(" · ")

/** Le tracé d'un voyage, tronçon par tronçon (ce que le serveur d'itinéraires a calculé), en points. */
fun tripLines(route: TripRoute?): List<List<LatLon>> =
    route?.days.orEmpty().flatMap { d -> d.legs.map { safeDecode(it.shape) } }.filter { it.size >= 2 }

/**
 * Où ajouter un lieu croisé le long du trajet ([along] : sa distance depuis le départ) : avant l'arrêt qu'on atteint
 * juste après lui, dans le jour de cet arrêt. Les distances d'un arrêt au suivant viennent des tronçons calculés, sinon
 * du vol d'oiseau (le long d'une ligne droite, comme le serveur sans itinéraires). Rend `(jour, index)` (−1 : à la fin).
 */
fun alongPlace(trip: Trip, route: TripRoute?, along: Double?): Pair<Int, Int> {
    val order = orderedStops(trip).filter { validPoint(it.stop.lat, it.stop.lon) }
    val lastDay = trip.days.lastOrNull()?.n ?: 1
    if (order.size < 2 || along == null) return lastDay to -1
    val legs = legsByStop(route)
    var walked = 0.0
    for (i in 1 until order.size) {
        val prev = order[i - 1].stop
        val cur = order[i].stop
        walked += legs[cur.id]?.distanceM ?: meters(LatLon(prev.lat!!, prev.lon!!), LatLon(cur.lat!!, cur.lon!!))
        if (along <= walked) {
            val day = trip.days.first { it.n == order[i].day }
            return order[i].day to day.stops.indexOfFirst { it.id == cur.id }
        }
    }
    return lastDay to -1
}

// ── Ce que la carte d'un voyage montre ──────────────────────────────────

/** Les arrêts d'un voyage, dans l'ordre, avec leurs numéros (roses : ceux qu'elle a ajoutés). */
fun tripPins(trip: Trip): List<ScenePin> {
    var n = 0
    return trip.days.flatMap { d ->
        d.stops.mapNotNull { s ->
            n += 1
            if (!validPoint(s.lat, s.lon)) null
            else ScenePin(s.id, s.lat!!, s.lon!!, label = n.toString(), mika = s.hers, title = s.name)
        }
    }
}

/**
 * La scène d'un voyage : ses lieux de « Sur la route » en épingles secondaires, puis ses arrêts ; le trajet de ces
 * arrêts-ci (jamais celui d'avant un geste) quand il est calculé, sinon ses arrêts reliés à vol d'oiseau.
 */
fun tripScene(trip: Trip, route: TripRoute?, along: AlongState): Scene {
    val stops = tripPins(trip)
    val routed = tripLines(route)
    val lines = if (routed.isNotEmpty()) routed.map { SceneLine(it) } else listOfNotNull(straightLine(stops.map { LatLon(it.lat, it.lon) }))
    return Scene(pins = alongPins(trip, route, along) + stops, lines = lines)
}

// ── « Sur la route » ────────────────────────────────────────────────────

private val ALONG_PIN = Regex("""^along:(\d+)$""")

/** L'épingle d'un lieu de « Sur la route » : un identifiant à part de ceux des arrêts (`along:<sa place>`). */
fun alongPinId(i: Int): String = "along:$i"

/** La place dans la liste du lieu de « Sur la route » qu'une épingle vise ; un arrêt : `null`. */
fun alongIndexOf(pinId: String): Int? = ALONG_PIN.matchEntire(pinId)?.groupValues?.get(1)?.toIntOrNull()

/** La ligne d'un lieu de « Sur la route » : « jour 1 · Camping · Sévrier · à 3 km de la route » — le jour d'abord. */
fun alongFacts(trip: Trip, route: TripRoute?, p: Place): String {
    val far = p.distanceM?.let { if (it < 150) "sur la route" else "à ${km(it)} de la route" }.orEmpty()
    return listOf("jour ${alongPlace(trip, route, p.alongM).first}", placeWhat(p), far).filter { it.isNotBlank() }.joinToString(" · ")
}

/** La liste de « Sur la route » montre ses lieux : deux arrêts au moins, une catégorie, ni en recherche ni refusée. */
fun alongShown(trip: Trip, along: AlongState): Boolean =
    stopCount(trip) >= 2 && along.error.isEmpty() && !along.loading && along.cat.isNotEmpty() && along.places.isNotEmpty()

/**
 * Les lieux que montre « Sur la route », en épingles secondaires (plus petites, sans numéro) à côté des arrêts ; un
 * toucher sur l'une retrouve sa ligne ([alongIndexOf]). La liste cachée : aucune.
 */
fun alongPins(trip: Trip, route: TripRoute?, along: AlongState): List<ScenePin> {
    if (!alongShown(trip, along)) return emptyList()
    return along.places.mapIndexedNotNull { i, p ->
        p.at?.let { ScenePin(alongPinId(i), it.lat, it.lon, minor = true, title = "${p.name.ifBlank { "—" }} · ${alongFacts(trip, route, p)}") }
    }
}

// ── Les mots d'un voyage ────────────────────────────────────────────────

/** Sous le titre d'un voyage : « sam. 3 – mer. 7 avril · en voiture · sans péage » ([short] : « 3–7 avr. »). */
fun tripHead(trip: Trip, now: Long, short: Boolean = false, zone: ZoneId = ZoneId.systemDefault()): String {
    val dates = if (short) tripSpan(trip.start, trip.days.size, now, zone) else tripDates(trip.start, trip.days.size, now, zone)
    return listOf(dates.ifBlank { "sans date" }, modeWords(trip.mode), avoidWords(trip.avoid, trip.mode))
        .filter { it.isNotBlank() }.joinToString(" · ")
}

/** Un jour : « sam. 3 avril · 502 km · 4 h 50 » (sa date, et ce que son trajet calculé dit). */
fun dayFacts(day: TripDay, route: TripRoute?, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    val r = route?.days?.firstOrNull { it.n == day.n }
    return listOf(
        if (day.date.isNotBlank()) dayLabel(day.date, now, zone) else "",
        if (r != null && r.distanceM > 0) km(r.distanceM) else "",
        if (r != null && r.durationS > 0) duration(r.durationS) else "",
    ).filter { it.isNotBlank() }.joinToString(" · ")
}

/** « Demander à Mika », d'un voyage. */
fun askAboutTrip(title: String): String = "Tu peux m'aider à préparer notre voyage « $title » ? "

// ── Ce que la fenêtre d'un voyage envoie ────────────────────────────────

/** Ce que disent les fenêtres « Nouveau voyage » et « Le voyage » ([avoid] : les cases cochées, cachées ou non). */
data class TripForm(val title: String, val start: String, val mode: String, val avoid: List<String>)

/** Ce qu'un trajet évite pour ce mode : en voiture, les cases cochées (dans l'ordre de l'API) ; à vélo, à pied, rien. */
private fun avoidFor(mode: String, avoid: List<String>): List<String> = if (mode == "voiture") AVOIDS.filter { it in avoid } else emptyList()

/** « Nouveau voyage » : son titre, sa date, son mode, et ce qu'il évite s'il se fait en voiture (sinon rien). */
fun newTripValues(form: TripForm): TripValues = TripValues(
    title = form.title.trim(),
    start = form.start,
    mode = form.mode,
    avoid = if (form.mode == "voiture") avoidFor(form.mode, form.avoid) else null,
)

/**
 * « Le voyage » : ce qui a changé, seulement (vide : rien à envoyer). Ce qu'il évite ne part qu'en voiture — les cases,
 * cachées hors voiture, ne disent rien d'un voyage qui la quitte —, et seulement s'il a changé.
 */
fun tripChanges(trip: Trip, form: TripForm): TripValues {
    val title = form.title.trim()
    val avoid = if (form.mode == "voiture") {
        avoidFor(form.mode, form.avoid).takeIf { it != AVOIDS.filter { a -> a in trip.avoid } }
    } else {
        null
    }
    return TripValues(
        title = title.takeIf { it != trip.title },
        start = form.start.takeIf { it != trip.start },
        mode = form.mode.takeIf { it != trip.mode },
        avoid = avoid,
    )
}

/** Le titre d'un voyage qu'on crée depuis un lieu (« Ajouter au voyage ») : « Autour de Sévrier ». */
fun tripTitleFor(first: Place): String = "Autour de ${first.town.ifBlank { first.name }}".take(CarteLimits.TITLE)

/** Ce qui désigne un lieu, d'une recherche à l'autre (son identifiant d'index change à chaque reconstruction). */
fun placeIntent(p: Place): String = "${p.lat},${p.lon},${p.name}"

/** Un lieu en arrêt d'un voyage : son nom (sinon « Lieu »), ses coordonnées, sa sorte, bornés comme l'API. */
fun stopOfPlace(p: Place, day: Int, index: Int, note: String = ""): NewStop? {
    val at = p.at ?: return null
    return NewStop(
        name = p.name.take(CarteLimits.NAME).ifBlank { "Lieu" },
        lat = at.lat,
        lon = at.lon,
        kind = p.kindFr.take(CarteLimits.KIND),
        day = day,
        index = index,
        note = note.trim().take(CarteLimits.NOTE),
    )
}
