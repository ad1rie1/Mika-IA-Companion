package fr.qwartz.mika.data.moi.carte

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * Les formes de la Carte sur l'API par personne (`backendv2/docs/protocole-moi.md` § 10 ; le code :
 * `backendv2/src/mika/app/me/maps.py`), des défauts partout : une clé inconnue s'ignore, une absente prend son défaut.
 * Les itinéraires, les regards de Mika et les voyages (lot 6b) ajouteront les leurs ici.
 */

/** Ce qui est branché sur le serveur (`GET /api/moi/carte`), et les catégories dans l'ordre de l'écran. */
@Serializable
data class CarteInfo(
    val places: PlacesIndex = PlacesIndex(),
    val addresses: Ready = Ready(),
    val routing: Routing = Routing(),
    val categories: List<Category> = emptyList(),
)

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
