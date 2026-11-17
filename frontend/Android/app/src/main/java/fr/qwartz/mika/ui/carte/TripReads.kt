package fr.qwartz.mika.ui.carte

import androidx.compose.runtime.mutableStateMapOf
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.carte.Trip
import fr.qwartz.mika.ui.shell.Load
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.async

/**
 * Les voyages lus pour la session (la Carte les partage : la liste, un voyage ouvert, ses gestes), portés de
 * `frontendv2/src/shared/kit.ts::Cached` : un voyage se relit s'il a plus de [ttl] ms ; deux demandes pendant une lecture
 * n'en font qu'une ; **une relecture forcée demandée pendant une lecture en cours la suit** — elle a pu partir avant ce
 * qu'on vient d'écrire — par une seule relecture de plus, pour toutes les demandes forcées d'ici là. Une relecture qui
 * échoue garde ce qu'on avait lu (et le dit, [Read.error]), sauf un 404 : supprimé, pas à toi, il ne se montre plus.
 * Tout se fait dans [scope] (le fil principal d'un ViewModel).
 */
class TripReads(
    private val scope: CoroutineScope,
    private val fetch: suspend (String) -> MoiApi.Result<Trip>,
    private val now: () -> Long,
    private val ttl: Long = CarteStore.TRIP_TTL_MS,
) {
    /** Ce qu'une lecture a donné : ce qu'on montre désormais, et son refus s'il y en a eu un (lu avant : gardé). */
    data class Read(val load: Load<Trip>, val error: MoiError? = null)

    private val loads = mutableStateMapOf<String, Load<Trip>>()
    private val at = HashMap<String, Long>()
    private val running = HashMap<String, Deferred<Read>>()
    /** La relecture qui suivra la lecture en cours, pour les demandes forcées venues pendant elle. */
    private val again = HashMap<String, Deferred<Read>>()

    /** Un voyage tel qu'on l'a lu ; jamais demandé : `null`. */
    operator fun get(id: String): Load<Trip>? = loads[id]

    /** Le voyage, relu s'il a plus de [ttl] ms (ou [force]). */
    suspend fun load(id: String, force: Boolean = false): Read {
        val current = running[id]?.takeIf { it.isActive }
        if (current != null) {
            if (!force) return current.await()
            val next = again[id]?.takeIf { it.isActive } ?: scope.async {
                current.join()
                again.remove(id)
                load(id, force = true)
            }.also { again[id] = it }
            return next.await()
        }
        val known = loads[id]
        if (!force && known is Load.Ready && now() - (at[id] ?: 0) < ttl) return Read(known)
        val job = scope.async {
            if (loads[id] == null) loads[id] = Load.Loading
            val got = fetch(id)
            val before = loads[id]
            val read = when (got) {
                is MoiApi.Result.Ok -> Read(Load.Ready(got.value)).also { at[id] = now() }
                is MoiApi.Result.Failed -> Read(if (got.error.gone || before !is Load.Ready) Load.Failed(got.error) else before, got.error)
            }
            loads[id] = read.load
            read
        }
        running[id] = job
        return job.await()
    }

    /** La prochaine lecture repartira du serveur. */
    fun invalidate(id: String) {
        at.remove(id)
    }

    /** Supprimé : il ne se montre plus. */
    fun forget(id: String) {
        at.remove(id)
        loads.remove(id)
    }
}
