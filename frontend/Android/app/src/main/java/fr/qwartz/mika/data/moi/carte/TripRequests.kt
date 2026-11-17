package fr.qwartz.mika.data.moi.carte

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/*
 * Ménager ce qui sort du serveur, et ne rien faire deux fois — porté de `frontendv2/src/screens/carte/requests.ts` sans
 * changer ses règles. Un trajet compte dans les bornes du serveur (`protocole-moi.md` § 10 : 20 par minute et par
 * compte, 429 au-delà ; le serveur d'itinéraires public ne répond qu'une fois par seconde, pour tous). Ici : le trajet
 * d'un voyage gardé pour ses arrêts et relu un moment après le dernier geste ([TripRoutes]), les gestes sur un voyage
 * faits l'un après l'autre ([GestureQueue]), quand un envoi refusé a usé sa clé ([refused]), et quand « Sur la route »
 * se recherche ([alongAfterRoute]).
 */

/** Combien de temps après le dernier geste le trajet d'un voyage se relit (dix gestes d'affilée : une seule relecture). */
const val ROUTE_WAIT_MS = 1_500L

/**
 * Un envoi refusé par le serveur (400, 404, 409 : il a lu, et dit non) a usé sa clé : le refaire est une autre demande,
 * avec une autre clé. Une panne, un 429, un 503 : on ne sait pas s'il a abouti, ou il n'a pas été tenté — on le refait
 * avec la même clé, et le serveur ne refait pas ce qui l'a été.
 */
fun refused(error: MoiError?): Boolean = error != null && error.code in setOf(400, 404, 409)

/**
 * Le trajet de chaque voyage, gardé pour ce dont il dépend ([tripRouteKey] : ses arrêts dans l'ordre, son mode, ce
 * qu'il évite) : un trajet qui n'est plus celui des arrêts ne se montre pas. Un voyage qui change se relit [wait] ms
 * après le dernier geste ; ouvert, de suite ; sous deux arrêts, il n'a pas de trajet. [landed] : un trajet (ou son
 * refus) vient d'arriver. Tout se fait dans [scope] (le fil principal d'un ViewModel) : rien n'y est partagé ailleurs.
 */
class TripRoutes(
    private val scope: CoroutineScope,
    private val fetcher: suspend (String) -> MoiApi.Result<TripRoute>,
    private val landed: (String) -> Unit,
    private val wait: Long = ROUTE_WAIT_MS,
) {
    /** Ce qu'on montre du trajet d'un voyage tel qu'il est maintenant : le sien, son refus, ou qu'il se calcule. */
    data class Shown(val route: TripRoute?, val error: MoiError?, val pending: Boolean)

    private class State(val key: String, val route: TripRoute?, val error: MoiError?)

    private val states = HashMap<String, State>()
    /** Le voyage tel qu'on le sait : c'est lui qu'une relecture sert. */
    private val latest = HashMap<String, Trip>()
    private val timers = HashMap<String, Job>()
    /** La relecture en cours (sa clé), et le numéro de la dernière partie. */
    private val reading = HashMap<String, String>()
    private val seqs = HashMap<String, Int>()

    fun shown(trip: Trip): Shown {
        if (routableStops(trip) < 2) return Shown(null, null, false)
        val state = states[trip.id]
        if (state != null && state.key == tripRouteKey(trip)) return Shown(state.route, state.error, false)
        return Shown(null, null, true)
    }

    /**
     * Le voyage tel qu'il est (ouvert, relu, changé par un geste) : son trajet se relit s'il n'est plus le sien —
     * [soon] : de suite (sans écourter un geste qui attend déjà) ; sinon [wait] ms après ce geste-ci. [force] : même
     * s'il l'est (« Réessayer »).
     */
    fun want(trip: Trip, soon: Boolean = false, force: Boolean = false) {
        val id = trip.id
        latest[id] = trip
        if (routableStops(trip) < 2) {
            cancel(id)
            states.remove(id)
            return
        }
        val key = tripRouteKey(trip)
        if (!force && (states[id]?.key == key || reading[id] == key)) {
            cancel(id) // revenu à ce qu'on a déjà (un arrêt monté puis redescendu) : rien à relire
            return
        }
        if (soon && !force && timers.containsKey(id)) return
        cancel(id)
        if (soon || force) {
            scope.launch { read(id) }
            return
        }
        timers[id] = scope.launch {
            delay(wait)
            timers.remove(id)
            read(id)
        }
    }

    private fun cancel(id: String) {
        timers.remove(id)?.cancel()
    }

    private suspend fun read(id: String) {
        val trip = latest[id] ?: return
        val key = tripRouteKey(trip)
        val seq = (seqs[id] ?: 0) + 1
        seqs[id] = seq
        reading[id] = key
        val state = when (val got = fetcher(id)) {
            is MoiApi.Result.Ok -> State(key, got.value, null)
            is MoiApi.Result.Failed -> State(key, null, got.error)
        }
        if (seqs[id] != seq) return // une relecture plus récente est partie
        reading.remove(id)
        states[id] = state
        landed(id)
    }
}

