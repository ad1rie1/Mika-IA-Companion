package fr.qwartz.mika.ui.map

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.carte.MINI_RETRY_MS
import fr.qwartz.mika.data.moi.carte.MapNoteKind
import fr.qwartz.mika.data.moi.carte.MiniData
import fr.qwartz.mika.data.moi.carte.MiniPool
import fr.qwartz.mika.data.moi.carte.MiniRef
import fr.qwartz.mika.data.moi.carte.Regard
import fr.qwartz.mika.data.moi.carte.Trip
import fr.qwartz.mika.data.moi.carte.goneMini
import fr.qwartz.mika.data.moi.carte.miniWanted
import fr.qwartz.mika.data.moi.carte.regardMini
import fr.qwartz.mika.data.moi.carte.tripMini
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.async

/*
 * Les cartes miniatures d'une liste qui défile (la liste des voyages ; demain le fil du chat, lot 7), portées de
 * `frontend/Web/src/map/minis.ts` : chacune montre d'abord son plan dessiné ; quand elle paraît, ce qu'elle montre se lit
 * au serveur, puis une vraie carte, non interactive, prend sa place — **au plus quatre à la fois** ([MiniSlots]) : au-delà,
 * le plan reste. Une miniature qui sort de la vue rend sa place, qu'une autre visible reprend ; une qui reste au plan
 * (hors de la zone du fond, fond pas prêt, refusée, rien à montrer) n'en prend pas. Une miniature dont la carte ne se
 * dessine pas garde son plan, seule (son refus est le sien, gardé par sa liste).
 */

/**
 * Ce que montrent les miniatures (par `<sorte>:<ref>`), lu une fois à la fois pour la session. Ce qui a vieilli (un
 * voyage changé) se montre encore jusqu'à sa relecture ; une lecture partie avant le changement ne le rajeunit pas ;
 * une lecture qui a échoué ne se refait pas avant trente secondes ; plus là (404) : [goneMini].
 */
@Stable
class MiniStore(
    private val scope: CoroutineScope,
    private val fetchTrip: suspend (String) -> MoiApi.Result<Trip>,
    private val fetchRegard: suspend (String) -> MoiApi.Result<Regard>,
    private val now: () -> Long,
) {
    private class Entry(val data: MiniData, val stale: Boolean)

    private val entries = mutableStateMapOf<String, Entry>()
    private val loading = HashMap<String, Deferred<MiniData?>>()
    private val retryAt = HashMap<String, Long>()
    /** Combien de fois chaque note a vieilli : une miniature à l'écran se relit quand ce nombre change. */
    private val ages = mutableStateMapOf<String, Int>()

    /** Ce qu'on sait d'une note, même vieilli, sinon `null`. */
    fun peek(id: String): MiniData? = entries[id]?.data

    /** Lu, et pas vieilli depuis. */
    fun fresh(id: String): Boolean = entries[id]?.stale == false

    fun age(id: String): Int = ages[id] ?: 0

    /** Elle a changé : relue quand une de ses miniatures reparaît (ou de suite, si elle est à l'écran). */
    fun invalidate(id: String) {
        entries[id]?.let { entries[id] = Entry(it.data, stale = true) }
        ages[id] = age(id) + 1
        retryAt.remove(id)
    }

    /** Son dernier changement selon une liste ([version] : un voyage changé ailleurs) ; plus récent que ce qu'on a lu, il vieillit. */
    fun seen(id: String, version: Long?) {
        val entry = entries[id] ?: return
        val known = entry.data.version
        if (!entry.stale && version != null && known != null && version > known) invalidate(id)
    }

    /** Ce qu'elle montre : gardé, sinon lu (une fois à la fois, pour tous ceux qui attendent) ; `null` : lecture en échec. */
    suspend fun get(ref: MiniRef): MiniData? {
        val id = ref.id
        entries[id]?.takeIf { !it.stale }?.let { return it.data }
        if ((retryAt[id] ?: 0) > now()) return entries[id]?.data
        val running = loading[id]?.takeIf { it.isActive } ?: scope.async { load(ref) }.also { loading[id] = it }
        return running.await()
    }

    private suspend fun load(ref: MiniRef): MiniData? {
        val id = ref.id
        val start = age(id)
        val got: MiniData? = if (ref.kind == MapNoteKind.TRIP) {
            when (val r = fetchTrip(ref.ref)) {
                is MoiApi.Result.Ok -> tripMini(r.value)
                is MoiApi.Result.Failed -> if (r.error.gone) goneMini(ref) else null
            }
        } else {
            when (val r = fetchRegard(ref.ref)) {
                is MoiApi.Result.Ok -> regardMini(ref.ref, r.value)
                is MoiApi.Result.Failed -> if (r.error.gone) goneMini(ref) else null
            }
        }
        loading.remove(id)
        if (got == null) {
            retryAt[id] = now() + MINI_RETRY_MS
            return entries[id]?.data
        }
        // une lecture partie avant un changement ne le rajeunit pas
        entries[id] = Entry(got, stale = age(id) != start)
        return got
    }
}

