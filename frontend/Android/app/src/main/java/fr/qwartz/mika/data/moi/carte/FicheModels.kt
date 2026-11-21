package fr.qwartz.mika.data.moi.carte

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * Les fiches des lieux, les événements et les photos sur l'API par personne (ADR 0259 ; `backendv2/docs/protocole-moi.md`
 * § 10, « Les fiches, les événements et les photos » ; le contrat des clients : `output/carte-avis/SUIVI.md`). Trois
 * sources, chacune avec ce qu'il faut citer : OpenStreetMap (l'index de ce serveur), l'office de tourisme (DATAtourisme,
 * Licence Ouverte) et Google Maps (le cache des avis de ce serveur). Des défauts partout, comme les autres formes : une
 * partie dont la source ne sait rien du lieu est `null` ; une clé inconnue s'ignore. Les instants sont en ms, une date du
 * jour en `AAAA-MM-JJ`, une date d'événement en ISO 8601.
 */

/**
 * Ce qu'un cache sait d'un endroit : les notes Google d'une liste (`reviews`), les événements (`coverage`) — prêt, ses
 * cases lues, sa lecture la plus ancienne (ms, 0 : aucune), et ce qu'il faut en dire ([note], à montrer tel quel).
 */
@Serializable
data class Coverage(
    val ready: Boolean = false,
    val cells: Int = 0,
    val loaded: Int = 0,
    val oldest: Long = 0,
    val note: String = "",
)

/** Où le serveur a dit que tu étais (`near=ici`) : ta dernière position, celle que ton téléphone a donnée. */
@Serializable
data class HereFix(val lat: Double? = null, val lon: Double? = null, val label: String = "", val at: Long = 0)

/** Une liste de lieux, et ce que le cache des avis sait de l'endroit (avec `near` ou `bbox`). */
@Serializable
data class PlacesFound(
    val places: List<Place> = emptyList(),
    val reviews: Coverage? = null,
    val here: HereFix? = null,
)

/**
 * Une photo relayée par ce serveur (jamais une adresse du dehors) : [ref] (`p:<hash>`) — l'app refait son adresse
 * depuis elle, sans jamais suivre [path] —, [source] (`google`, `datatourisme`), son auteur et son lien ([credit],
 * [creditUrl]) à montrer avec elle, sa licence (une photo de l'office de tourisme), sa légende.
 */
@Serializable
data class Photo(
    val ref: String = "",
    val path: String = "",
    val source: String = "",
    val credit: String = "",
    @SerialName("credit_url") val creditUrl: String = "",
    val licence: String = "",
    val caption: String = "",
    val width: Int? = null,
    val height: Int? = null,
)

/** Un fait d'une source : « Terrasse » « oui ». */
@Serializable
data class Fact(val label: String = "", val value: String = "")

/** Ce qu'OpenStreetMap dit d'un lieu (l'index de ce serveur) : [url] sa page (« Corriger »), [extract] la date de l'extrait. */
@Serializable
data class OsmPart(
    val id: String = "",
    val url: String = "",
    val address: String = "",
    val phone: String = "",
    val website: String = "",
    val email: String = "",
    val hours: String = "",
    @SerialName("hours_text") val hoursText: String = "",
    val facts: List<Fact> = emptyList(),
    val wikidata: String = "",
    val wikipedia: String = "",
    val extract: String = "",
    val attribution: String = "",
    @SerialName("licence_url") val licenceUrl: String = "",
)

/** Ce qu'en dit l'office de tourisme (DATAtourisme) : [author] et [updated] (`AAAA-MM-JJ`) dans [attribution]. */
@Serializable
data class TourismPart(
    val id: String = "",
    val description: String = "",
    val labels: List<String> = emptyList(),
    val prices: String = "",
    val contacts: List<Fact> = emptyList(),
    val author: String = "",
    val updated: String = "",
    val url: String = "",
    val photos: List<Photo> = emptyList(),
    val attribution: String = "",
    val licence: String = "",
    @SerialName("licence_url") val licenceUrl: String = "",
)

/** Un avis Google : son auteur et son lien, sa date en mots ([relative]), à montrer avec lui. */
@Serializable
data class Review(
    val rating: Double? = null,
    val text: String = "",
    val author: String = "",
    @SerialName("author_url") val authorUrl: String = "",
    val at: Long = 0,
    val relative: String = "",
    val language: String = "",
)

/**
 * Ce que Google Maps dit d'un lieu (le cache de ce serveur). [found] faux : Google n'a rien de ce lieu, ou on n'a pas pu
 * chercher — [note] dit lequel. [facts] : ce que Google ajoute à la fiche d'OpenStreetMap ; [cached] : quand ce serveur
 * l'a lue (ms).
 */
