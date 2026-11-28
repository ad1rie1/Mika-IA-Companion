package fr.qwartz.mika.data.moi.carte

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * Les formes des itinéraires, des regards de Mika et des voyages sur l'API par personne (`protocole-moi.md` § 10 ; le
 * code : `backendv2/src/mika/app/domains/maps/api.py`), portées de `frontend/Web/src/api/carte.ts`, des défauts partout : une clé
 * inconnue s'ignore, une absente (ou `null`) prend son défaut.
 */

/** Les bornes de l'API (`app/domains/maps/api.py`, `contracts/trips.py`) : au-delà, elle refuse (400) — elle ne coupe jamais. */
object CarteLimits {
    const val TITLE = 120
    const val NAME = 200
    const val KIND = 60
    const val NOTE = 500
    const val DAYS = 30
    const val STOPS = 60
    const val POINTS = 20
}

/** Une consigne d'un tronçon, en français. */
@Serializable
data class Step(
    val text: String = "",
    @SerialName("distance_m") val distanceM: Double = 0.0,
    @SerialName("duration_s") val durationS: Double = 0.0,
)

/** Un tronçon d'un itinéraire : son tracé en polyline à six décimales ([decodePolyline6]), ses consignes. */
@Serializable
data class Leg(
    @SerialName("distance_m") val distanceM: Double = 0.0,
    @SerialName("duration_s") val durationS: Double = 0.0,
    val shape: String = "",
    val steps: List<Step> = emptyList(),
)

/** Un itinéraire calculé (`GET /api/moi/carte/itineraire`) ; [provider] : qui l'a calculé, en mots. */
@Serializable
data class Itinerary(
    @SerialName("distance_m") val distanceM: Double = 0.0,
    @SerialName("duration_s") val durationS: Double = 0.0,
    val legs: List<Leg> = emptyList(),
    @SerialName("has_toll") val hasToll: Boolean = false,
    @SerialName("has_highway") val hasHighway: Boolean = false,
    @SerialName("has_ferry") val hasFerry: Boolean = false,
    val provider: String = "",
)

/**
 * Le trajet résumé d'un regard ; une carte qui relie ses lieux sans tracé calculé : son [mode] seul. [avoid] : ce que
 * son trajet évitait, quand le regard le dit (un regard d'avant ne le dit pas : `null`).
 */
@Serializable
data class RegardRoute(
    val mode: String? = null,
    val avoid: List<String>? = null,
    @SerialName("distance_m") val distanceM: Double? = null,
    @SerialName("duration_s") val durationS: Double? = null,
    val shape: String? = null,
)

/**
 * Ce qu'elle a cherché (`look`) ou montré (`map`) pour toi (`GET /api/moi/carte/regards/<seq>`), la note d'un de ses
 * messages : [what] `lieux` ou `trajet` (un regard), vide pour une carte ; [trip] : le voyage qu'elle montrait, s'il
 * est encore là. Ses lieux sont ce qu'elle en a gardé (un point nommé n'a ni sorte ni distance). Des événements qu'elle
 * a trouvés (ADR 0259) : [what] `evenements`, [events], et ses lieux vides (l'onglet Événements l'ouvre).
 */
@Serializable
data class Regard(
    val kind: String = "",
    val title: String = "",
    val what: String = "",
    val places: List<Place> = emptyList(),
    val route: RegardRoute? = null,
    val trip: String = "",
    val at: Long = 0,
    val events: List<EventItem> = emptyList(),
) {
    /** Elle a calculé un trajet (Itinéraire l'ouvre). */
    val isRoute: Boolean get() = kind == KIND_LOOK && what == WHAT_ROUTE

    /** Elle a cherché des événements (l'onglet Événements l'ouvre). */
    val isEvents: Boolean get() = what == WHAT_EVENTS

    companion object {
        const val KIND_LOOK = "look"
        const val KIND_MAP = "map"
        const val WHAT_ROUTE = "trajet"
        const val WHAT_EVENTS = "evenements"
    }
}

