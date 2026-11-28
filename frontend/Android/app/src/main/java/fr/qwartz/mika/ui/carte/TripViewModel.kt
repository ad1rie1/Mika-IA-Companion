package fr.qwartz.mika.ui.carte

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.files.DownloadStore
import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.carte.AlongNext
import fr.qwartz.mika.data.moi.carte.AlongState
import fr.qwartz.mika.data.moi.carte.CarteLimits
import fr.qwartz.mika.data.moi.carte.GestureQueue
import fr.qwartz.mika.data.moi.carte.GpxDownloads
import fr.qwartz.mika.data.moi.carte.Place
import fr.qwartz.mika.data.moi.carte.Scene
import fr.qwartz.mika.data.moi.carte.Trip
import fr.qwartz.mika.data.moi.carte.TripRoutes
import fr.qwartz.mika.data.moi.carte.TripValues
import fr.qwartz.mika.data.moi.carte.TripsApi
import fr.qwartz.mika.data.moi.carte.alongAfterRoute
import fr.qwartz.mika.data.moi.carte.alongPlace
import fr.qwartz.mika.data.moi.carte.askAboutTrip
import fr.qwartz.mika.data.moi.carte.dropIndex
import fr.qwartz.mika.data.moi.carte.fileName
import fr.qwartz.mika.data.moi.carte.movedTrip
import fr.qwartz.mika.data.moi.carte.movedWords
import fr.qwartz.mika.data.moi.carte.notedTrip
import fr.qwartz.mika.data.moi.carte.noopMove
import fr.qwartz.mika.data.moi.carte.refused
import fr.qwartz.mika.data.moi.carte.removedTrip
import fr.qwartz.mika.data.moi.carte.stepMove
import fr.qwartz.mika.data.moi.carte.stopOf
import fr.qwartz.mika.data.moi.carte.stopOfPlace
import fr.qwartz.mika.data.moi.carte.tripRouteKey
import fr.qwartz.mika.data.moi.carte.tripScene
import fr.qwartz.mika.data.net.Topics
import fr.qwartz.mika.ui.map.MapControl
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

/** L'arrêt dont on écrit la note (un seul à la fois), et ce qu'on a tapé. */
data class Noting(val stop: String, val draft: String)

/**
 * Ce dont un voyage ouvert a besoin hors de l'écran : l'API, les voyages lus de la Carte (partagés pour la session), ce
 * qui suit un voyage changé (la liste, sa miniature), ses mots et le GPX ; la Carte et le graphe de la session en vrai,
 * des faux dans les tests (`TripModelTest`).
 */
class TripDeps(
    val api: TripsApi,
    val reads: TripReads,
    /** Le voyage a changé ici : il se relira, la liste et sa miniature aussi. */
    val changed: (String) -> Unit = { reads.invalidate(it) },
    /** Supprimé : il ne se montre plus nulle part. */
    val forget: (String) -> Unit = { reads.forget(it) },
    /** Ce qui est branché sur le serveur, relu quand l'écran revient. */
    val loadInfo: () -> Unit = {},
    /** Une phrase de l'app (ses chaînes, et ce qu'elles prennent). */
    val words: (Int, Array<out Any>) -> String = { id, args -> (listOf<Any>(id) + args).joinToString("|") },
    /** Le GPX du serveur, rangé dans Téléchargements/Mika. */
    val saveGpx: suspend (DownloadStore.ServedFile) -> DownloadStore.Outcome = { DownloadStore.Outcome.Saved("Téléchargements/Mika") },
    /** Un 401 : la session est à vérifier. */
    val unauthorized: () -> Unit = {},
) {
    constructor(graph: AppGraph, store: CarteStore) : this(
        api = store.trips,
        reads = store.tripReads,
        changed = store::invalidateTrip,
        forget = store::forgetTrip,
        loadInfo = { store.loadInfo() },
        words = { id, args -> graph.context.getString(id, *args) },
        saveGpx = { graph.downloads.saveToDownloads(it) },
        unauthorized = { graph.scope.launch { graph.auth.checkAfterUnauthorized() } },
    )
}

