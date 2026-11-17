package fr.qwartz.mika.data.moi.carte

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.async

/*
 * Les règles de la Carte, sans Compose ni MapLibre, portées du web sans les réinventer : quand une adresse se demande et
 * les adresses gardées par texte (`screens/carte/requests.ts`), jusqu'où une recherche est allée, son titre, la phrase
 * préparée pour Mika (`format.ts`, `view.ts`), ce qu'Explorer montre sur la carte ; et la vraie carte ou le plan
 * (`map/live.ts`, `map/base.ts` : quand elle se montre, pourquoi un plan, des tuiles en échec de suite).
 */

// ── Les rythmes ─────────────────────────────────────────────────────────

/** Le fond de carte se relit toutes les cinq minutes tant qu'une carte est à l'écran (`MAP_INFO_TTL` du web). */
const val FOND_TTL_MS = 5 * 60_000L
/** Ta dernière position : relue au plus toutes les quinze secondes (`store.position` du web). */
const val POSITION_TTL_MS = 15_000L
/** Combien de lieux une recherche montre. */
const val PLACES_SHOWN = 30
/** La frappe s'arrête tant avant qu'une recherche parte. */
const val TYPE_MS = 350L
/** La carte bougée cherche de nouveau « dans cette zone » tant après le dernier geste. */
const val MOVE_MS = 500L

// ── Les adresses ────────────────────────────────────────────────────────

/** Combien d'adresses on demande pour un texte. */
const val ADDRESS_LIMIT = 5
/** Combien de temps la saisie doit s'arrêter avant qu'une adresse se demande. */
const val ADDRESS_WAIT_MS = 700L

private val DIGIT = Regex("""\d""")

/** Un texte qui vaut d'être cherché en adresse : trois caractères au moins, et un chiffre ou cinq caractères. */
fun wantsAddress(q: String): Boolean {
    val text = q.trim()
    return text.length >= 3 && (DIGIT.containsMatchIn(text) || text.length >= 5)
}

/**
 * Une adresse se demande-t-elle pour ce texte nouveau ? S'il en a l'air ([wantsAddress]) : un numéro toujours (sans
 * adresses branchées, il reçoit le message du serveur, 503) ; sinon seulement si les adresses sont prêtes et que
 * l'index n'a rien trouvé ([hasPlaces]).
 */
fun addressWanted(q: String, hasPlaces: Boolean, addressesReady: Boolean): Boolean {
    if (!wantsAddress(q)) return false
    return DIGIT.containsMatchIn(q) || (addressesReady && !hasPlaces)
}

private fun addressKey(q: String): String = q.trim().replace(Regex("\\s+"), " ").lowercase()

/**
 * Les adresses trouvées, par texte (les espaces et la casse n'y comptent pas) : un texte déjà cherché ne se redemande
 * pas, deux demandes du même texte n'en font qu'une ; les plus anciens s'en vont au-delà de [keep]. Un refus (429, 503)
 * ne se garde pas : l'appelant le dit, et le texte se redemandera.
 */
class AddressBook(
    private val scope: CoroutineScope,
    private val fetcher: suspend (String, Int) -> MoiApi.Result<List<Place>>,
    private val keep: Int = 100,
) {
    private val found = LinkedHashMap<String, List<Place>>()
    private val pending = HashMap<String, Deferred<MoiApi.Result<List<Place>>>>()

    /** Ce qu'on a déjà trouvé pour ce texte, sinon `null` (rien ne part). */
    fun peek(q: String): List<Place>? = synchronized(this) { found[addressKey(q)] }

    suspend fun lookup(q: String): MoiApi.Result<List<Place>> {
        val key = addressKey(q)
        val running = synchronized(this) {
            found[key]?.let { return MoiApi.Result.Ok(it) }
            pending.getOrPut(key) { scope.async { fetcher(q.trim(), ADDRESS_LIMIT) } }
        }
        val got = running.await()
        synchronized(this) {
            if (pending[key] === running) pending.remove(key)
            if (got is MoiApi.Result.Ok) {
                found[key] = got.value
                while (found.size > keep) found.remove(found.keys.first())
            }
        }
        return got
    }
}

// ── Jusqu'où une recherche est allée ────────────────────────────────────

