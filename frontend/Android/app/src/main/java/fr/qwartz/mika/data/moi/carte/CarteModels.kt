package fr.qwartz.mika.data.moi.carte

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * Les formes de la Carte sur l'API par personne (`backendv2/docs/protocole-moi.md` § 10 ; le code :
 * `backendv2/src/mika/app/domains/maps/api.py`), des défauts partout : une clé inconnue s'ignore, une absente prend son défaut.
 * Les itinéraires, les regards de Mika et les voyages : `TripModels.kt` ; les fiches, les événements et les photos
 * (ADR 0259) : `FicheModels.kt`.
 */

/**
 * Ce qui est branché sur le serveur (`GET /api/moi/carte`), et les catégories dans l'ordre de l'écran ; depuis l'ADR
 * 0259, ce qu'une liste sait filtrer ([features]) et ranger ([sorts]), les thèmes des événements ([themes]) et la base
 * des données touristiques ([tourism]).
 */
@Serializable
data class CarteInfo(
    val places: PlacesIndex = PlacesIndex(),
    val addresses: Ready = Ready(),
    val routing: Routing = Routing(),
    val categories: List<Category> = emptyList(),
    /** `terrasse`, `vegetarien`, `vegan`, `accessible`… et leur nom, dans l'ordre des puces. */
    val features: List<Category> = emptyList(),
    /** `distance` (« Les plus proches »), `rating` (« Les mieux notés »). */
    val sorts: List<Category> = emptyList(),
    /** `concerts`, `spectacles`, `expositions`… et leur nom, dans l'ordre des puces. */
    val themes: List<Category> = emptyList(),
    val tourism: TourismBase = TourismBase(),
)

/** La base des données touristiques (DATAtourisme) : prête ou non, combien de lieux et d'événements, lue quand (ms). */
@Serializable
data class TourismBase(val ready: Boolean = false, val places: Long = 0, val events: Long = 0, val synced: Long = 0)

/** L'index des lieux : prêt ou non, combien de lieux, quand il a été construit (ms). */
@Serializable
data class PlacesIndex(val ready: Boolean = false, val count: Long = 0, val built: Long = 0)

@Serializable
data class Ready(val ready: Boolean = false)

/** Les itinéraires : prêts ou non, qui les calcule (en mots), les modes et ce qu'un trajet peut éviter. */
@Serializable
data class Routing(
    val ready: Boolean = false,
    val provider: String = "",
    val modes: List<String> = emptyList(),
    val avoid: List<String> = emptyList(),
)

/** Une catégorie de l'index (`manger`, `dormir`…) et son nom à l'écran. */
@Serializable
data class Category(val id: String = "", val label: String = "")

/**
 * Un lieu : de l'index (`l<n>`, qui change à chaque reconstruction), une adresse de cette réponse (`a:<n>`), ou un point
 * nommé (`""`). Ses coordonnées manquent parfois à un point qu'un regard a gardé : `null`, jamais 0. Il voyage aussi
 * dans la pile des écrans (« Itinéraire jusqu'ici », `Route.Carte.to`).
 */
@Serializable
data class Place(
    val id: String = "",
    val name: String = "",
    /** La sorte OpenStreetMap (`camp_site`), `address`, ou vide. */
    val kind: String = "",
    /** « Camping ». */
    @SerialName("kind_fr") val kindFr: String = "",
    /** `manger`, `dormir`… ; `adresse`. */
    val category: String = "",
    val lat: Double? = null,
    val lon: Double? = null,
    val town: String = "",
    /** Depuis `near`, ou jusqu'au trajet ; sinon `null`. */
    @SerialName("distance_m") val distanceM: Double? = null,
    /** Le long d'un trajet : où on le croise, depuis le départ. */
    @SerialName("along_m") val alongM: Double? = null,
    // Seulement quand le serveur les sait (ADR 0244, 0256, 0259) ; sinon leur défaut :
    /** Son objet d'OpenStreetMap (`n123`, `w45`, `r6`), stable d'une reconstruction de l'index à l'autre. */
    val osm: String = "",
    /** `open`, `closed`, `unknown` (des horaires qu'on ne comprend pas) ; vide : on n'en sait rien. */
    @SerialName("open_state") val openState: String = "",
    /** « Ouvert · ferme à 22:30 », à l'instant de la réponse. */
    @SerialName("open_text") val openText: String = "",
    /** « Italienne, pizza ». */
    val cuisine: String = "",
    /** Sa note Google, sur 5. */
    val rating: Double? = null,
    /** Le nombre de ses avis Google. */
    val reviews: Long? = null,
    /** « €€ ». */
    val price: String = "",
    /** Sa première photo (`p:<hash>`), servie par ce serveur seul. */
    val photo: String = "",
    /** Ce qu'il offre parmi les `features` (`terrasse`, `vegetarien`…). */
    val tags: List<String> = emptyList(),
    // Avec sa photo, ce qu'il faut en citer sur la ligne (R2, ADR 0269) ; un lieu d'un regard n'en garde pas :
    /** `google`, `datatourisme`. */
    @SerialName("photo_source") val photoSource: String = "",
    /** Son auteur, lié à [photoCreditUrl]. */
    @SerialName("photo_credit") val photoCredit: String = "",
    @SerialName("photo_credit_url") val photoCreditUrl: String = "",
    /** Sa licence (une photo de l'office de tourisme). */
    @SerialName("photo_licence") val photoLicence: String = "",
) {
    /** Ses coordonnées, si elles sont valides. */
    val at: LatLon? get() = if (validPoint(lat, lon)) LatLon(lat!!, lon!!) else null
}

@Serializable
internal data class Places(val places: List<Place> = emptyList())

/**
 * Le fond de carte (`GET /api/moi/carte/fond`, ADR 0193, 0229), celui de toutes les cartes, servi par ce serveur seul.
 * Pas prêt : [reason] dit pourquoi, et l'app garde son plan dessiné. Les chemins ([tiles], [glyphs], [sprite]) se
 * posent tels quels sur l'adresse du serveur : `{z}`, `{fontstack}` y restent pour MapLibre.
 */
@Serializable
data class MapFond(
    val ready: Boolean = false,
    val reason: String = "",
    /** `vecteur` (au schéma Protomaps) ou `image`. */
    val kind: String = KIND_VECTOR,
    val minzoom: Int = 0,
    val maxzoom: Int = 15,
    /** Ouest, sud, est, nord ; `null` : partout. */
    val bounds: List<Double>? = null,
    val attribution: String = "",
    /** `…/tiles/{z}/{x}/{y}?v=<version>`. */
    val tiles: String = "",
    /** `…/fonts/{fontstack}/{range}.pbf?v=<version>` ; `null` : pas de polices (une carte sans noms). */
    val glyphs: String? = null,
    /** `…/sprites/~<version>/v4` (la planche suit : `/light`, `/dark`) ; `null` : pas d'icônes. */
    val sprite: String? = null,
) {
    /** Sa zone, si elle est lisible (quatre nombres, ouest < est, sud < nord). */
    val zone: Bounds?
        get() {
            val b = bounds ?: return null
            if (b.size != 4 || b.any { !it.isFinite() } || b[0] >= b[2] || b[1] >= b[3]) return null
            return Bounds(b[0], b[1], b[2], b[3])
        }

    companion object {
        const val KIND_VECTOR = "vecteur"
        const val KIND_IMAGE = "image"
    }
}