/**
 * Carte › un voyage (ADR 0195, 0235), porté de `frontend/Web/src/screens/carte/trip.ts` sans changer ses règles : ses
 * gestes — déplacer un arrêt, le retirer, le noter, en ajouter, réordonner un jour, le changer — faits l'un après
 * l'autre ([GestureQueue] : chacun part du voyage que le précédent a laissé ; un refus annule ceux qui attendaient) et
 * montrés avant que le serveur les dise ([optimistic]) ; quand plus rien n'attend, le voyage relu, et son trajet un
 * moment après ([TripRoutes] : celui de ces arrêts-ci, jamais celui d'avant un geste). Le voyage relu après un geste
 * l'est après lui : une relecture partie avant (celle d'un geste d'avant, du retour sur l'écran) est suivie d'une autre
 * ([TripReads]), et seule la relecture du dernier geste fini lève ce qu'on montrait. Une relecture qui échoue après des
 * gestes tous aboutis garde ce qu'ils ont posé (le serveur l'a écrit), le dit, et le voyage se relit au retour sur
 * l'écran ([unread]). Un geste refusé (le 409 « la situation a changé » compris) se dit, et le voyage relu montre où il
 * en est. « Sur la route » ne se recherche que si le trajet a changé, et pas pour un panneau fermé. Un modèle par voyage
 * et par session.
 */
class TripViewModel(private val deps: TripDeps, val id: String) : ViewModel() {
    private val api = deps.api
    private val reads = deps.reads
    val control = MapControl()
    private val routes = TripRoutes(viewModelScope, { api.route(it) }, { routeLanded(it) })
    private val gestures = GestureQueue()

    /** Un voyage montré avant que le serveur le dise (un arrêt déplacé, retiré, noté). */
    private var optimistic by mutableStateOf<Trip?>(null)
    /** Un geste refusé (ou annulé derrière un refus) depuis la dernière relecture : ce qu'on montrait de lui n'a pas eu lieu. */
    private var refusedSince = false
    /** Combien de gestes ont fini : la relecture d'un geste laisse faire celle d'un geste fini après lui. */
    private var settled = 0
    /** La relecture d'après tes gestes a échoué : ce qu'ils ont posé reste montré, le voyage se relit au retour sur l'écran. */
    var unread by mutableStateOf(false)
        private set
    /** Change quand un trajet (ou son refus) arrive : ce qui le montre se relit. */
    private var routeVersion by mutableIntStateOf(0)
    var along by mutableStateOf(AlongState(id))
        private set
    /** « Sur la route » ouvert : son panneau en tête de l'éditeur ; fermé, ni lieux, ni épingles, ni relectures. */
    var alongOpen by mutableStateOf(false)
        private set
    private var alongSeq = 0
    var noting by mutableStateOf<Noting?>(null)
        private set
    /** La clé de la note qu'on enregistre (cet arrêt, ce texte) : redite après une panne, elle ne s'écrit qu'une fois. */
    private var noteIntent: Pair<String, String>? = null
    var optimizing by mutableStateOf(false)
        private set
    /** Ce qu'un lecteur d'écran annonce (un arrêt déplacé par « Monter », « Descendre »). */
    var announce by mutableStateOf("")
        private set
    private var framed = false

    private val notices = Channel<String>(Channel.BUFFERED)
    private val gone = Channel<Unit>(Channel.BUFFERED)

    /** Le sort des gestes, une fois chacun (l'écran le montre en toast). */
    val said: Flow<String> = notices.receiveAsFlow()
    /** Le voyage vient d'être supprimé : l'écran s'en va. */
    val deleted: Flow<Unit> = gone.receiveAsFlow()

    private fun say(text: String) {
        if (text.isNotBlank()) notices.trySend(text)
    }

    private fun words(id: Int, vararg args: Any): String = deps.words(id, args)

    /** Ce qu'on a lu du voyage : en lecture, lu, refusé (404 : supprimé, ou pas à toi). */
    val load: Load<Trip> get() = reads[id] ?: Load.Loading

