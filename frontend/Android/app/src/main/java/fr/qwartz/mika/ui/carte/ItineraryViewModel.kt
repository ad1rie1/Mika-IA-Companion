package fr.qwartz.mika.ui.carte

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.files.DownloadStore
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.carte.ADDRESS_WAIT_MS
import fr.qwartz.mika.data.moi.carte.CarteLimits
import fr.qwartz.mika.data.moi.carte.GpxDownloads
import fr.qwartz.mika.data.moi.carte.ItiPoint
import fr.qwartz.mika.data.moi.carte.Itinerary
import fr.qwartz.mika.data.moi.carte.LatLon
import fr.qwartz.mika.data.moi.carte.NewStop
import fr.qwartz.mika.data.moi.carte.Place
import fr.qwartz.mika.data.moi.carte.Regard
import fr.qwartz.mika.data.moi.carte.RouteChoice
import fr.qwartz.mika.data.moi.carte.RouteChoices
import fr.qwartz.mika.data.moi.carte.Scene
import fr.qwartz.mika.data.moi.carte.SceneLine
import fr.qwartz.mika.data.moi.carte.ScenePin
import fr.qwartz.mika.data.moi.carte.TripValues
import fr.qwartz.mika.data.moi.carte.askAboutRoute
import fr.qwartz.mika.data.moi.carte.chosenPoints
import fr.qwartz.mika.data.moi.carte.fileName
import fr.qwartz.mika.data.moi.carte.herePoint
import fr.qwartz.mika.data.moi.carte.itiKey
import fr.qwartz.mika.data.moi.carte.placeWhat
import fr.qwartz.mika.data.moi.carte.pointLetter
import fr.qwartz.mika.data.moi.carte.pointOf
import fr.qwartz.mika.data.moi.carte.refused
import fr.qwartz.mika.data.moi.carte.routeChoices
import fr.qwartz.mika.data.moi.carte.routeGpx
import fr.qwartz.mika.data.moi.carte.routeName
import fr.qwartz.mika.data.moi.carte.routeTrack
import fr.qwartz.mika.data.moi.carte.safeDecode
import fr.qwartz.mika.data.moi.carte.typedPoint
import fr.qwartz.mika.data.moi.carte.validPoint
import fr.qwartz.mika.data.moi.carte.wantsAddress
import fr.qwartz.mika.data.moi.carte.withChoice
import fr.qwartz.mika.ui.map.MapControl
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch
import kotlin.math.max

/** Une proposition pour un point : sa position ([mine]), une adresse, un lieu de l'index. */
data class Suggestion(val label: String, val sub: String, val point: ItiPoint, val mine: Boolean = false)

/** Les propositions du point ouvert ; [note] : ce que les adresses n'ont pas pu dire (429, 503), en mots. */
data class Suggestions(
    val mine: List<Suggestion> = emptyList(),
    val addresses: List<Suggestion> = emptyList(),
    val places: List<Suggestion> = emptyList(),
    val note: String = "",
) {
    val all: List<Suggestion> get() = mine + addresses + places
}

/** Ce que Mika a calculé (un regard du chat), tel qu'elle l'a gardé, jusqu'à ton premier changement. */
data class RegardShown(val title: String, val distanceM: Double?, val durationS: Double?, val line: List<LatLon>, val key: String)

/** Combien d'adresses une liste de propositions montre. */
private const val ADDRESSES_SUGGESTED = 4
/** La frappe dans un point s'arrête tant avant que ses propositions se cherchent. */
private const val POINT_TYPE_MS = 250L

/**
 * Ce qu'un geste lent demande à l'écran qui l'a lancé quand il finit (ouvrir le voyage qu'il vient de créer) : suivi
 * seulement si l'écran est là à cet instant. Sinon [send] rend la main à l'appelant (un toast avec « Ouvrir »), et rien
 * n'attend le retour de l'écran pour l'emmener ailleurs plus tard ; ce qui n'avait pas encore été suivi quand il s'en
 * va est jeté. Un compte plutôt qu'un drapeau : une rotation compose le nouvel écran avant de défaire l'ancien.
 */
