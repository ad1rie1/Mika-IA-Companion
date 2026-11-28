package fr.qwartz.mika.ui.carte

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.carte.ADDRESS_WAIT_MS
import fr.qwartz.mika.data.moi.carte.AddressBook
import fr.qwartz.mika.data.moi.carte.Bounds
import fr.qwartz.mika.data.moi.carte.CarteApi
import fr.qwartz.mika.data.moi.carte.CarteInfo
import fr.qwartz.mika.data.moi.carte.Coverage
import fr.qwartz.mika.data.moi.carte.LatLon
import fr.qwartz.mika.data.moi.carte.MOVE_MS
import fr.qwartz.mika.data.moi.carte.PLACES_SHOWN
import fr.qwartz.mika.data.moi.carte.MIN_RATING
import fr.qwartz.mika.data.moi.carte.POSITION_TTL_MS
import fr.qwartz.mika.data.moi.carte.PRELOAD_REREAD_MS
import fr.qwartz.mika.data.moi.carte.Place
import fr.qwartz.mika.data.moi.carte.PlaceFilters
import fr.qwartz.mika.data.moi.carte.PlacesQuery
import fr.qwartz.mika.data.moi.carte.Regard
import fr.qwartz.mika.data.moi.carte.Scene
import fr.qwartz.mika.data.moi.carte.TYPE_MS
import fr.qwartz.mika.data.moi.carte.Where
import fr.qwartz.mika.data.moi.carte.addressWanted
import fr.qwartz.mika.data.moi.carte.explorerScene
import fr.qwartz.mika.data.moi.carte.nextSort
import fr.qwartz.mika.data.moi.carte.placeId
import fr.qwartz.mika.data.moi.carte.regardLine
import fr.qwartz.mika.data.moi.carte.regardPins
import fr.qwartz.mika.data.moi.carte.sceneBounds
import fr.qwartz.mika.data.moi.carte.selectedPlace
import fr.qwartz.mika.data.moi.carte.toggledFeature
import fr.qwartz.mika.data.moi.carte.wantsReread
import fr.qwartz.mika.data.moi.carte.withRefreshed
import fr.qwartz.mika.data.moi.phone.PhoneMoiApi
import fr.qwartz.mika.data.moi.phone.PhonePosition
import fr.qwartz.mika.ui.map.MapControl
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.max

/** Une phrase de plus sous la recherche : sa position inconnue, ou rien pour savoir où chercher. */
enum class ExplorerHint { NONE, NO_POSITION, CHOOSE_WHERE }

/**
 * Carte › Explorer (ADR 0194, 0235), porté de `frontend/Web/src/screens/carte/explorer.ts` sans changer ses règles :
 * chercher dans l'index des lieux du serveur (un nom, une catégorie, autour de ta dernière position ou dans la zone de
 * la carte, recherchée de nouveau quand on la déplace) et une adresse (Géoplateforme, relayée : seul le texte part ;
 * seulement si le texte en a l'air, après une pause de frappe, une fois par texte) ; le lieu choisi. Un modèle par
 * session : la recherche survit à un autre onglet, à une rotation. Ce qui n'est pas prêt (503) ou trop demandé (429)
 * se dit à l'endroit qui l'a reçu : les lieux, ou les adresses — le reste marche.
 *
 * Depuis l'ADR 0259, la liste se filtre (ouvert maintenant, ce qu'offre le lieu, sa note Google, sa cuisine) et se range
 * (les plus proches, les mieux notés) ; elle dit ce que le cache des notes sait de l'endroit ([coverage]). « Autour de
 * moi » envoie ta position avec `here=1` : le serveur précharge les notes de ta case, et la liste se relit une fois,
 * quelques secondes plus tard, si elles n'étaient pas toutes lues. Un lieu qui a une fiche l'ouvre (`Route.PlaceFiche`).
 *
 * Ce que Mika a cherché ou montré (un regard, `Route.Carte.look`) prend la place de la recherche : ses lieux en rose,
 * son tracé tel qu'elle l'a gardé ; chercher autre chose le quitte. Les adresses déjà trouvées sont celles de la Carte
 * ([CarteStore.book]) : Itinéraire et un arrêt de voyage ne redemandent pas un texte qu'Explorer a cherché.
 */
class ExplorerViewModel(private val graph: AppGraph, private val store: CarteStore) : ViewModel() {
    private val api = CarteApi(graph.moi)
    private val phone = PhoneMoiApi(graph.moi)
    private val book: AddressBook get() = store.book