@Serializable
data class ReviewsPart(
    val source: String = "",
    @SerialName("source_label") val sourceLabel: String = "",
    val found: Boolean = false,
    val id: String = "",
    val rating: Double? = null,
    val count: Long? = null,
    val price: String = "",
    @SerialName("price_range") val priceRange: String = "",
    val summary: String = "",
    val facts: List<Fact> = emptyList(),
    val reviews: List<Review> = emptyList(),
    val photos: List<Photo> = emptyList(),
    val url: String = "",
    val cached: Long = 0,
    val note: String = "",
)

/**
 * Un événement (une liste, une fiche de lieu, un regard) : le serveur donne tous ses champs, toujours. [start], [end] :
 * sa prochaine date dans la période, en ISO 8601 ; [free] : `null` quand on ne sait pas ; [photo] : vide sans photo.
 * Il voyage aussi dans la pile des écrans (sa fiche, `Route.Event.hint`).
 */
@Serializable
data class EventItem(
    val id: String = "",
    val name: String = "",
    val start: String = "",
    val end: String = "",
    /** « ven. 20 nov. · 19:00–20:30 ». */
    @SerialName("when_text") val whenText: String = "",
    /** Où, en mots : le lieu nommé ou l'adresse, et la commune. */
    val place: String = "",
    val lat: Double? = null,
    val lon: Double? = null,
    @SerialName("distance_m") val distanceM: Double? = null,
    val themes: List<String> = emptyList(),
    val free: Boolean? = null,
    val price: String = "",
    val photo: String = "",
    // Ce qu'il faut citer de sa photo (R2, ADR 0269) : vides sans photo, absents d'un regard
    @SerialName("photo_source") val photoSource: String = "",
    @SerialName("photo_credit") val photoCredit: String = "",
    @SerialName("photo_credit_url") val photoCreditUrl: String = "",
    @SerialName("photo_licence") val photoLicence: String = "",
) {
    val at: LatLon? get() = if (validPoint(lat, lon)) LatLon(lat!!, lon!!) else null
}

/** La fiche d'un lieu : sa ligne, puis ce qu'en dit chaque source (`null` : elle n'en sait rien), et les événements tout près. */
@Serializable
data class PlaceFiche(
    val place: Place = Place(),
    val osm: OsmPart? = null,
    val tourism: TourismPart? = null,
    /** `null` : rien à en dire (pas de clé et rien en cache, ou une sorte dont on ne lit pas les avis). */
    val reviews: ReviewsPart? = null,
    val events: List<EventItem> = emptyList(),
)

/** « Actualiser » : le message du serveur, et la fiche relue. */
@Serializable
data class PlaceRefreshed(
    val ok: Boolean = false,
    val message: String = "",
    val place: Place = Place(),
    val osm: OsmPart? = null,
    val tourism: TourismPart? = null,
    val reviews: ReviewsPart? = null,
    val events: List<EventItem> = emptyList(),
) {
    val fiche: PlaceFiche get() = PlaceFiche(place, osm, tourism, reviews, events)
}

/** Une date d'un événement : « du 18 nov. au 4 janv. · du mer. au lun. · 10:00–18:00 ». */
@Serializable
data class EventDate(
    val start: String = "",
    val end: String = "",
    val text: String = "",
    val days: List<String> = emptyList(),
)

/**
 * La fiche d'un événement (DATAtourisme, Licence Ouverte) : ses dates à venir (la prochaine d'abord, [moreDates] en
 * plus), le lieu nommé où il se tient s'il est rapproché ([venue] ; [venuePlace] ouvre sa fiche), qui l'a écrite et
 * quand, combien de fiches de l'office il réunit ([merged]).
 */
@Serializable
data class EventFiche(
    val event: EventItem = EventItem(),
    val description: String = "",
    val dates: List<EventDate> = emptyList(),
    @SerialName("more_dates") val moreDates: Int = 0,
    val prices: String = "",
    val contacts: List<Fact> = emptyList(),
    val address: String = "",
    val town: String = "",
    val venue: String = "",
    @SerialName("venue_place") val venuePlace: String = "",
    val author: String = "",
    val updated: String = "",
    val url: String = "",
    val photos: List<Photo> = emptyList(),
    val merged: Int = 0,
    val attribution: String = "",
    val licence: String = "",
    @SerialName("licence_url") val licenceUrl: String = "",
)

/** Une liste d'événements, et ce que la base sait de l'endroit, au même rayon. */
@Serializable
data class EventsFound(
    val events: List<EventItem> = emptyList(),
    val coverage: Coverage? = null,
    val here: HereFix? = null,
)