    /** Le voyage tel qu'on le montre : celui d'un geste pas encore confirmé, sinon le dernier lu (aucun : `null`). */
    val shown: Trip? get() = optimistic ?: reads[id]?.valueOrNull

    /** Le trajet de ces arrêts-ci (jamais celui d'avant un geste), son refus, ou qu'il se calcule. */
    fun routeOf(trip: Trip): TripRoutes.Shown {
        @Suppress("UNUSED_VARIABLE") val v = routeVersion // relu quand un trajet arrive
        return routes.shown(trip)
    }

    fun scene(trip: Trip): Scene = tripScene(trip, routeOf(trip).route, along)

    /**
     * L'écran revient : le voyage (s'il a plus de dix secondes ; après une relecture de tes gestes qui a échoué, comme
     * après eux), ce qui est branché ; son trajet s'il le faut.
     */
    fun resume(force: Boolean = false) {
        deps.loadInfo()
        viewModelScope.launch {
            if (unread && !gestures.busy) reloadTrip() else reads.load(id, force)
            val trip = shown
            if (trip != null && !framed) {
                framed = true
                control.fit()
            }
            // le trajet d'un voyage qu'on ouvre : de suite s'il n'est plus celui de ses arrêts (des gestes en cours le reliront)
            if (trip != null && !gestures.busy) routes.want(trip, soon = true, force = force)
        }
    }

    fun retry() = resume(force = true)

    /**
     * Le direct (ADR 0308) : tes voyages ont changé (`trips` — Mika l'a peut-être changé) : relu de suite, sauf pendant
     * tes gestes (leur relecture, à la fin, dira ce qu'il est devenu). Rend la main quand c'est relu.
     */
    suspend fun onLive(signal: LiveSignal) {
        if (!signal.touches(Topics.TRIPS) || gestures.busy) return
        reads.invalidate(id)
        if (unread) reloadTrip() else reads.load(id, force = true)
        val trip = shown
        if (trip != null && !gestures.busy) routes.want(trip, soon = true)
    }

    // ── Les gestes ──────────────────────────────────────────────────────

    /**
     * Un geste sur le voyage : écrit après ceux d'avant, puis — quand plus rien n'attend — le voyage relu, et son trajet
     * un moment après. Un refus se dit (sauf [quiet]) ; rend vrai s'il a abouti, et son refus.
     */
    private suspend fun gesture(quiet: Boolean = false, write: suspend () -> MoiError?): Pair<Boolean, MoiError?> {
        val outcome = gestures.run(write)
        settled += 1
        if (outcome != GestureQueue.Outcome.Done) refusedSince = true
        val error = (outcome as? GestureQueue.Outcome.Refused)?.error
        if (error != null && !quiet) say(error.said)
        if (!gestures.busy) {
            val seen = settled
            viewModelScope.launch { reloadTrip(seen) }
        }
        return (outcome == GestureQueue.Outcome.Done) to error
    }

    /**
     * Après les gestes ([seen] : combien avaient fini) : le voyage relu — après une lecture qui était partie avant eux —,
     * son trajet [fr.qwartz.mika.data.moi.carte.ROUTE_WAIT_MS] après le dernier. Relu, il remplace ce qu'on montrait
     * d'eux. Pas relu (une panne) : l'échec se dit, et le voyage se relira au retour sur l'écran ([unread]) ; si tous ont
     * abouti, ce qu'ils ont posé reste montré (le serveur l'a écrit : le voyage d'avant eux serait faux), sinon le
     * dernier lu fait foi.
     */
    private suspend fun reloadTrip(seen: Int = settled) {
        deps.changed(id)
        val read = reads.load(id, force = true)
        // un autre geste est parti, ou a fini depuis : sa relecture, partie après lui, fera foi
        if (gestures.busy || settled != seen) return
        val failed = read.error?.takeIf { !it.gone }
        unread = failed != null
        if (failed != null) {
            val kept = optimistic?.takeIf { !refusedSince }
            say(words(if (kept != null) R.string.carte_trip_unread_kept else R.string.carte_trip_unread, failed.said))
            if (kept != null) {
                routes.want(kept)
                return
            }
        }
        optimistic = null
        refusedSince = false
        val trip = reads[id]?.valueOrNull ?: return
        routes.want(trip)
        // revenu à des arrêts dont on a déjà le trajet (monté puis redescendu) : rien ne se relit, « Sur la route » suit
        if (!routes.shown(trip).pending) routeLanded(id)
    }

