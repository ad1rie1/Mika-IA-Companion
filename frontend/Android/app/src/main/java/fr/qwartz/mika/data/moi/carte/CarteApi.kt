package fr.qwartz.mika.data.moi.carte

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.decode
import fr.qwartz.mika.data.moi.map
import okhttp3.HttpUrl
import java.util.Locale

/**
 * La Carte par l'API par personne (`backendv2/docs/protocole-moi.md` § 10), sous le jeton de ce téléphone : ce qui est
 * branché, le fond de carte, les lieux de l'index local (rien ne sort du serveur) et les adresses (Géoplateforme,
 * relayée : seul le texte part). Ce qui n'est pas prêt répond 503, en mots ([fr.qwartz.mika.data.moi.MoiError]) ; trop
 * d'adresses d'affilée, 429 ; trop de trajets (20 par minute et par compte), 429 aussi. Un itinéraire (seuls ses points
 * partent, au serveur d'itinéraires réglé) et ce que Mika a cherché ou montré (un regard) ; les voyages : [TripsApi].
 * Depuis l'ADR 0259 : la liste filtrée et notée, la fiche d'un lieu et « Actualiser », les événements et leur fiche,
 * l'adresse d'une photo relayée (bornes par compte : 60 fiches ou recherches d'événements par minute, 120 photos, 10
 * « Actualiser » ; 429 au-delà, en mots).
 */
class CarteApi(private val api: MoiApi) {
    /** Ce qui est branché sur le serveur, et les catégories dans l'ordre de l'écran. */
    suspend fun info(): MoiApi.Result<CarteInfo> = api.get(PATH, reader = CarteInfo.serializer())

    /** Le fond de toutes les cartes (ADR 0193, 0229) ; pas prêt : `ready` faux et `reason`, le plan dessiné. */
    suspend fun fond(): MoiApi.Result<MapFond> = api.get("$PATH/fond", reader = MapFond.serializer())

    /**
     * Des lieux de l'index : par le nom ([q]), d'une catégorie ([cat]), près d'un point ([near], les plus proches
     * d'abord), dans une zone ([bbox]) — au moins un de [q], [near], [bbox] (le serveur refuse sinon, 400).
     */
    suspend fun places(
        q: String = "",
        cat: String = "",
        near: LatLon? = null,
        bbox: Bounds? = null,
        limit: Int = PLACES_LIMIT,
    ): MoiApi.Result<List<Place>> = list(PlacesQuery(q = q, cat = cat, near = near, bbox = bbox, limit = limit)).map { it.places }

    /**
     * Une liste de lieux filtrée et rangée ([PlacesQuery], ADR 0244, 0259) et ce que le cache des avis sait de l'endroit
     * (`reviews`, avec `near` ou `bbox`). Une liste ne lit que les caches du serveur : elle ne compte pas dans ses bornes.
     */
    suspend fun list(query: PlacesQuery): MoiApi.Result<PlacesFound> =
        api.get("$PATH/lieux", placesParams(query), PlacesFound.serializer())

    /**
     * La fiche d'un lieu (`l<n>`, son objet d'OpenStreetMap `n123`/`w45`/`r6`, ou `t:<uuid>`) : ce qu'en dit chaque
     * source, et les événements tout près. Un identifiant d'une autre forme ne part pas : 404, comme le serveur.
     */
    suspend fun place(id: String): MoiApi.Result<PlaceFiche> {
        val ref = placeRef(id) ?: return MoiApi.Result.Failed(MoiError(404, NOT_HERE))
        return api.get("$PATH/lieu/$ref", reader = PlaceFiche.serializer())
    }

