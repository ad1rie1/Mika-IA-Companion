package fr.qwartz.mika.ui.carte

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.carte.Bounds
import fr.qwartz.mika.data.moi.carte.CarteApi
import fr.qwartz.mika.data.moi.carte.Coverage
import fr.qwartz.mika.data.moi.carte.DayRange
import fr.qwartz.mika.data.moi.carte.EventItem
import fr.qwartz.mika.data.moi.carte.EventsQuery
import fr.qwartz.mika.data.moi.carte.Regard
import fr.qwartz.mika.data.moi.carte.Scene
import fr.qwartz.mika.data.moi.carte.SceneHere
import fr.qwartz.mika.data.moi.carte.WhenKind
import fr.qwartz.mika.data.moi.carte.Where
import fr.qwartz.mika.data.moi.carte.eventPins
import fr.qwartz.mika.data.moi.carte.eventRef
import fr.qwartz.mika.data.moi.carte.sceneBounds
import fr.qwartz.mika.data.moi.carte.whenRange
import fr.qwartz.mika.ui.map.MapControl
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** La frappe s'arrête tant avant qu'une recherche d'événements parte ; la carte bougée, tant après son dernier geste. */
private const val EVENTS_TYPE_MS = 400L
private const val EVENTS_MOVE_MS = 600L

/**
 * Carte › Événements (ADR 0259), porté de `frontendv2/src/screens/carte/events.ts` sans changer ses règles : ce qui se
 * passe autour de toi (ta dernière position, celle de ton téléphone ; à 20 km, le rayon du serveur) ou dans la zone de
 * la carte (recherchée de nouveau quand on la déplace) — quand (aujourd'hui, ce week-end, cette semaine par défaut, des
 * dates), quoi (les thèmes du serveur, « Gratuit »), un texte —, ce que la base sait de la zone ([coverage]), le choisi.
 * La première recherche part d'elle-même, une fois qu'on sait où chercher. Les événements viennent des offices de
 * tourisme (DATAtourisme), gardés sur ce serveur : chercher ne fait rien sortir. Un modèle par session.
 *
 * Ce que Mika a trouvé (un regard d'événements, `Route.Carte.look`) prend la place de la liste, en rose ; chercher autre
 * chose le quitte.
 */
class EventsViewModel(private val graph: AppGraph, private val store: CarteStore) : ViewModel() {
    private val api: CarteApi get() = store.api

    /** La poignée de la carte de l'onglet : son cadre (« Dans cette zone »), ses cadrages. */
    val control = MapControl()

    var q by mutableStateOf("")
        private set
    var whenKind by mutableStateOf(WhenKind.WEEK)
        private set
    /** Les dates choisies (« Des dates… »). */
    var dates by mutableStateOf(DayRange())
        private set
    var themes by mutableStateOf<List<String>>(emptyList())
        private set
    var free by mutableStateOf(false)
        private set
    /** Où chercher ; `null` tant que ta position ne s'est pas lue. */
    var where by mutableStateOf<Where?>(null)
        private set
    var events by mutableStateOf<List<EventItem>>(emptyList())
        private set
    /** Ce que la base sait de la zone, au même rayon (sa `note` : lue en partie, trop grande, un quota). */
    var coverage by mutableStateOf<Coverage?>(null)
        private set
    /** Le refus du serveur, en mots. */
    var error by mutableStateOf("")
        private set
    var hint by mutableStateOf(ExplorerHint.NONE)
        private set
    var loading by mutableStateOf(false)
        private set
    var searched by mutableStateOf(false)
        private set
    /** La liste montrée est partie de ta position : ce que disent sa tête et sa légende. */
    var searchedNear by mutableStateOf(false)
        private set
    /** L'événement choisi (son identifiant) : son épingle cerclée. */
    var sel by mutableStateOf<String?>(null)
        private set

    /** Le regard de Mika montré (son `seq`), à la place de la liste ; aucun : `null`. */
    var look by mutableStateOf<String?>(null)
        private set

    /** La zone du fond servi (sans vraie carte, « Dans cette zone » y cherche) : l'écran la tient à jour. */
    var fondZone: Bounds? = null

    private var seq = 0
    private var started = false
    private var typeJob: Job? = null
    private var moveJob: Job? = null

    private fun now() = graph.clock.wallMs()

    val regardLoad: Load<Regard>? get() = look?.let { store.regard(it) }

    /** Ses événements, une fois son regard lu (ceux qui ont la forme d'un événement). */
    val regardEvents: List<EventItem>?
        get() = (regardLoad as? Load.Ready)?.value?.events?.filter { eventRef(it.id) != null }

    /** Ce que la liste montre : ses événements à elle, ou ceux de la recherche. */
    val shown: List<EventItem> get() = if (look != null) regardEvents.orEmpty() else events

    /** Ce que la carte montre : les épingles de la liste (roses pour elle), le choisi cerclé, ta position autour de toi. */
    val scene: Scene
        get() {
            val hers = look != null
            val here = if (!hers && where == Where.HERE) store.here else null
            return Scene(pins = eventPins(shown, sel, hers), here = here?.let { SceneHere(it.lat, it.lon) })
        }

