package fr.qwartz.mika.data.moi.carte

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.map
import java.util.Locale

/**
 * La Carte par l'API par personne (`backendv2/docs/protocole-moi.md` § 10), sous le jeton de ce téléphone : ce qui est
 * branché, le fond de carte, les lieux de l'index local (rien ne sort du serveur) et les adresses (Géoplateforme,
 * relayée : seul le texte part). Ce qui n'est pas prêt répond 503, en mots ([fr.qwartz.mika.data.moi.MoiError]) ; trop
 * d'adresses d'affilée, 429 ; trop de trajets (20 par minute et par compte), 429 aussi. Un itinéraire (seuls ses points
 * partent, au serveur d'itinéraires réglé) et ce que Mika a cherché ou montré (un regard) ; les voyages : [TripsApi].
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
    ): MoiApi.Result<List<Place>> = api.get(
        "$PATH/lieux",
        linkedMapOf(
            "q" to q.trim().take(QUERY_MAX),
            "cat" to cat,
            "near" to near?.let { pointText(it) },
            "bbox" to bbox?.let { bboxText(it) },
            "limit" to limit.coerceIn(1, LIMIT_MAX).toString(),
        ),
        Places.serializer(),
    ).map { it.places }

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