    /**
     * « Actualiser » : sa fiche relue tout de suite chez Google et à l'office de tourisme. Ce qui n'a pas pu se relire
     * répond 503, en mots — ce qui l'a pu est gardé : relire la fiche ; 429 au-delà de dix par minute.
     */
    suspend fun refresh(id: String): MoiApi.Result<PlaceRefreshed> {
        val ref = placeRef(id) ?: return MoiApi.Result.Failed(MoiError(404, NOT_HERE))
        return api.post("$PATH/lieu/$ref/actualiser").decode(PlaceRefreshed.serializer())
    }

    /** Les événements à venir (DATAtourisme) et ce que la base sait de l'endroit : au moins un de `near`, `bbox`, `q`. */
    suspend fun events(query: EventsQuery): MoiApi.Result<EventsFound> =
        api.get("$PATH/evenements", eventsParams(query), EventsFound.serializer())

    /** La fiche d'un événement (`e:<uuid>`) ; une autre forme ne part pas (404). */
    suspend fun event(id: String): MoiApi.Result<EventFiche> {
        val ref = eventRef(id) ?: return MoiApi.Result.Failed(MoiError(404, NOT_HERE))
        return api.get("$PATH/evenement/$ref", reader = EventFiche.serializer())
    }

    /**
     * L'adresse d'une photo relayée, refaite depuis sa référence (`p:<32 chiffres hexadécimaux>`) sur le serveur de la
     * session : jamais le `path` ni une adresse donnée par une réponse. Une autre forme, ou hors session : `null`.
     */
    fun photoUrl(ref: String?): HttpUrl? = photoPath(ref)?.let { api.url(it) }

    /** Une adresse (3 à 200 caractères ; [limit] : 1 à 10) : seul ce texte part, à la Géoplateforme. */
    suspend fun addresses(q: String, limit: Int = ADDRESS_LIMIT): MoiApi.Result<List<Place>> = api.get(
        "$PATH/adresses",
        linkedMapOf("q" to q.trim().take(QUERY_MAX), "limit" to limit.coerceIn(1, 10).toString()),
        Places.serializer(),
    ).map { it.places }

    /**
     * Un itinéraire de 2 à 20 [points] ([CarteLimits.POINTS]), [mode] (`voiture`, `velo`, `pied`), ce qu'il évite
     * ([avoid], en voiture seulement : `peages`, `autoroutes`, `ferries`). Seuls ses points partent.
     */
    suspend fun route(points: List<LatLon>, mode: String, avoid: List<String> = emptyList()): MoiApi.Result<Itinerary> = api.get(
        "$PATH/itineraire",
        linkedMapOf("points" to pointsText(points), "mode" to mode, "avoid" to avoid.joinToString(",")),
        Itinerary.serializer(),
    )

    /** Ce qu'elle a cherché ou montré pour toi (le `ref` d'une note `look` ou `map`) ; oublié, ou pas pour toi : 404. */
    suspend fun regard(seq: String): MoiApi.Result<Regard> {
        val ref = refOf(seq) ?: return MoiApi.Result.Failed(MoiError(404, NOT_HERE))
        return api.get("$PATH/regards/$ref", reader = Regard.serializer())
    }

    companion object {
        const val PATH = "/carte"
        /** Un texte cherché, au plus (`QUERY_MAX` du serveur). */
        const val QUERY_MAX = 200
        /** Combien de lieux au plus par recherche (`LIMIT_MAX` du serveur) ; par défaut. */
        const val LIMIT_MAX = 50
        const val PLACES_LIMIT = 20
    }
}

/** Un point comme l'API le lit : `latitude,longitude`, à six décimales. */
fun pointText(p: LatLon): String = String.format(Locale.ROOT, "%.6f,%.6f", p.lat, p.lon)

/** Une zone : `ouest,sud,est,nord`, à cinq décimales. */
fun bboxText(b: Bounds): String =
    listOf(b.west, b.south, b.east, b.north).joinToString(",") { String.format(Locale.ROOT, "%.5f", it) }

/** Des points, séparés par `;`. */
fun pointsText(points: List<LatLon>): String = points.joinToString(";") { pointText(it) }