    /** La poignée de la carte d'Explorer : son cadre (« Dans cette zone »), ses cadrages. */
    val control = MapControl()

    /** Ce qui est branché sur le serveur, et les catégories. */
    var info by mutableStateOf<Load<CarteInfo>>(Load.Loading)
        private set
    var q by mutableStateOf("")
        private set
    var cat by mutableStateOf("")
        private set
    /** Où chercher ; `null` tant que ta position ne s'est pas lue (on sait alors : autour de toi, ou la zone). */
    var where by mutableStateOf<Where?>(null)
        private set
    var places by mutableStateOf<List<Place>>(emptyList())
        private set
    var addresses by mutableStateOf<List<Place>>(emptyList())
        private set
    /** Le refus de l'index (503 : pas construit ; 429…), en mots. */
    var error by mutableStateOf("")
        private set
    /** Le refus des adresses, en mots. */
    var addrError by mutableStateOf("")
        private set
    var loading by mutableStateOf(false)
        private set
    var searched by mutableStateOf(false)
        private set
    /** La recherche montrée est partie de ta position (inconnue : de la zone de la carte) : ce que dit sa légende. */
    var searchedNear by mutableStateOf(false)
        private set
    /** Les filtres et l'ordre de la liste (ADR 0259). */
    var filters by mutableStateOf(PlaceFilters())
        private set
    /** Ce que le cache des notes Google sait de l'endroit cherché (la ligne « Notes Google Maps lues le … »). */
    var coverage by mutableStateOf<Coverage?>(null)
        private set
    /** Le lieu choisi (son identifiant dans la liste). */
    var sel by mutableStateOf<String?>(null)
        private set
    var hint by mutableStateOf(ExplorerHint.NONE)
        private set
    private var position by mutableStateOf<PhonePosition?>(null)
    private var positionAt = 0L
    private var positionSettled = false

    /** La zone du fond servi (sans vraie carte ni lieux, « Dans cette zone » y cherche) : l'écran la tient à jour. */
    var fondZone: Bounds? = null

    /** Le texte dont les adresses montrées viennent : la carte bougée, une catégorie ne les redemandent pas. */
    private var addrQ = ""
    private var typedAt = 0L
    private var searchSeq = 0
    private var started = false
    private var typeJob: Job? = null
    private var moveJob: Job? = null
    private var addrJob: Job? = null
    private var rereadJob: Job? = null

    init {
        // « Actualiser » dans une fiche : la ligne de ce lieu montre ce que la fiche relue dit (R2-A06)
        viewModelScope.launch { store.refreshed.collect { (id, fresh) -> places = withRefreshed(places, id, fresh) } }
    }

    /** Ta dernière position (son téléphone), si elle est connue. */
    val here: LatLon?
        get() {
            val p = position ?: return null
            val c = p.coords ?: return null
            return if (p.known) LatLon(c.lat, c.lon) else null
        }

    /** Le regard de Mika qu'Explorer montre (son `seq`), à la place de la recherche ; aucun : `null`. */
    var look by mutableStateOf<String?>(null)
        private set

    /** Ce regard, tel qu'il se lit (en lecture, lu, refusé) ; aucun : `null`. */
    val regardLoad: Load<Regard>? get() = look?.let { store.regard(it) }

    /** Ce regard, lu (oublié depuis : plus rien). */
    val regard: Regard? get() = (regardLoad as? Load.Ready)?.value

    /**
     * Ce que la carte montre : ce que Mika a cherché (ses lieux en rose, le choisi cerclé, son tracé) — rien tant qu'il
     * se lit ou s'il ne se lit pas ; sinon les lieux et les adresses, le choisi cerclé, ta position quand on cherche
     * autour de toi.
     */
    val scene: Scene
        get() {
            if (look != null) {
                val r = regard ?: return Scene.EMPTY
                return Scene(pins = regardPins(r).map { it.copy(selected = it.id == sel) }, lines = regardLine(r))
            }
            return explorerScene(places, addresses, sel, if (where == Where.HERE) here else null)
        }

    /** Le lieu choisi, s'il est encore dans la liste (celle de son regard, quand elle en montre un). */
    val chosen: Place?
        get() {
            if (look != null) return regard?.places?.withIndex()?.firstOrNull { (i, p) -> placeId(p, i) == sel }?.value
            return selectedPlace(places, addresses, sel)
        }