    /** L'écran revient : ce qui est branché, ta position ; la première fois, la recherche part d'elle-même. */
    fun resume() {
        store.loadInfo()
        viewModelScope.launch {
            store.loadPosition()
            if (where == null) where = if (store.here != null) Where.HERE else Where.ZONE
            if (!started && look == null) {
                started = true
                search()
            }
        }
    }

    /** Ce que la route ouvre : ce que Mika a trouvé (lu s'il ne l'est pas), ou la liste. */
    fun applyLook(seqOf: String?) {
        if (seqOf == look) {
            seqOf?.let { store.loadRegard(it) }
            return
        }
        look = seqOf
        sel = null
        if (seqOf != null) {
            store.loadRegard(seqOf)
        } else if (!started && where != null) {
            // ouvert sur ce qu'elle avait trouvé, puis quitté : la liste à soi se cherche
            started = true
            launchSearch(refit = true)
        }
    }

    fun retryLook() {
        look?.let { store.loadRegard(it, force = true) }
    }

    /** Chercher autre chose quitte ce que Mika a trouvé : l'écran remet sa route sur l'onglet seul. */
    private fun leaveLook(): Boolean {
        if (look == null) return false
        look = null
        sel = null
        return true
    }

    fun type(text: String) {
        leaveLook()
        q = text.take(CarteApi.QUERY_MAX)
        typeJob?.cancel()
        typeJob = viewModelScope.launch {
            delay(EVENTS_TYPE_MS)
            search(refit = false)
        }
    }

    fun chooseWhen(kind: WhenKind) {
        leaveLook()
        whenKind = kind
        if (kind == WhenKind.DATES && dates.start.isEmpty()) dates = whenRange(WhenKind.WEEK, now())
        launchSearch(refit = false)
    }

    /** Des dates choisies (« Des dates… ») : remises dans l'ordre par [whenRange]. */
    fun chooseDates(range: DayRange) {
        leaveLook()
        whenKind = WhenKind.DATES
        dates = whenRange(WhenKind.DATES, now(), dates = range)
        launchSearch(refit = false)
    }

    fun toggleTheme(id: String) {
        leaveLook()
        themes = if (id in themes) themes - id else themes + id
        launchSearch(refit = false)
    }

    fun toggleFree() {
        leaveLook()
        free = !free
        launchSearch(refit = false)
    }

    fun chooseWhere(next: Where) {
        leaveLook()
        where = next
        launchSearch(refit = true)
    }

    /** Un événement choisi (une épingle) : son épingle cerclée. */
    fun select(id: String?) {
        sel = id
    }

    /** L'événement d'une épingle ou d'une ligne, s'il est encore là. */
    fun eventOf(id: String): EventItem? = shown.firstOrNull { it.id == id }

    /** La carte a bougé : « Dans cette zone » cherche dans ce qu'elle montre maintenant. */
    fun mapMoved() {
        if (look != null || where != Where.ZONE || !searched) return
        moveJob?.cancel()
        moveJob = viewModelScope.launch {
            delay(EVENTS_MOVE_MS)
            search(refit = false)
        }
    }

    fun retry() = launchSearch(refit = false)

    private fun launchSearch(refit: Boolean) {
        typeJob?.cancel()
        viewModelScope.launch { search(refit) }
    }

    /**
     * Une recherche : autour de ta position (connue) ou dans la zone de la carte, aux jours de « quand », des thèmes
     * choisis, du texte, gratuits ou non. Autour de toi, la carte se cadre sur ce qu'on a trouvé ; dans la zone, elle
     * reste où on l'a mise.
     */
    private suspend fun search(refit: Boolean = true) {
        val mine = ++seq
        hint = ExplorerHint.NONE
        store.loadPosition()
        if (mine != seq) return
        val from = where ?: Where.ZONE
        val near = if (from == Where.HERE) store.here?.at else null
        if (from == Where.HERE && near == null) hint = ExplorerHint.NO_POSITION
        val bbox = if (near == null) control.frame() ?: sceneBounds(scene) ?: fondZone else null
        val text = q.trim()
        if (near == null && bbox == null && text.isEmpty()) {
            hint = ExplorerHint.CHOOSE_WHERE
            return
        }
        val range = whenRange(whenKind, now(), dates = dates)
        loading = true
        val got = api.events(EventsQuery(near = near, bbox = bbox, start = range.start, end = range.end, themes = themes, q = text, free = free))
        if (mine != seq) return
        when (got) {
            is MoiApi.Result.Ok -> {
                events = got.value.events.filter { eventRef(it.id) != null }
                coverage = got.value.coverage
                error = ""
            }
            is MoiApi.Result.Failed -> {
                events = emptyList()
                coverage = null
                error = got.error.said
            }
        }
        loading = false
        searched = true
        searchedNear = near != null
        if (sel != null && events.none { it.id == sel }) sel = null
        if (refit && near != null) control.fit()
    }
}