/** Ce qui n'est pas un identifiant du serveur ne part pas : on le dit comme lui (404). */
internal const val NOT_HERE = "Introuvable : ce n'est plus là."

private val REF = Regex("""^\d{1,18}$""")

/**
 * Un identifiant du serveur (le `seq` d'un regard, d'un voyage, d'un arrêt) : des chiffres, sinon `null` — rien ne part
 * vers une adresse qu'on n'a pas lue de lui.
 */
fun refOf(text: String?): String? = text?.trim()?.takeIf { REF.matches(it) }

// ── Les fiches, les événements et les photos (ADR 0259) ─────────────────

/** Les identifiants que l'API lit, de la même forme que les siens (`backendv2/src/mika/ports/maps.py`). */
private val PLACE_REF = Regex("""^(?:l\d{1,15}|[nwr]\d{1,15}|t:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$""")
private val EVENT_REF = Regex("""^e:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$""")
private val PHOTO_REF = Regex("""^p:[0-9a-f]{32}$""")

/** Un lieu qui a une fiche (`l<n>`, `n123`/`w45`/`r6`, `t:<uuid>`), sinon `null` : rien ne part. */
fun placeRef(id: String?): String? = id?.trim()?.takeIf { PLACE_REF.matches(it) }

/** Un événement (`e:<uuid>`), sinon `null`. */
fun eventRef(id: String?): String? = id?.trim()?.takeIf { EVENT_REF.matches(it) }

/** Une photo relayée (`p:<32 chiffres hexadécimaux>`), sinon `null`. */
fun photoRef(ref: String?): String? = ref?.trim()?.takeIf { PHOTO_REF.matches(it) }

/** Le chemin d'une photo sous `/api/moi`, refait depuis sa référence ; une autre forme : `null`, rien à montrer. */
fun photoPath(ref: String?): String? = photoRef(ref)?.let { "${CarteApi.PATH}/photo/$it" }

/** L'ordre d'une liste : les plus proches (par défaut), ou les mieux notés (ceux sans note à la fin). */
const val SORT_DISTANCE = "distance"
const val SORT_RATING = "rating"

/** Une cuisine cherchée, au plus (`CUISINE_MAX` du serveur). */
const val CUISINE_MAX = 40

/**
 * Ce qu'une liste de lieux filtre et range (ADR 0244, 0259) : ouvert à l'instant ([open], d'après ses horaires), tous
 * ces [features] (`terrasse`, `vegan`…), sa [cuisine], une note minimale ([minRating], de 0 à 5 : elle écarte les lieux
 * sans note), l'ordre ([sort]).
 */
data class PlaceFilters(
    val open: Boolean = false,
    val features: List<String> = emptyList(),
    val cuisine: String = "",
    val minRating: Double? = null,
    val sort: String = SORT_DISTANCE,
)

/**
 * Une liste de lieux : [q], [cat], [near] ou [bbox], [limit], les [filters] ; [here] : ce [near] est ta propre position
 * (« Autour de moi », avec les coordonnées que ton téléphone a données) — le serveur précharge alors les notes de ta
 * case. Un point de la carte qu'on regarde n'est pas toi : jamais [here]. [ici] : `near=ici`, ta dernière position que
 * le serveur garde (il précharge aussi) ; sans elle, 409 en mots (`fields.near`) — il l'emporte sur [near].
 */
data class PlacesQuery(
    val q: String = "",
    val cat: String = "",
    val near: LatLon? = null,
    val bbox: Bounds? = null,
    val limit: Int = CarteApi.PLACES_LIMIT,
    val filters: PlaceFilters = PlaceFilters(),
    val here: Boolean = false,
    val ici: Boolean = false,
)

/** `near=ici` : ta dernière position, celle que ton téléphone a donnée au serveur. */
const val NEAR_HERE = "ici"


