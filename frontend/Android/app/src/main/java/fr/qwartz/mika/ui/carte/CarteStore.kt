package fr.qwartz.mika.ui.carte

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.carte.AddressBook
import fr.qwartz.mika.data.moi.carte.CarteApi
import fr.qwartz.mika.data.moi.carte.CarteInfo
import fr.qwartz.mika.data.moi.carte.LatLon
import fr.qwartz.mika.data.moi.carte.MiniRef
import fr.qwartz.mika.data.moi.carte.POSITION_TTL_MS
import fr.qwartz.mika.data.moi.carte.Place
import fr.qwartz.mika.data.moi.carte.Regard
import fr.qwartz.mika.data.moi.carte.Trip
import fr.qwartz.mika.data.moi.carte.TripSummary
import fr.qwartz.mika.data.moi.carte.TripValues
import fr.qwartz.mika.data.moi.carte.TripsApi
import fr.qwartz.mika.data.moi.carte.WriteDone
import fr.qwartz.mika.data.moi.carte.refOf
import fr.qwartz.mika.data.moi.carte.stopOfPlace
import fr.qwartz.mika.data.moi.phone.PhoneMoiApi
import fr.qwartz.mika.data.moi.phone.PhonePosition
import fr.qwartz.mika.ui.map.MiniStore
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.rememberSessionKey
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.launch

/** Ta dernière position, telle qu'un itinéraire ou un voyage la prend : ses coordonnées et le nom du lieu. */
data class Here(val lat: Double, val lon: Double, val label: String) {
    val at: LatLon get() = LatLon(lat, lon)
}

/** Ce qu'un ajout de lieu à un voyage a donné : fait (ou déjà fait pour cette clé), ou refusé en mots. */
sealed interface AddOutcome {
    data class Added(val day: Int, val deduped: Boolean) : AddOutcome
    data class Refused(val error: MoiError) : AddOutcome
}

/**
 * Ce que les onglets de la Carte, un voyage ouvert et les miniatures (la liste des voyages ; demain le chat) partagent
 * pour la session — le cadre de `frontendv2/src/screens/carte/index.ts` : ce qui est branché sur le serveur, ta dernière
 * position, les adresses déjà trouvées, ce que Mika a cherché ou montré (ses regards), la liste de tes voyages, chaque
 * voyage lu, et ce que montrent les miniatures. Chaque lecture se garde un moment (les rythmes du web) ; une relecture
 * qui échoue garde ce qu'on savait, sauf un 404 (oublié, supprimé : ce qu'on en avait lu ne se montre plus).
 */
class CarteStore(private val graph: AppGraph) : ViewModel() {
    val api = CarteApi(graph.moi)
    val trips = TripsApi(graph.moi)
    private val phone = PhoneMoiApi(graph.moi)

    /** Les adresses déjà trouvées, par texte : un texte ne se redemande pas (Explorer, Itinéraire, un arrêt). */
    val book = AddressBook(viewModelScope, { q, limit -> api.addresses(q, limit) })

    /** Ce que montrent les miniatures, lu une fois pour la session (un voyage changé ici se relit quand elle reparaît). */
    val minis = MiniStore(viewModelScope, { trips.read(it) }, { api.regard(it) }, graph.clock::wallMs)

    private fun now() = graph.clock.wallMs()

    // ── Ce qui est branché ──────────────────────────────────────────────

    var info by mutableStateOf<Load<CarteInfo>>(Load.Loading)
        private set
    private var infoAt = 0L
    private var infoJob: Job? = null

    fun loadInfo(force: Boolean = false) {
        if (!force && info is Load.Ready && now() - infoAt < INFO_TTL_MS) return
        if (infoJob?.isActive == true) return
        infoJob = viewModelScope.launch {
            when (val got = api.info()) {
                is MoiApi.Result.Ok -> {
                    info = Load.Ready(got.value)
                    infoAt = now()
                }
                is MoiApi.Result.Failed -> if (info !is Load.Ready) info = Load.Failed(got.error)
            }
        }
    }

    // ── Ta dernière position ────────────────────────────────────────────

    private var position by mutableStateOf<PhonePosition?>(null)
    private var positionAt = 0L
    /** Ta position s'est lue au moins une fois (connue ou non). */
    var positionSettled by mutableStateOf(false)
        private set
    private var positionJob: Deferred<Unit>? = null

    /** Ta dernière position (son téléphone), si elle est connue ; le nom du lieu, s'il en a un. */
    val here: Here?
        get() {
            val p = position ?: return null
            val c = p.coords ?: return null
            return if (p.known) Here(c.lat, c.lon, p.label.trim()) else null
        }

    /** Ta position, relue si elle a plus de quinze secondes ; une lecture qui échoue : on ne sait pas où tu es. */
    suspend fun loadPosition() {
        if (positionSettled && now() - positionAt < POSITION_TTL_MS) return
        val running = positionJob?.takeIf { it.isActive } ?: viewModelScope.async {
            when (val got = phone.position()) {
                is MoiApi.Result.Ok -> position = got.value
                is MoiApi.Result.Failed -> if (!positionSettled) position = null
            }
            positionAt = now()
            positionSettled = true
        }.also { positionJob = it }
        running.await()
    }

    // ── Ses regards ─────────────────────────────────────────────────────

    private val regards = mutableStateMapOf<String, Load<Regard>>()
    private val regardAt = HashMap<String, Long>()
    private val regardJobs = HashMap<String, Job>()

    /** Ce qu'elle a cherché ou montré (`regards/<seq>`) : en lecture, lu, ou refusé ; jamais demandé : `null`. */
    fun regard(seq: String): Load<Regard>? = regards[seq]