    /** Un trajet (ou son refus) vient d'arriver : « Sur la route », ouvert, suit s'il avait été cherché pour d'autres arrêts. */
    private fun routeLanded(tripId: String) {
        routeVersion += 1
        val trip = reads[tripId]?.valueOrNull ?: return
        if (!alongOpen || along.trip != tripId) return
        val key = tripRouteKey(trip)
        when (alongAfterRoute(along, key)) {
            AlongNext.ADOPT -> along = along.copy(key = key, adopt = false)
            AlongNext.RELOAD -> loadAlong(along.cat)
            AlongNext.KEEP -> Unit
        }
    }

    /** L'arrêt lâché (ou monté, descendu) : déplacé à ce jour, à cet indice ; lâché où il était, rien ne part. */
    fun moveTo(stop: String, day: Int, index: Int) {
        val trip = shown ?: return
        if (noopMove(trip, stop, day, index)) return
        optimistic = movedTrip(trip, stop, day, index)
        val key = MoiApi.newKey()
        viewModelScope.launch { gesture { (api.moveStop(id, stop, day, index, key) as? MoiApi.Result.Failed)?.error } }
    }

    /** Un arrêt glissé lâché au jour [day], avant l'arrêt [before] (`null` : à la fin du jour) ; lâché sur lui-même, rien. */
    fun drop(stop: String, day: Int, before: String?) {
        val trip = shown ?: return
        if (before == stop) return
        moveTo(stop, day, dropIndex(trip, stop, day, before))
    }

    /** « Monter » (−1) ou « Descendre » (+1) d'une place, d'un jour à l'autre au bord ; dit à un lecteur d'écran. */
    fun step(stop: String, delta: Int) {
        val trip = shown ?: return
        val (day, index) = stepMove(trip, stop, delta) ?: return
        moveTo(stop, day, index)
        shown?.let { announce = movedWords(it, stop) }
    }

    /** Retiré de suite à l'écran (un second appui ne trouve plus son bouton), écrit après les autres gestes. */
    fun remove(stop: String) {
        val trip = shown ?: return
        val s = stopOf(trip, stop) ?: return
        optimistic = removedTrip(trip, stop)
        if (noting?.stop == stop) noting = null
        val key = MoiApi.newKey()
        viewModelScope.launch {
            val (ok, _) = gesture { (api.removeStop(id, stop, key) as? MoiApi.Result.Failed)?.error }
            if (ok) say(words(if (s.hers) R.string.carte_stop_removed_hers else R.string.carte_stop_removed))
        }
    }

    // ── La note d'un arrêt ──────────────────────────────────────────────

    /** « Noter » : le champ en place, prérempli de sa note ; un autre arrêt en saisie se referme (un seul à la fois). */
    fun openNote(stop: String) {
        val s = shown?.let { stopOf(it, stop) } ?: return
        if (noting?.stop == stop) {
            noting = null
            return
        }
        noting = Noting(stop, s.note)
    }

    fun typeNote(text: String) {
        noting = noting?.copy(draft = text.take(CarteLimits.NOTE))
    }

    /** « Annuler » : le champ se referme sans rien écrire. */
    fun closeNote() {
        noting = null
    }