/** Une note comme l'API la lit : « 4 », « 4.5 » ; rien pour une note qui n'écarte rien (absente, 0, pas un nombre). */
fun ratingParam(r: Double?): String? {
    if (r == null || !r.isFinite() || r <= 0) return null
    val v = r.coerceAtMost(5.0)
    return if (v == Math.floor(v)) v.toLong().toString() else String.format(Locale.ROOT, "%.1f", v)
}

/** Ce qu'une recherche de lieux envoie : rien de vide, rien qui ne dise rien (l'ordre par défaut, une note 0). */
fun placesParams(query: PlacesQuery): Map<String, String?> {
    val f = query.filters
    val near = if (query.ici) null else query.near?.takeIf { validPoint(it.lat, it.lon) }
    return linkedMapOf(
        "q" to query.q.trim().take(CarteApi.QUERY_MAX),
        "cat" to query.cat,
        "near" to if (query.ici) NEAR_HERE else near?.let { pointText(it) },
        "bbox" to query.bbox?.let { bboxText(it) },
        "limit" to query.limit.coerceIn(1, CarteApi.LIMIT_MAX).toString(),
        "open_now" to if (f.open) "1" else null,
        "features" to f.features.map { it.trim() }.filter { it.isNotEmpty() }.distinct().joinToString(","),
        "cuisine" to f.cuisine.trim().replace(Regex("\\s+"), " ").take(CUISINE_MAX),
        "min_rating" to ratingParam(f.minRating),
        "sort" to f.sort.takeIf { it.isNotBlank() && it != SORT_DISTANCE },
        // « ici » est déjà ta position : `here` n'en dit pas plus
        "here" to if (query.here && near != null) "1" else null,
    )
}

/** Combien d'événements une recherche demande (le plus que l'API rende). */
const val EVENTS_LIMIT = 50
/** Le rayon des événements autour d'un point, en mètres : ses bornes (`RADIUS_MIN`, `RADIUS_MAX` du serveur). */
const val RADIUS_MIN = 500
const val RADIUS_MAX = 100_000

/**
 * Une liste d'événements : autour de [near] (à [radius] mètres ; sans : 20 km, le défaut du serveur) ou dans [bbox], du
 * [start] au [end] (`AAAA-MM-JJ`, à l'heure de Paris), d'un des [themes], dont le nom dit [q], gratuits seulement
 * ([free]). [ici] : `near=ici`, ta dernière position que le serveur garde (sans elle, 409 en mots).
 */
data class EventsQuery(
    val near: LatLon? = null,
    val bbox: Bounds? = null,
    val radius: Int? = null,
    val start: String = "",
    val end: String = "",
    val themes: List<String> = emptyList(),
    val q: String = "",
    val free: Boolean = false,
    val limit: Int = EVENTS_LIMIT,
    val ici: Boolean = false,
)

/** Ce qu'une recherche d'événements envoie : le rayon seulement autour d'un point, une date seulement si c'en est une. */
fun eventsParams(query: EventsQuery): Map<String, String?> {
    val near = if (query.ici) null else query.near?.takeIf { validPoint(it.lat, it.lon) }
    return linkedMapOf(
        "near" to if (query.ici) NEAR_HERE else near?.let { pointText(it) },
        "bbox" to query.bbox?.let { bboxText(it) },
        "radius" to if (near != null || query.ici) query.radius?.coerceIn(RADIUS_MIN, RADIUS_MAX)?.toString() else null,
        "start" to query.start.takeIf { isoDay(it) != null },
        "end" to query.end.takeIf { isoDay(it) != null },
        "themes" to query.themes.map { it.trim() }.filter { it.isNotEmpty() }.distinct().joinToString(","),
        "q" to query.q.trim().take(CarteApi.QUERY_MAX),
        "free" to if (query.free) "1" else null,
        "limit" to query.limit.coerceIn(1, EVENTS_LIMIT).toString(),
    )
}