    /** Ce que la route ouvre dans Explorer : un regard de Mika (lu s'il ne l'est pas), ou rien (la recherche revient). */
    fun applyLook(seq: String?) {
        if (seq == look) {
            seq?.let { store.loadRegard(it) }
            return
        }
        look = seq
        sel = null
        if (seq != null) store.loadRegard(seq)
    }

    fun retryLook() {
        look?.let { store.loadRegard(it, force = true) }
    }

    /** Chercher autre chose quitte le regard de Mika : l'écran remet sa route sur Explorer seul. */
    private fun leaveLook() {
        if (look == null) return
        look = null
        sel = null
    }

    /** L'écran revient : ce qui est branché et ta position, relus ; la première fois, « Autour de moi » si elle est connue. */
    fun resume() {
        val first = !started
        started = true
        viewModelScope.launch {
            if (first || info !is Load.Ready) loadInfo()
            else when (val got = api.info()) {
                is MoiApi.Result.Ok -> info = Load.Ready(got.value)
                is MoiApi.Result.Failed -> Unit // une relecture qui échoue garde ce qu'on savait
            }
        }
        viewModelScope.launch {
            loadPosition()
            if (where == null) {
                where = if (here != null) Where.HERE else Where.ZONE
                // autour de toi : la carte se cadre sur ta position
                if (where == Where.HERE) control.fit()
            }
        }
    }

    fun retryInfo() {
        info = Load.Loading
        viewModelScope.launch { loadInfo() }
    }

    private suspend fun loadInfo() {
        info = when (val got = api.info()) {
            is MoiApi.Result.Ok -> Load.Ready(got.value)
            is MoiApi.Result.Failed -> Load.Failed(got.error)
        }
    }

    /** Ta position, relue si elle a plus de quinze secondes ; une lecture qui échoue : on ne sait pas où tu es. */
    private suspend fun loadPosition() {
        val now = graph.clock.wallMs()
        if (positionSettled && now - positionAt < POSITION_TTL_MS) return
        when (val got = phone.position()) {
            is MoiApi.Result.Ok -> position = got.value
            is MoiApi.Result.Failed -> if (!positionSettled) position = null
        }
        positionAt = graph.clock.wallMs()
        positionSettled = true
    }

    /** La frappe : la recherche part une fois qu'elle s'arrête ; l'adresse attend davantage, une fois par texte. */
    fun type(text: String) {
        leaveLook()
        q = text.take(CarteApi.QUERY_MAX)
        typedAt = graph.clock.wallMs()
        typeJob?.cancel()
        addrJob?.cancel()
        typeJob = viewModelScope.launch {
            delay(TYPE_MS)
            sel = null
            search()
        }
    }

    /** Une catégorie (la même : plus de catégorie). */
    fun chooseCategory(id: String) {
        leaveLook()
        cat = if (cat == id) "" else id
        sel = null
        launchSearch()
    }

    /** Autour de toi, ou dans la zone de la carte. */
    fun chooseWhere(next: Where) {
        leaveLook()
        where = next
        sel = null
        launchSearch()
    }

    /** Un lieu de la liste, ou une épingle touchée (le même : plus rien de choisi). */
    fun select(id: String?) {
        sel = if (id != null && sel == id) null else id
        chosen?.at?.let { control.show(it) }
    }

    /** Une épingle touchée : son lieu, choisi. */
    fun pinTouched(id: String) {
        sel = id
    }

    /** Le lieu d'une épingle ou d'une ligne (celle de son regard, quand elle en montre un), s'il est encore là. */
    fun placeOf(id: String): Place? {
        if (look != null) return regard?.places?.withIndex()?.firstOrNull { (i, p) -> placeId(p, i) == id }?.value
        return selectedPlace(places, addresses, id)
    }

    // ── Les filtres et l'ordre (ADR 0259) ─────────────────────────────────

    fun toggleOpen() = applyFilters(filters.copy(open = !filters.open))

    fun toggleFeature(id: String) = applyFilters(toggledFeature(filters, id))

    /** « 4 et plus » : sa note Google (elle écarte les lieux sans note). */
    fun toggleRating() = applyFilters(filters.copy(minRating = if (filters.minRating == null) MIN_RATING else null))

    /** Une cuisine (vide : toutes). */
    fun chooseCuisine(cuisine: String) = applyFilters(filters.copy(cuisine = cuisine.trim()))

    /** L'ordre suivant : les plus proches, les mieux notés. */
    fun nextOrder() {
        val sorts = (info as? Load.Ready)?.value?.sorts.orEmpty()
        applyFilters(filters.copy(sort = nextSort(sorts, filters.sort)))
    }