/**
 * Les places des cartes vivantes d'une liste ([MiniPool]), de quoi réveiller celles qui attendent quand une se libère,
 * et ce qui ne s'est pas dessiné, miniature par miniature ([refusal] : gardé tant que la liste vit, même quand elle sort
 * de la vue et y revient).
 */
@Stable
class MiniSlots(max: Int = fr.qwartz.mika.data.moi.carte.MAX_LIVE_MINIS) {
    private val pool = MiniPool(max)
    private val refusals = HashMap<String, LiveRefusal>()
    var freed by mutableIntStateOf(0)
        private set

    fun take(key: String): Boolean = pool.take(key)

    fun give(key: String) {
        if (pool.has(key)) {
            pool.give(key)
            freed += 1
        }
    }

    /**
     * La place de cette miniature : prise si elle dessine une vraie carte ([wants], `miniWanted`) et qu'il en reste
     * une ; rendue sinon (une autre visible la reprend). Rend vrai si elle l'a.
     */
    fun hold(key: String, wants: Boolean): Boolean {
        if (wants) return take(key)
        give(key)
        return false
    }

    /** Ce qui ne s'est pas dessiné pour cette miniature (le sien, pas celui des autres). */
    fun refusal(key: String): LiveRefusal = refusals.getOrPut(key) { LiveRefusal() }
}

/**
 * Ce que montre une miniature : ce qu'on en sait (même vieilli), sinon [fallback] ; lu quand elle paraît, relu quand il
 * a changé ([version] : son dernier changement selon une liste).
 */
@Composable
fun rememberMini(store: MiniStore, ref: MiniRef, fallback: MiniData, version: Long? = null): MiniData {
    val id = ref.id
    val age = store.age(id)
    LaunchedEffect(id, version, age) {
        store.seen(id, version)
        if (!store.fresh(id)) store.get(ref)
    }
    return store.peek(id) ?: fallback
}

/**
 * Une carte miniature : la vraie carte, non interactive, quand le fond couvre tout ce qu'elle montre (`miniWanted`) et
 * qu'une place est libre ([slots], [key] : la sienne dans la liste) ; sinon son plan dessiné, sans note, et aucune place
 * prise. Rien n'y répond au doigt : la carte qui la porte l'ouvre.
 */
@Composable
fun MiniMap(graph: AppGraph, slots: MiniSlots, key: String, data: MiniData, modifier: Modifier = Modifier) {
    val fond = rememberMapFond(graph).fond
    val refusal = slots.refusal(key)
    val wants = miniWanted(fond, data.scene, refusal.failure(fond) != null)
    var granted by remember(key) { mutableStateOf(false) }
    LaunchedEffect(key, slots.freed, wants) {
        granted = slots.hold(key, wants)
    }
    DisposableEffect(key) {
        onDispose { slots.give(key) }
    }
    Box(modifier) {
        val plan: @Composable (String) -> Unit = { why -> ScenePlan(data.scene, data.title, why, Modifier.fillMaxSize(), note = false) }
        if (granted && wants) {
            SceneMap(graph, data.scene, data.title, Modifier.fillMaxSize(), interactive = false, nested = true, plan = plan, refusal = refusal)
        } else {
            plan("")
        }
    }
}