/** Un voyage de la liste (`GET /api/moi/voyages`) : [days], [stops] : combien ; [mika] : elle l'a préparé avec toi. */
@Serializable
data class TripSummary(
    val id: String = "",
    val title: String = "",
    /** `AAAA-MM-JJ`, ou vide. */
    val start: String = "",
    val mode: String = "voiture",
    val avoid: List<String> = emptyList(),
    val days: Int = 0,
    val stops: Int = 0,
    val updated: Long = 0,
    val mika: Boolean = false,
)

@Serializable
internal data class TripList(val trips: List<TripSummary> = emptyList())

/** Un arrêt d'un voyage ; [by] : `mika` (elle l'a ajouté : rose) ou `toi`. Ses coordonnées peuvent manquer : `null`. */
@Serializable
data class TripStop(
    val id: String = "",
    val name: String = "",
    val kind: String = "",
    val lat: Double? = null,
    val lon: Double? = null,
    val note: String = "",
    val by: String = "",
) {
    val hers: Boolean get() = by == BY_HER

    companion object {
        const val BY_HER = "mika"
    }
}

/** Un jour d'un voyage ; [date] : la sienne, si le voyage en a une. */
@Serializable
data class TripDay(val n: Int = 1, val date: String = "", val stops: List<TripStop> = emptyList())

/** Un voyage (`GET /api/moi/voyages/<id>`), du jour 1 au dernier qui a un arrêt (un jour vide entre deux compris). */
@Serializable
data class Trip(
    val id: String = "",
    val title: String = "",
    val start: String = "",
    val mode: String = "voiture",
    val avoid: List<String> = emptyList(),
    val updated: Long = 0,
    val mika: Boolean = false,
    val days: List<TripDay> = emptyList(),
)

/** Un tronçon du trajet d'un voyage : les arrêts qu'il relie ([from], [to]). */
@Serializable
data class TripLeg(
    val from: String = "",
    val to: String = "",
    @SerialName("distance_m") val distanceM: Double = 0.0,
    @SerialName("duration_s") val durationS: Double = 0.0,
    val shape: String = "",
    val steps: List<Step> = emptyList(),
)

@Serializable
data class TripRouteDay(
    val n: Int = 1,
    @SerialName("distance_m") val distanceM: Double = 0.0,
    @SerialName("duration_s") val durationS: Double = 0.0,
    val legs: List<TripLeg> = emptyList(),
)

/** Le trajet d'un voyage (`…/trajet`) : ses tronçons d'un arrêt au suivant, rangés au jour de leur arrivée. */
@Serializable
data class TripRoute(
    val days: List<TripRouteDay> = emptyList(),
    @SerialName("distance_m") val distanceM: Double = 0.0,
    @SerialName("duration_s") val durationS: Double = 0.0,
    @SerialName("has_toll") val hasToll: Boolean = false,
    @SerialName("has_highway") val hasHighway: Boolean = false,
    @SerialName("has_ferry") val hasFerry: Boolean = false,
    val provider: String = "",
)

/** Les lieux le long d'un trajet (`…/sur-la-route`) ; [route] faux : sans itinéraires, le long des arrêts reliés à vol d'oiseau. */
@Serializable
data class Along(val places: List<Place> = emptyList(), val route: Boolean = true)

/**
 * Le sort d'une écriture (`{"ok", "message"}`), et ce qu'elle a créé ([id]), si le serveur l'a déjà fait pour cette clé
 * ([deduped]), l'ordre qu'elle a appliqué ([order], « Optimiser l'ordre »).
 */
@Serializable
data class WriteDone(
    val ok: Boolean = true,
    val message: String = "",
    val id: String = "",
    val deduped: Boolean = false,
    val order: List<String> = emptyList(),
)

/** Ce qu'on règle d'un voyage : seulement ce qui n'est pas `null` part (`start` vide : plus de date). */
data class TripValues(
    val title: String? = null,
    val start: String? = null,
    val mode: String? = null,
    val avoid: List<String>? = null,
) {
    val isEmpty: Boolean get() = title == null && start == null && mode == null && avoid == null
}

/** Un arrêt à ajouter : au jour [day] (1 à 30), à la place [index] de ce jour (0 : la première ; −1 : à la fin). */
data class NewStop(
    val name: String,
    val lat: Double,
    val lon: Double,
    val kind: String = "",
    val day: Int = 1,
    val index: Int = -1,
    val note: String = "",
)