    /** Un filtre de plus ou de moins : la recherche se refait sans recadrer la carte (le lieu choisi s'oublie). */
    private fun applyFilters(next: PlaceFilters) {
        if (next == filters) return
        filters = next
        sel = null
        typeJob?.cancel()
        viewModelScope.launch { search(refit = false) }
    }

    /** La personne a bougé la carte : « Dans cette zone » cherche dans ce qu'elle montre maintenant. */
    fun mapMoved() {
        if (look != null || where != Where.ZONE || (q.isBlank() && cat.isEmpty())) return
        moveJob?.cancel()
        moveJob = viewModelScope.launch {
            delay(MOVE_MS)
            search(refit = false)
        }
    }

    private fun launchSearch() {
        typeJob?.cancel()
        viewModelScope.launch { search() }
    }

    /**
     * Une recherche : l'index local (le texte, la catégorie, autour de toi ou dans la zone), puis les adresses — elles ne
     * dépendent pas de la zone : seul un autre texte les redemande.
     */
    private suspend fun search(refit: Boolean = true, reread: Boolean = false) {
        val text = q.trim()
        val seq = ++searchSeq
        if (!reread) {
            hint = ExplorerHint.NONE
            rereadJob?.cancel()
        }
        if (text.isEmpty() && cat.isEmpty()) {
            addrJob?.cancel()
            places = emptyList()
            addresses = emptyList()
            coverage = null
            addrQ = ""
            error = ""
            addrError = ""
            searched = false
            loading = false
            return
        }
        loadPosition()
        if (seq != searchSeq) return
        val from = where ?: Where.ZONE
        var near: LatLon? = null
        if (from == Where.HERE) {
            near = here
            if (near == null) hint = ExplorerHint.NO_POSITION
        }
        val bbox = if (near == null) control.frame() ?: sceneBounds(scene) ?: fondZone else null
        if (text.isEmpty() && near == null && bbox == null) {
            hint = ExplorerHint.CHOOSE_WHERE
            return
        }
        if (!reread) loading = true
        // autour de toi : ta propre position (`here`), le serveur précharge les notes de ta case ; un point de la carte, non
        val query = PlacesQuery(q = text, cat = cat, near = near, bbox = bbox, limit = PLACES_SHOWN, filters = filters, here = near != null)
        val got = api.list(query)
        if (seq != searchSeq) return
        when (got) {
            is MoiApi.Result.Ok -> {
                places = got.value.places
                coverage = got.value.reviews
                error = ""
            }
            is MoiApi.Result.Failed -> {
                // la relecture après le préchargement : une panne passagère ne vide pas la liste montrée
                if (reread) return
                places = emptyList()
                coverage = null
                error = got.error.said
            }
        }
        searchedNear = near != null
        if (!reread && text != addrQ) findAddresses(text, places.isNotEmpty())
        loading = false
        searched = true
        if (sel != null && chosen == null) sel = null
        if (!reread && refit && from == Where.HERE) control.fit()
        // les notes de ta case arrivent au prochain affichage : la liste se relit une fois, un peu plus tard
        if (!reread && wantsReread(coverage, near != null)) {
            rereadJob = viewModelScope.launch {
                delay(PRELOAD_REREAD_MS)
                search(refit = false, reread = true)
            }
        }
    }

    /**
     * Les adresses d'un texte nouveau : si le texte en a l'air ([addressWanted]), à la Géoplateforme, une fois la saisie
     * arrêtée ([ADDRESS_WAIT_MS]) et une fois par texte. Sans adresses branchées, un numéro reçoit le message du serveur.
     */
    private fun findAddresses(text: String, hasPlaces: Boolean) {
        addrJob?.cancel()
        addrQ = text
        addresses = emptyList()
        addrError = ""
        val ready = (info as? Load.Ready)?.value?.addresses?.ready == true
        if (!addressWanted(text, hasPlaces, ready)) return
        book.peek(text)?.let {
            addresses = it
            return
        }
        addrJob = viewModelScope.launch {
            delay(max(0L, typedAt + ADDRESS_WAIT_MS - graph.clock.wallMs()))
            if (addrQ != text || q.trim() != text) return@launch
            val got = book.lookup(text)
            if (addrQ != text || q.trim() != text) return@launch
            when (got) {
                is MoiApi.Result.Ok -> {
                    addresses = got.value
                    addrError = ""
                }
                is MoiApi.Result.Failed -> {
                    addresses = emptyList()
                    addrError = got.error.said
                }
            }
            if (sel != null && chosen == null) sel = null
        }
    }
}