/**
 * Le rayon (en mètres) jusqu'où une recherche autour de toi se dit « autour de ta position » : le deuxième cercle où
 * l'index cherche un texte (`TEXT_RADII_KM`, `backendv2/src/mika/adapters/maps/places.py`). Au-delà, il s'est élargi.
 */
const val NEARBY_M = 20_000.0

/**
 * Ce que la légende dit de la portée d'une recherche, depuis ses lieux reçus. Autour de toi, l'index élargit ses cercles
 * jusqu'à trouver : tant que le plus loin est à [NEARBY_M] au plus, « autour de ta position » ; sinon, les plus proches
 * qu'il connaisse, jusqu'où ils vont (le classement mêle pertinence et distance : pas de promesse d'un ordre). Une zone
 * ne s'élargit pas. [near] : la recherche est partie de ta position (inconnue, elle a cherché dans la zone de la carte).
 */
fun searchReach(near: Boolean, places: List<Place>): String {
    if (!near) return "dans cette zone"
    val far = places.mapNotNull { p -> p.distanceM?.takeIf { it.isFinite() } }.maxOrNull()?.coerceAtLeast(0.0) ?: 0.0
    return if (far <= NEARBY_M) "autour de ta position" else "les plus proches que l'index connaisse · jusqu'à ${km(far)}"
}

/** Le titre de ce qu'on cherche : « Dormir · camping », « Camping », « Dormir » ; rien : « Lieux ». */
fun searchTitle(info: CarteInfo?, q: String, cat: String): String {
    val label = info?.categories?.firstOrNull { it.id == cat }?.label.orEmpty()
    return listOf(label, q.trim()).filter { it.isNotBlank() }.joinToString(" · ").ifBlank { "Lieux" }
}

/** « 12 lieux · autour de ta position » : la ligne de la légende d'une recherche. */
fun searchLegend(near: Boolean, places: List<Place>): String =
    "${plural(places.size.toLong(), "lieu", "lieux")} · ${searchReach(near, places)}"

// ── Explorer ────────────────────────────────────────────────────────────

/** Où chercher : autour de ta dernière position, ou dans la zone de la carte. */
enum class Where { HERE, ZONE }

/** L'identifiant d'un lieu de la liste : le sien, sinon sa place (un point nommé d'un regard n'en a pas). */
fun placeId(p: Place, i: Int): String = p.id.ifBlank { "p$i" }

/** L'identifiant d'une adresse de la liste (`a<n>`, sa place). */
fun addressId(i: Int): String = "a$i"

/** Le lieu choisi de la liste (une adresse : `a<n>`), sinon `null`. */
fun selectedPlace(places: List<Place>, addresses: List<Place>, sel: String?): Place? {
    if (sel == null) return null
    Regex("""^a(\d+)$""").matchEntire(sel)?.let { return addresses.getOrNull(it.groupValues[1].toInt()) }
    return places.withIndex().firstOrNull { (i, p) -> placeId(p, i) == sel }?.value
}

/**
 * Ce qu'Explorer montre sur la carte : les lieux de la recherche et ses adresses (le choisi, cerclé), et ta position
 * quand on cherche autour de toi.
 */
fun explorerScene(places: List<Place>, addresses: List<Place>, sel: String?, here: LatLon?): Scene = Scene(
    pins = places.mapIndexedNotNull { i, p ->
        p.at?.let { ScenePin(placeId(p, i), it.lat, it.lon, title = p.name, selected = sel == placeId(p, i)) }
    } + addresses.mapIndexedNotNull { i, p ->
        p.at?.let { ScenePin(addressId(i), it.lat, it.lon, title = p.name, selected = sel == addressId(i)) }
    },
    here = here?.let { SceneHere(it.lat, it.lon) },
)

/** La ligne sous le nom d'un lieu choisi : « Camping · Sévrier · à 5,8 km de toi ». */
fun placeLine(p: Place, where: Where): String {
    val dist = p.distanceM?.let { "à ${km(it)}${if (where == Where.HERE) " de toi" else ""}" }.orEmpty()
    return listOf(placeWhat(p), dist).filter { it.isNotBlank() }.joinToString(" · ")
}