internal class ShownOrders<T> {
    private val channel = Channel<T>(Channel.BUFFERED)
    private var shown = 0

    /** Ce que l'écran à l'écran doit suivre. */
    val flow: Flow<T> = channel.receiveAsFlow()

    fun enter() {
        shown += 1
    }

    fun leave() {
        shown = max(0, shown - 1)
        if (shown == 0) while (channel.tryReceive().isSuccess) Unit
    }

    /** Vrai : l'écran est là, il le suivra ; faux : il n'y est pas, à l'appelant de le dire autrement. */
    fun send(order: T): Boolean {
        if (shown == 0) return false
        channel.trySend(order)
        return true
    }
}

/**
 * Carte › Itinéraire (ADR 0194, 0235), porté de `frontend/Web/src/screens/carte/itinerary.ts` sans changer ses règles :
 * ses points et leurs propositions (ta position, les lieux de l'index, les adresses), le calcul du trajet (seulement
 * quand tous ses points sont choisis, et pas deux fois le même), le regard de Mika (ce qu'elle a calculé, posé tel
 * qu'elle l'a gardé, sans rien recalculer avant ton premier changement), tes choix (`own` : le mode, ce qu'il évite,
 * écrits par tes seuls gestes), le GPX fait ici et « En faire un voyage ». Un point retapé rend le trajet montré passé
 * ([stale]) : ni consignes, ni GPX, ni voyage avant de le choisir. Un modèle par session : l'itinéraire survit à un autre
 * onglet, à une rotation.
 */
class ItineraryViewModel(private val graph: AppGraph, private val store: CarteStore) : ViewModel() {
    val control = MapControl()

    var points by mutableStateOf(listOf(ItiPoint(), ItiPoint()))
        private set
    /** Tes choix (le mode, ce qu'il évite) : écrits par tes seuls gestes, repris par un trajet que tu commences. */
    private var own = RouteChoices()
    /** Le mode et ce qu'évite le trajet montré : les tiens, ou ceux du trajet de Mika qu'on regarde (et qu'on modifie). */
    var mode by mutableStateOf("voiture")
        private set
    var avoid by mutableStateOf<List<String>>(emptyList())
        private set
    var route by mutableStateOf<Itinerary?>(null)
        private set
    /** [itiKey] des points, du mode et de ce qu'évitait le trajet montré : un autre, il est passé. */
    private var routeFor = ""
    var routeError by mutableStateOf("")
        private set
    var routing by mutableStateOf(false)
        private set
    private var routeSeq = 0
    var suggestFor by mutableStateOf<Int?>(null)
        private set
    var sugg by mutableStateOf(Suggestions())
        private set
    private var suggestSeq = 0
    /** Ce que Mika a calculé, tel qu'elle l'a gardé, jusqu'à ton premier changement. */
    var regard by mutableStateOf<RegardShown?>(null)
        private set
    /** Le regard dont les points ont été posés : il ne se repose pas sur ce que tu as changé depuis. */
    private var regardFrom: String? = null
    /** Le regard que la route demande (son `seq`) : Itinéraire dit s'il ne se lit pas. */
    var look by mutableStateOf<String?>(null)
        private set
    private var lookJob: Job? = null
    /** La dernière frappe dans un point : une adresse attend [ADDRESS_WAIT_MS] après elle. */
    private var typedAt = 0L
    private var typeJob: Job? = null
    private var addrJob: Job? = null
    /** « En faire un voyage » : en cours, et la clé de cette intention (redemandé après une panne : le même voyage). */
    var sendingTrip by mutableStateOf(false)
        private set
    private var tripIntent: Pair<String, String>? = null

    private val notices = Channel<String>(Channel.BUFFERED)
    private val made = ShownOrders<String>()