    /**
     * « Enregistrer » : la note (vidée : effacée) montrée de suite, écrite après les autres gestes, avec la clé de cette
     * intention (cet arrêt, ce texte). Refusée ou pas partie, le champ se rouvre sur ce qu'on avait tapé.
     */
    fun saveNote() {
        val trip = shown ?: return
        val n = noting ?: return
        val s = stopOf(trip, n.stop) ?: return
        val note = n.draft.trim().take(CarteLimits.NOTE)
        if (note == s.note) {
            noting = null
            return
        }
        val intent = "${n.stop}|$note"
        if (noteIntent?.first != intent) noteIntent = intent to MoiApi.newKey()
        val key = noteIntent!!.second
        optimistic = notedTrip(trip, n.stop, note)
        noting = null
        viewModelScope.launch {
            val (ok, error) = gesture { (api.noteStop(id, n.stop, note, key) as? MoiApi.Result.Failed)?.error }
            if (ok || refused(error)) noteIntent = null
            if (ok) {
                say(words(if (note.isNotEmpty()) R.string.carte_note_saved else R.string.carte_note_cleared))
                return@launch
            }
            // pas écrite : ce qu'on avait tapé revient dans son champ, si on n'en a pas ouvert un autre entre-temps
            if (noting == null && shown?.let { stopOf(it, n.stop) } != null) noting = n
        }
    }

    // ── Optimiser, ajouter, changer, supprimer ──────────────────────────

    /** Le meilleur ordre de chaque jour qui a trois arrêts ou plus (le départ et la nuit ne bougent pas). */
    fun optimize() {
        val trip = shown ?: return
        if (optimizing) return
        val days = trip.days.filter { it.stops.size >= 3 }
        if (days.isEmpty()) {
            say(words(R.string.carte_optimize_nothing))
            return
        }
        optimizing = true
        viewModelScope.launch {
            var moved = 0
            val (ok, _) = gesture {
                var refusal: MoiError? = null
                for (d in days) {
                    when (val got = api.optimize(id, d.n, MoiApi.newKey())) {
                        is MoiApi.Result.Ok -> if (got.value.order != d.stops.map { it.id }) moved += 1
                        is MoiApi.Result.Failed -> {
                            refusal = got.error
                            break
                        }
                    }
                }
                refusal
            }
            optimizing = false
            if (ok) say(words(if (moved > 0) R.string.carte_optimize_done else R.string.carte_optimize_same))
        }
    }

    /**
     * Ajouter un lieu au voyage (« Ajouter un arrêt », « Sur la route »), avec la clé de cette intention : redit (un
     * double appui, un réessai), le serveur ne l'ajoute qu'une fois. Après les autres gestes. Rend vrai s'il est là.
     */
    private suspend fun addPlace(p: Place, day: Int, index: Int, key: String, note: String = ""): Pair<Boolean, MoiError?> {
        val stop = stopOfPlace(p, day, index, note) ?: run {
            val error = MoiError(400, words(R.string.carte_add_no_coords))
            say(error.message)
            return false to error
        }
        val title = shown?.title.orEmpty().ifBlank { words(R.string.carte_untitled_lc) }
        var deduped = false
        val got = gesture {
            when (val r = api.addStop(id, stop, key)) {
                is MoiApi.Result.Ok -> {
                    deduped = r.value.deduped
                    null
                }
                is MoiApi.Result.Failed -> r.error
            }
        }
        if (got.first) say(if (deduped) words(R.string.carte_added_already, title) else words(R.string.carte_added_to, title, day))
        return got
    }

    /**
     * « Ajouter un arrêt » à un jour (à la fin), par le modèle : la fenêtre qui l'a demandé peut se fermer, le geste va au
     * bout. Rend vrai s'il est là, et son refus.
     */
    fun addStopAsync(p: Place, day: Int, key: String, note: String): Deferred<Pair<Boolean, MoiError?>> =
        viewModelScope.async { addPlace(p, day, -1, key, note) }

    /** Un lieu de « Sur la route », ajouté au bon jour (avant l'arrêt qu'on atteint après lui). */
    fun addAlong(i: Int) {
        val trip = shown ?: return
        val state = along
        val p = state.places.getOrNull(i) ?: return
        val key = state.keys.getOrNull(i) ?: return
        if (state.sending == i) return
        val (day, index) = alongPlace(trip, routes.shown(trip).route, p.alongM)
        along = state.copy(sending = i)
        viewModelScope.launch {
            val (ok, _) = addPlace(p, day, index, key)
            if (along.trip == id && along.keys === state.keys && along.sending == i) {
                along = along.copy(sending = null, adopt = along.adopt || ok)
            }
        }
    }