/**
 * Les gestes sur un voyage, faits l'un après l'autre : chacun part du voyage que le précédent a laissé (son index se lit
 * sur lui). Un geste refusé annule ceux qui attendaient derrière lui : ils partaient d'un voyage qui n'a pas eu lieu.
 */
class GestureQueue {
    /** Ce qu'un geste a donné : fait, annulé (un geste d'avant a été refusé), ou refusé (en mots). */
    sealed interface Outcome {
        data object Done : Outcome
        data object Cancelled : Outcome
        data class Refused(val error: MoiError) : Outcome
    }

    private val mutex = Mutex()
    private var waiting = 0
    private var generation = 0

    /** Un geste en cours, ou qui attend. */
    val busy: Boolean get() = waiting > 0

    /** [write] : le geste, qui rend son refus (`null` : fait). */
    suspend fun run(write: suspend () -> MoiError?): Outcome {
        val mine = generation
        waiting += 1
        try {
            return mutex.withLock {
                if (mine != generation) return@withLock Outcome.Cancelled
                val error = write()
                if (error == null) {
                    Outcome.Done
                } else {
                    generation += 1
                    Outcome.Refused(error)
                }
            }
        } finally {
            waiting -= 1
        }
    }

    /**
     * Attendre que les gestes partis avant cet appel soient faits (ou annulés) — le verrou est équitable, il passe
     * après eux —, sans en être un : rien n'attend derrière lui, et un refus ne l'annule pas (le GPX d'un voyage).
     */
    suspend fun settled() {
        mutex.withLock { }
    }
}

/** « Sur la route » d'un voyage : ses lieux, et pour quels arrêts ils ont été cherchés ([key]). */
data class AlongState(
    val trip: String,
    /** La catégorie cherchée ; vide : fermé. */
    val cat: String = "",
    val places: List<Place> = emptyList(),
    val error: String = "",
    val loading: Boolean = false,
    /** Faux : sans itinéraires, le long des arrêts reliés à vol d'oiseau. */
    val routed: Boolean = true,
    /** [tripRouteKey] du voyage quand ils ont été cherchés : un autre trajet, ils se recherchent. */
    val key: String = "",
    /** Une clé d'envoi par lieu de la liste : un double appui sur « Ajouter » ne l'ajoute qu'une fois. */
    val keys: List<String> = emptyList(),
    /** Le lieu qui s'ajoute. */
    val sending: Int? = null,
    /**
     * Un de ses lieux vient d'être ajouté : le trajet change (il y passe), la liste reste vraie — elle prend la clé du
     * prochain trajet au lieu de se rechercher (dix ajouts : dix trajets relus, pas vingt demandes).
     */
    val adopt: Boolean = false,
)

/** Ce que « Sur la route » fait quand le voyage a un autre trajet : rien, prendre sa clé, ou se rechercher. */
enum class AlongNext { KEEP, ADOPT, RELOAD }

/**
 * « Sur la route » quand le voyage a un autre trajet ([key]) : rien à faire (fermé, ou déjà cherché pour lui) ; prendre
 * sa clé sans rien demander (un de ses lieux vient d'être ajouté, la liste reste vraie) ; ou se rechercher.
 */
fun alongAfterRoute(along: AlongState, key: String): AlongNext = when {
    along.cat.isEmpty() || along.key == key -> AlongNext.KEEP
    along.adopt && !along.loading -> AlongNext.ADOPT
    else -> AlongNext.RELOAD
}