    /** Le sort des gestes, une fois chacun (l'écran le montre en toast). */
    val said: Flow<String> = notices.receiveAsFlow()
    /** Un voyage né de l'itinéraire pendant que l'onglet est à l'écran (son identifiant) : l'écran l'ouvre. */
    val opened: Flow<String> = made.flow

    /** L'onglet paraît ([on]) ou s'en va : un voyage fini pendant son absence ne l'emmènera nulle part. */
    fun shown(on: Boolean) = if (on) made.enter() else made.leave()

    private fun now() = graph.clock.wallMs()
    private fun say(text: String) {
        if (text.isNotBlank()) notices.trySend(text)
    }

    /** Ce regard, tel qu'il se lit (en lecture, lu, refusé) ; aucun : `null`. */
    val lookLoad: Load<Regard>? get() = look?.let { store.regard(it) }

    /** Ce que montre l'itinéraire est-il celui de ses points (un point retapé, un trajet qui se recalcule : non) ? */
    val stale: Boolean
        get() {
            val shownKey = if (route != null) routeFor else regard?.key
            return typedPoint(points) || (shownKey != null && shownKey != itiKey(points, mode, avoid))
        }

    /** Ses points (A, 1, 2…, B ; roses tant que le trajet de Mika se montre), et le tracé s'il est encore le leur. */
    val scene: Scene
        get() {
            val n = points.size
            val hers = regard != null && route == null
            val pins = points.mapIndexedNotNull { i, p ->
                if (!validPoint(p.lat, p.lon)) null
                else ScenePin("pt$i", p.lat!!, p.lon!!, label = pointLetter(i, n), title = p.name.ifBlank { p.query }, mika = hers)
            }
            val r = route
            val shown = regard
            val lines = when {
                stale -> emptyList()
                r != null -> r.legs.map { safeDecode(it.shape) }.filter { it.size >= 2 }.map { SceneLine(it) }
                shown != null && shown.line.size >= 2 -> listOf(SceneLine(shown.line, mika = true))
                else -> emptyList()
            }
            return Scene(pins = pins, lines = lines)
        }

    /** L'onglet revient : ce qui est branché et ta position, relus ; un départ de ta position, s'il est vide. */
    fun resume() {
        store.loadInfo()
        viewModelScope.launch {
            store.loadPosition()
            // un itinéraire part de sa position, quand son téléphone l'a donnée (la maquette : « Ma position · … »)
            val start = points[0]
            val here = store.here
            if (look == null && regard == null && here != null && start.query.isEmpty() && start.lat == null) {
                points = listOf(herePoint(here.lat, here.lon, here.label)) + points.drop(1)
                control.fit()
            }
        }
    }

    /** « Itinéraire jusqu'ici » (Explorer) : de ta position à ce lieu, avec tes choix (pas ceux d'un trajet de Mika). */
    fun routeTo(p: Place) {
        viewModelScope.launch {
            store.loadPosition()
            val here = store.here
            points = listOf(here?.let { herePoint(it.lat, it.lon, it.label) } ?: ItiPoint(), pointOf(p))
            val c = routeChoices(own, null)
            mode = c.mode
            avoid = c.avoid
            route = null
            routeFor = ""
            routeError = ""
            regard = null
            regardFrom = null
            look = null
            closeSuggestions()
            control.fit()
            computeRoute()
        }
    }

    /** Ce que la route ouvre dans Itinéraire : un trajet de Mika (un regard), posé une fois qu'il est lu. */
    fun applyLook(seq: String?) {
        if (seq == null) {
            // la route ne le demande plus (un autre onglet, puis celui-ci) : ce qui se montre reste
            look = null
            lookJob?.cancel()
            return
        }
        if (look != seq) {
            look = seq
            if (regardFrom != seq) regard = null
        }
        store.loadRegard(seq)
        lookJob?.cancel()
        lookJob = viewModelScope.launch {
            val got = snapshotFlow { store.regard(seq) }.first { it is Load.Ready || it is Load.Failed }
            if (got is Load.Ready && regardFrom != seq && look == seq) applyRegard(seq, got.value)
        }
    }

