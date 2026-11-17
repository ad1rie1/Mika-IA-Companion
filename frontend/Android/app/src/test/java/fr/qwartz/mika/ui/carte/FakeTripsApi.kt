package fr.qwartz.mika.ui.carte

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.carte.Along
import fr.qwartz.mika.data.moi.carte.Place
import fr.qwartz.mika.data.moi.carte.Trip
import fr.qwartz.mika.data.moi.carte.TripRoute
import fr.qwartz.mika.data.moi.carte.TripsApi
import fr.qwartz.mika.data.moi.carte.WriteDone
import fr.qwartz.mika.data.moi.carte.movedTrip
import fr.qwartz.mika.data.moi.carte.removedTrip
import kotlinx.coroutines.CompletableDeferred
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient

/**
 * Une fausse API des voyages pour l'écran d'un voyage : un serveur en mémoire ([trip] : le voyage tel qu'il l'a), et des
 * barrières — un appel retenu ([hold]) ne répond que quand le test le lâche. Une lecture rend ce que le serveur avait au
 * moment de la demande ; une écriture s'applique quand elle répond.
 */
class FakeTripsApi(var trip: Trip) : TripsApi(MoiApi(OkHttpClient(), { null }, {})) {
    /** Les appels, dans l'ordre (« read », « move:A », « remove:B », « along:dormir », « route »). */
    val calls = mutableListOf<String>()
    /** Les lectures suivantes échouent ainsi (une panne : code 0). */
    var readFails: MoiError? = null
    /** Les écritures suivantes sont refusées ainsi (409 : la situation a changé). */
    var writeRefused: MoiError? = null
    var alongPlaces: List<Place> = emptyList()

    private val holds = HashMap<String, ArrayDeque<CompletableDeferred<Unit>>>()

    /** Retenir le prochain appel de ce nom (`read`, `move`, `remove`) : il répondra quand le test complétera la barrière. */
    fun hold(name: String): CompletableDeferred<Unit> =
        CompletableDeferred<Unit>().also { holds.getOrPut(name) { ArrayDeque() }.addLast(it) }

    private suspend fun gate(name: String) {
        holds[name]?.removeFirstOrNull()?.await()
    }

    val reads: Int get() = calls.count { it == "read" }

    override suspend fun read(id: String): MoiApi.Result<Trip> {
        calls += "read"
        val seen = trip
        val fails = readFails
        gate("read")
        return fails?.let { MoiApi.Result.Failed(it) } ?: MoiApi.Result.Ok(seen)
    }

    private suspend fun write(name: String, apply: () -> Unit): MoiApi.Result<WriteDone> {
        calls += name
        gate(name.substringBefore(':'))
        writeRefused?.let { return MoiApi.Result.Failed(it) }
        apply()
        return MoiApi.Result.Ok(WriteDone())
    }

    override suspend fun moveStop(id: String, stop: String, day: Int, index: Int, key: String): MoiApi.Result<WriteDone> =
        write("move:$stop") { trip = movedTrip(trip, stop, day, index) }

    override suspend fun removeStop(id: String, stop: String, key: String): MoiApi.Result<WriteDone> =
        write("remove:$stop") { trip = removedTrip(trip, stop) }

    override suspend fun route(id: String): MoiApi.Result<TripRoute> {
        calls += "route"
        return MoiApi.Result.Ok(TripRoute())
    }

    override suspend fun along(id: String, cat: String, day: Int, corridor: Int, limit: Int): MoiApi.Result<Along> {
        calls += "along:$cat"
        return MoiApi.Result.Ok(Along(alongPlaces))
    }

    override fun gpxUrl(id: String): HttpUrl = "http://192.168.1.22:8001/api/moi/voyages/$id/gpx".toHttpUrl()
}