/** « En parler à Mika » : la phrase qu'on lui prépare, qu'on complète avant de l'envoyer. */
fun askAboutPlace(p: Place): String {
    val what = listOf(p.kindFr, p.town).filter { it.isNotBlank() }.joinToString(", ")
    return "Tu connais « ${p.name} »${if (what.isNotBlank()) " ($what)" else ""} ? "
}

// ── La vraie carte, ou le plan ──────────────────────────────────────────

/** Pourquoi la carte ne s'est pas dessinée ici : ses tuiles, MapLibre qui ne se charge pas, ou son style. */
enum class LiveFailure { TILES, LOAD, STYLE }

/**
 * La vraie carte se montre-t-elle pour cette scène ? Le fond est prêt, elle ne s'est pas refusée ici ([refused]), et il
 * couvre ce que la scène montre : une de ses épingles ou un point de ses tracés au moins (une scène vide : le fond).
 * [needsHere] (la Position du Téléphone) : il couvre sa position, sans laquelle rien ne se montre.
 */
fun liveWanted(fond: MapFond?, scene: Scene, refused: Boolean, needsHere: Boolean = false): Boolean {
    if (fond == null || !fond.ready || fond.tiles.isBlank() || refused) return false
    if (needsHere) return scene.here?.let { covers(fond, it.lat, it.lon) } ?: false
    val points = scene.pins.map { LatLon(it.lat, it.lon) } + scene.lines.flatMap { it.points }
    return points.isEmpty() || points.any { covers(fond, it.lat, it.lon) }
}

/**
 * Une miniature devient-elle une vraie carte (`frontendv2/src/map/minis.ts::live`) ? Plus exigeant qu'un écran : elle a
 * des épingles, le fond est prêt, elle ne s'est pas refusée ([refused]), et il couvre **tous** ses points — ses épingles,
 * le début et la fin de ses tracés ; un voyage qui sort de la zone garde son plan plutôt qu'une carte à moitié vide.
 */
fun miniWanted(fond: MapFond?, scene: Scene, refused: Boolean): Boolean {
    if (refused || scene.pins.isEmpty()) return false
    val ends = scene.lines.filter { it.points.isNotEmpty() }.flatMap { listOf(it.points.first(), it.points.last()) }
    return coversAll(fond, scene.pins.map { LatLon(it.lat, it.lon) } + ends)
}

/**
 * Pourquoi un plan plutôt que la carte, en mots (la note du plan) : le fond qui se lit encore ou ne se lit pas
 * ([error]), aucun de réglé, son refus ici ([failure]), sinon ce qu'on montre est hors de sa zone ([here] : la
 * Position du Téléphone).
 */
fun planWhy(fond: MapFond?, error: MoiError?, failure: LiveFailure?, here: Boolean = false): String = when {
    fond == null -> error?.message ?: "la carte du serveur se lit…"
    !fond.ready -> fond.reason.ifBlank { "aucune carte n'est réglée sur ce serveur." }
    failure == LiveFailure.TILES -> "ses tuiles ne se lisent pas sur ce serveur en ce moment."
    failure == LiveFailure.LOAD -> "elle ne se charge pas sur ce téléphone."
    failure == LiveFailure.STYLE -> "elle ne se dessine pas sur ce téléphone."
    here -> "ta position est hors de la zone qu'elle couvre."
    else -> "ces lieux sont hors de la zone qu'elle couvre."
}

/** Au-delà de tant de tuiles en échec d'affilée (aucune lue entre deux), la carte ne se dessine pas : le plan revient. */
const val TILE_FAILURES = 4

/**
 * Le compte des tuiles en échec d'affilée : une tuile lue le remet à zéro ; [failed] ne devient vrai qu'une fois. Une
 * tuile absente (204) n'est pas un échec.
 */
class TileWatch(private val limit: Int = TILE_FAILURES) {
    private var streak = 0
    var failed = false
        private set

    /** Une tuile en échec : vrai la seule fois où la série atteint la borne. */
    fun error(): Boolean {
        if (failed) return false
        streak += 1
        if (streak < limit) return false
        failed = true
        return true
    }

    fun ok() {
        if (!failed) streak = 0
    }

    fun reset() {
        streak = 0
        failed = false
    }
}