    fun retryLook() {
        val seq = look ?: return
        store.loadRegard(seq, force = true)
        applyLook(seq)
    }

    /**
     * Ce que Mika a calculé, posé tel qu'elle l'a gardé : ses points, son mode, ce qu'elle évitait (quand le regard le
     * dit), son tracé et son résumé. Rien ne se recalcule avant ton premier changement (ou « Recalculer »). Son mode et
     * ses cases se montrent sans devenir les tiens ([own]).
     */
    private fun applyRegard(seq: String, r: Regard) {
        regardFrom = seq
        val pts = r.places.filter { it.at != null }
        if (pts.size >= 2) points = pts.take(CarteLimits.POINTS).map { pointOf(it) }
        // ce qu'un regard ne dit pas (un regard d'avant ne dit pas ce qu'il évitait) : tes choix
        val c = routeChoices(own, r.route)
        mode = c.mode
        avoid = c.avoid
        regard = RegardShown(r.title, r.route?.distanceM, r.route?.durationS, safeDecode(r.route?.shape), itiKey(points, mode, avoid))
        route = null
        routeFor = ""
        routeError = ""
        routing = false
        routeSeq += 1
        closeSuggestions()
        control.fit()
    }

    /**
     * Ton geste sur le mode ou une case : le trajet montré le prend, et il devient ton choix pour les trajets que tu
     * commences — lui seul ([withChoice]) : les autres cases d'un trajet de Mika ne deviennent pas tiennes.
     */
    fun choose(choice: RouteChoice) {
        own = withChoice(own, choice)
        val shown = withChoice(RouteChoices(mode, avoid), choice)
        mode = shown.mode
        avoid = shown.avoid
        changed()
    }

    /** Tu changes l'itinéraire (un mode, une case, un point) : ce que Mika avait calculé cède la place, il se recalcule. */
    private fun changed() {
        val r = regard
        if (r != null && r.key == itiKey(points, mode, avoid) && !typedPoint(points)) return // rien de ce qui fait le trajet n'a changé
        regard = null
        computeRoute()
    }

    /** « Recalculer » : le trajet et ses consignes, calculés de nouveau ici (le sien se montre jusqu'à leur arrivée). */
    fun recompute() = computeRoute(force = true)

    /** Le trajet de ces points : demandé seulement s'ils sont tous choisis et qu'il n'est pas déjà celui-là ([force] : si). */
    private fun computeRoute(force: Boolean = false) {
        val chosen = chosenPoints(points)
        val key = itiKey(points, mode, avoid)
        val seq = ++routeSeq
        if (chosen.size < 2 || typedPoint(points) || (!force && route != null && routeFor == key)) {
            // un point retapé, pas encore choisi : rien ne part (le trajet d'avant se montre, passé)
            if (chosen.size < 2) {
                route = null
                routeFor = ""
            }
            routeError = ""
            routing = false
            return
        }
        routing = true
        viewModelScope.launch {
            val got = store.api.route(chosen.map { LatLon(it.lat, it.lon) }, mode, if (mode == "voiture") avoid else emptyList())
            if (seq != routeSeq) return@launch
            when (got) {
                is MoiApi.Result.Ok -> {
                    route = got.value
                    routeFor = key
                    routeError = ""
                    regard = null
                    control.fit()
                }
                is MoiApi.Result.Failed -> {
                    route = null
                    routeFor = ""
                    routeError = got.error.said
                }
            }
            routing = false
        }
    }

    // ── Les points et leurs propositions ────────────────────────────────