    fun loadRegard(seq: String, force: Boolean = false) {
        val ref = refOf(seq) ?: run {
            regards[seq] = Load.Failed(MoiError(404, graph.context.getString(R.string.carte_regard_gone_title)))
            return
        }
        val known = regards[ref]
        if (!force && known is Load.Ready && now() - (regardAt[ref] ?: 0) < REGARD_TTL_MS) return
        if (regardJobs[ref]?.isActive == true) return
        if (known !is Load.Ready) regards[ref] = Load.Loading
        regardJobs[ref] = viewModelScope.launch {
            val got = api.regard(ref)
            regards[ref] = when {
                got is MoiApi.Result.Ok -> Load.Ready(got.value).also { regardAt[ref] = now() }
                got is MoiApi.Result.Failed && (got.error.gone || known !is Load.Ready) -> Load.Failed(got.error)
                else -> known ?: Load.Loading
            }
        }
    }

    // ── Tes voyages ─────────────────────────────────────────────────────

    var list by mutableStateOf<Load<List<TripSummary>>>(Load.Loading)
        private set
    private var listAt = 0L
    private var listJob: Job? = null

    /** La liste, relue si elle a plus de quinze secondes (ou [force]) ; ce que la liste dit plus récent vieillit sa miniature. */
    fun loadList(force: Boolean = false) {
        if (!force && list is Load.Ready && now() - listAt < LIST_TTL_MS) return
        if (listJob?.isActive == true) return
        listJob = viewModelScope.launch {
            when (val got = trips.list()) {
                is MoiApi.Result.Ok -> {
                    list = Load.Ready(got.value)
                    listAt = now()
                }
                is MoiApi.Result.Failed -> if (list !is Load.Ready) list = Load.Failed(got.error)
            }
        }
    }

    fun retryList() {
        list = Load.Loading
        loadList(force = true)
    }

    /** Chaque voyage lu (relu s'il a plus de dix secondes ; une relecture forcée suit celle qui était partie avant). */
    val tripReads = TripReads(viewModelScope, { trips.read(it) }, ::now)

    /** Un voyage tel qu'on l'a lu ; jamais demandé : `null`. */
    fun trip(id: String): Load<Trip>? = tripReads[id]

    /** Un voyage changé (ici, ou supprimé) : relu à la prochaine lecture, la liste et sa miniature aussi. */
    fun invalidateTrip(id: String) {
        tripReads.invalidate(id)
        listAt = 0
        minis.invalidate(MiniRef.trip(id).id)
    }

    /** Un voyage supprimé : il ne se montre plus nulle part. */
    fun forgetTrip(id: String) {
        invalidateTrip(id)
        tripReads.forget(id)
        (list as? Load.Ready)?.let { l -> list = Load.Ready(l.value.filter { it.id != id }) }
    }

    /** Un voyage neuf (et son premier arrêt, s'il naît d'un lieu), chacun avec sa clé : redit, le même voyage. */
    suspend fun createTrip(values: TripValues, key: String, first: Place? = null, firstKey: String = ""): MoiApi.Result<WriteDone> {
        val made = trips.create(values, key)
        if (made !is MoiApi.Result.Ok) return made
        val id = made.value.id
        val stop = first?.let { stopOfPlace(it, day = 1, index = -1) }
        if (stop != null && id.isNotEmpty()) {
            val added = trips.addStop(id, stop, firstKey)
            if (added is MoiApi.Result.Failed) return added
        }
        listAt = 0
        return made
    }

    /**
     * Ajouter un lieu à un voyage qui n'est pas ouvert (Explorer, « Ajouter au voyage »), avec la clé de cette intention :
     * redit (un double appui, un réessai), le serveur ne l'ajoute qu'une fois. Le voyage ouvert passe par ses gestes.
     */
    suspend fun addPlace(trip: String, p: Place, day: Int, index: Int, key: String): AddOutcome {
        val stop = stopOfPlace(p, day, index) ?: return AddOutcome.Refused(MoiError(400, graph.context.getString(R.string.carte_add_no_coords)))
        return when (val got = trips.addStop(trip, stop, key)) {
            is MoiApi.Result.Ok -> {
                invalidateTrip(trip)
                AddOutcome.Added(day, got.value.deduped)
            }
            is MoiApi.Result.Failed -> AddOutcome.Refused(got.error)
        }
    }

    /** [createTrip] par le modèle : la fenêtre qui l'a demandé peut se fermer, la création va au bout. */
    fun createTripAsync(values: TripValues, key: String, first: Place?, firstKey: String): Deferred<MoiApi.Result<WriteDone>> =
        viewModelScope.async { createTrip(values, key, first, firstKey) }

    /** [addPlace] par le modèle : la feuille qui l'a demandé peut se fermer, l'ajout va au bout. */
    fun addPlaceAsync(trip: String, p: Place, day: Int, index: Int, key: String): Deferred<AddOutcome> =
        viewModelScope.async { addPlace(trip, p, day, index, key) }

    companion object {
        /** Ce qui est branché : relu au plus chaque minute (le web). */
        const val INFO_TTL_MS = 60_000L
        const val LIST_TTL_MS = 15_000L
        const val TRIP_TTL_MS = 10_000L
        const val REGARD_TTL_MS = 5 * 60_000L
    }
}

/** Ce que la Carte partage pour la session (une par session, comme les autres modèles de l'app). */
@Composable
internal fun rememberCarteStore(graph: AppGraph): CarteStore {
    val session = rememberSessionKey(graph)
    return viewModel(key = "carte.store|$session") { CarteStore(graph) }
}