    /** « Sur la route » : une catégorie (la même : la liste se ferme). */
    fun toggleAlong(cat: String) {
        if (along.cat == cat) {
            alongSeq += 1
            along = AlongState(id)
            return
        }
        loadAlong(cat)
    }

    /** « Sur la route » (le bouton sous la carte, ⋮) : ouvert, ou refermé. */
    fun toggleAlongPanel() {
        if (alongOpen) closeAlong() else alongOpen = true
    }

    /** « Sur la route » refermé : ses lieux et leurs épingles s'en vont, rien ne se recherche plus pour lui. */
    fun closeAlong() {
        alongSeq += 1
        along = AlongState(id)
        alongOpen = false
    }

    /** L'écran du voyage s'en va (pas une rotation) : « Sur la route » se referme, il ne survit pas à la sortie. */
    fun leave() = closeAlong()

    private fun loadAlong(cat: String) {
        val seq = ++alongSeq
        val trip = reads[id]?.valueOrNull
        val key = trip?.let { tripRouteKey(it) }.orEmpty()
        along = AlongState(id, cat = cat, loading = true, key = key)
        viewModelScope.launch {
            val got = api.along(id, cat = cat)
            if (seq != alongSeq) return@launch
            along = when (got) {
                // une clé par lieu, faite avec la liste : « Ajouter » touché deux fois ne l'ajoute qu'une fois
                is MoiApi.Result.Ok -> AlongState(id, cat, got.value.places, routed = got.value.route, key = key, keys = got.value.places.map { MoiApi.newKey() })
                is MoiApi.Result.Failed -> AlongState(id, cat, error = got.error.said, key = key)
            }
        }
    }

    /** « Le voyage » : ce qui a changé (son titre, sa date, son mode, ce qu'il évite), après les autres gestes ; rend son refus. */
    fun changeAsync(values: TripValues, key: String): Deferred<Pair<Boolean, MoiError?>> = viewModelScope.async {
        val got = gesture(quiet = true) { (api.change(id, values, key) as? MoiApi.Result.Failed)?.error }
        if (got.first) say(words(R.string.carte_trip_changed))
        got
    }

    /** Supprimer le voyage (confirmé par l'écran) : il ne se montre plus nulle part, l'écran s'en va. */
    fun delete() {
        val key = MoiApi.newKey()
        viewModelScope.launch {
            when (val got = api.remove(id, key)) {
                is MoiApi.Result.Ok -> {
                    deps.forget(id)
                    say(words(R.string.carte_trip_deleted))
                    gone.trySend(Unit)
                }
                is MoiApi.Result.Failed -> say(got.error.said)
            }
        }
    }

    /** « Demander à Mika » : la phrase préparée. */
    fun askText(): String = askAboutTrip(shown?.title.orEmpty())

    /**
     * Le GPX du voyage, celui du serveur (ses arrêts, et le tracé quand il se calcule), dans Téléchargements/Mika —
     * demandé après les gestes partis avant lui : il dit l'ordre que l'écran montre.
     */
    fun gpx() {
        if (shown == null) return
        val url = api.gpxUrl(id) ?: return say(words(R.string.carte_signed_out))
        viewModelScope.launch {
            gestures.settled()
            val trip = shown ?: return@launch
            val name = fileName(trip.title.ifBlank { "voyage-$id" }, "gpx")
            val file = DownloadStore.ServedFile(url, name, GpxDownloads.MIME, "trip-gpx|$id|${trip.updated}")
            when (val got = deps.saveGpx(file)) {
                is DownloadStore.Outcome.Saved -> say(words(R.string.carte_gpx_saved_trip, got.folder))
                is DownloadStore.Outcome.Failed -> {
                    if (got.sessionExpired) deps.unauthorized()
                    say(got.message)
                }
                is DownloadStore.Outcome.Ready -> Unit
            }
        }
    }
}