    /** Retapé : le point perd ses coordonnées, le trajet montré est passé jusqu'à ce qu'on en choisisse un. */
    fun type(i: Int, text: String) {
        if (i !in points.indices) return
        points = points.toMutableList().also { it[i] = ItiPoint(query = text.take(200)) }
        typedAt = now()
        typeJob?.cancel()
        addrJob?.cancel()
        typeJob = viewModelScope.launch {
            delay(POINT_TYPE_MS)
            suggest(i, text)
        }
    }

    /** Un point vide prend la main : ses propositions (ta position d'abord). */
    fun focus(i: Int) {
        if (i !in points.indices || points[i].query.isNotEmpty() || suggestFor == i) return
        typeJob?.cancel()
        typeJob = viewModelScope.launch { suggest(i, "") }
    }

    /**
     * Les propositions d'un point : sa position, les lieux de l'index (rien ne sort) ; une adresse, si le texte en a
     * l'air, gardée par texte et demandée après une pause de la saisie. Un refus des adresses (429…) se dit sous la liste.
     */
    private suspend fun suggest(i: Int, text: String) {
        val q = text.trim()
        val seq = ++suggestSeq
        addrJob?.cancel()
        store.loadPosition()
        val here = store.here
        val mine = if (here != null && (q.isEmpty() || "ma position".startsWith(q.lowercase()))) {
            listOf(Suggestion(graph.context.getString(R.string.carte_my_position), here.label.ifBlank { graph.context.getString(R.string.carte_last_position) }, herePoint(here.lat, here.lon, here.label), mine = true))
        } else {
            emptyList()
        }
        val info = store.info.valueOrNull
        val places = if (q.length >= 2 && info?.places?.ready == true) {
            (store.api.places(q = q, near = here?.at, limit = 6) as? MoiApi.Result.Ok)?.value.orEmpty()
        } else {
            emptyList()
        }
        if (seq != suggestSeq) return
        val wanted = info?.addresses?.ready == true && wantsAddress(q)
        val known = if (wanted) store.book.peek(q) else null
        sugg = Suggestions(mine, known.orEmpty().take(ADDRESSES_SUGGESTED).mapNotNull(::suggestionOf), places.mapNotNull(::suggestionOf))
        if (wanted && known == null) {
            addrJob = viewModelScope.launch {
                delay(max(0L, typedAt + ADDRESS_WAIT_MS - now()))
                suggestAddresses(i, q, seq)
            }
        }
        showSuggestions(i)
    }

    private suspend fun suggestAddresses(i: Int, q: String, seq: Int) {
        val got = store.book.lookup(q)
        if (seq != suggestSeq) return
        sugg = when (got) {
            is MoiApi.Result.Ok -> sugg.copy(addresses = got.value.take(ADDRESSES_SUGGESTED).mapNotNull(::suggestionOf), note = "")
            is MoiApi.Result.Failed -> sugg.copy(addresses = emptyList(), note = got.error.said)
        }
        showSuggestions(i)
    }

    private fun suggestionOf(p: Place): Suggestion? = if (p.at == null) null else Suggestion(p.name, placeWhat(p), pointOf(p))

    private fun showSuggestions(i: Int) {
        suggestFor = if (sugg.all.isNotEmpty() || sugg.note.isNotEmpty()) i else null
    }

    fun closeSuggestions() {
        addrJob?.cancel()
        suggestSeq += 1
        suggestFor = null
        sugg = Suggestions()
    }

    /** Une proposition choisie : le point prend ses coordonnées, le trajet se calcule ; rend le prochain point vide (−1 : aucun). */
    fun pick(i: Int, j: Int): Int {
        val s = sugg.all.getOrNull(j) ?: return -1
        if (i !in points.indices) return -1
        points = points.toMutableList().also { it[i] = s.point }
        closeSuggestions()
        control.fit()
        changed()
        return points.indexOfFirst { !it.chosen }
    }

    /** Une étape de plus, avant l'arrivée (20 points au plus). */
    fun addStep(): Int {
        if (points.size >= CarteLimits.POINTS) return -1
        points = points.toMutableList().also { it.add(it.size - 1, ItiPoint()) }
        return points.size - 2
    }

    fun swap() {
        closeSuggestions()
        points = points.reversed()
        changed()
    }

    fun removeStep(i: Int) {
        if (i <= 0 || i >= points.size - 1) return
        closeSuggestions()
        points = points.toMutableList().also { it.removeAt(i) }
        changed()
    }

    // ── Ce qu'on en fait ────────────────────────────────────────────────

    /** Ce qu'on dit à Mika du trajet montré : le calculé, sinon le sien ; passé, rien que ses points. */
    fun askText(): String {
        val names = chosenPoints(points).map { it.name }
        val r = route
        val shown = regard
        return when {
            stale -> askAboutRoute(names, null, null, mode)
            r != null -> askAboutRoute(names, r.distanceM, r.durationS, mode)
            shown != null -> askAboutRoute(names, shown.distanceM, shown.durationS, mode)
            else -> askAboutRoute(names, null, null, mode)
        }
    }

    /**
     * « En faire un voyage » : le voyage, puis ses arrêts au jour 1. Une clé par intention (ces points, ce mode) : redit
     * après une panne à mi-chemin, le serveur rend le même voyage et n'ajoute pas deux fois un arrêt déjà là. Fini avec
     * l'onglet à l'écran, le voyage s'ouvre ; fini ailleurs (jusqu'à 21 requêtes en série : on a pu changer d'onglet),
     * [elsewhere] le dit avec de quoi l'ouvrir, et rien ne t'emmène tout seul.
     */
    fun makeTrip(elsewhere: (id: String, text: String) -> Unit) {
        val chosen = chosenPoints(points)
        if (chosen.size < 2 || sendingTrip || stale) return
        sendingTrip = true
        val key = itiKey(points, mode, avoid)
        if (tripIntent?.first != key) tripIntent = key to MoiApi.newKey()
        val nonce = tripIntent!!.second
        val values = TripValues(title = routeName(chosen).take(CarteLimits.TITLE), mode = mode, avoid = if (mode == "voiture") avoid else emptyList())
        viewModelScope.launch {
            var error: MoiError? = null
            var id = ""
            when (val got = store.trips.create(values, nonce)) {
                is MoiApi.Result.Ok -> id = got.value.id
                is MoiApi.Result.Failed -> error = got.error
            }
            if (error == null) {
                for ((i, p) in chosen.withIndex()) {
                    val stop = NewStop(p.name.take(CarteLimits.NAME).ifBlank { "Point" }, p.lat, p.lon, day = 1, index = -1)
                    val added = store.trips.addStop(id, stop, "$nonce-${i + 1}")
                    if (added is MoiApi.Result.Failed) {
                        error = added.error
                        break
                    }
                }
            }
            val failed = error
            if (failed != null) {
                if (refused(failed)) tripIntent = null
                say(failed.said)
            } else {
                tripIntent = null
                store.loadList(force = true)
                val text = graph.context.getString(R.string.carte_trip_made_from_route)
                if (made.send(id)) say(text) else elsewhere(id, text)
            }
            sendingTrip = false
        }
    }

    /** Le GPX de l'itinéraire, fait ici (ses points, son tracé — le calculé, sinon celui que Mika a gardé), dans Téléchargements/Mika. */
    fun gpx() {
        val chosen = chosenPoints(points)
        if (chosen.size < 2 || stale) return
        val title = routeName(chosen)
        val track = route?.let { routeTrack(it) } ?: regard?.line.orEmpty()
        val text = routeGpx(title, chosen, track)
        viewModelScope.launch {
            when (val got = GpxDownloads.save(graph.context, fileName(title, "gpx"), text)) {
                is DownloadStore.Outcome.Saved -> say(graph.context.getString(R.string.carte_gpx_saved, got.folder))
                is DownloadStore.Outcome.Failed -> say(got.message)
                is DownloadStore.Outcome.Ready -> Unit
            }
        }
    }
}
