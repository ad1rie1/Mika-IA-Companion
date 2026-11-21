package fr.qwartz.mika.data.moi

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.Serializable

/** `GET /api/moi` (protocole § 2) : qui est connecté, et ce qui attend sa décision. */
@Serializable
data class Me(
    val username: String = "",
    val name: String = "",
    val handle: String = "",
    val person: String = "",
    val operator: Boolean = false,
    val owner: Boolean = false,
    val counts: Counts = Counts(),
) {
    /** Le nom à montrer : celui sous lequel elle la connaît, sinon l'identifiant. */
    val shown: String get() = name.ifBlank { username }
}

/**
 * Les pastilles du tiroir (ADR 0200) : ses brouillons de mail qui attendent, ses réponses Teams qui attendent, ses
 * réponses offertes au téléphone, ce qui t'attend dans tes projets (« À faire », ADR 0296).
 */
@Serializable
data class Counts(val mail: Int = 0, val teams: Int = 0, val phone: Int = 0, val projects: Int = 0)

/**
 * Ce que le serveur dit de la personne connectée, relu à l'ouverture, chaque minute tant que l'app est à l'écran
 * (la boucle est celle de l'écran racine), et après chaque geste qui peut changer une pastille ([refresh]).
 * Une lecture qui échoue garde la dernière connue ; une lecture partie avant [clear] ne repose rien après.
 */
class MeRepository(private val api: MoiApi, private val scope: CoroutineScope) {
    private val _me = MutableStateFlow<Me?>(null)
    val me: StateFlow<Me?> = _me.asStateFlow()
    private val lock = Mutex()
    /** Compte les sessions fermées : une lecture partie sous une autre génération ne pose rien. */
    private var generation = 0
    private val guard = Any()

    fun refresh() {
        scope.launch { load() }
    }

    suspend fun load(): MoiApi.Result<Me> = lock.withLock {
        val asked = synchronized(guard) { generation }
        val got = api.get("", reader = Me.serializer())
        // posé seulement si la session n'a pas été fermée pendant la lecture (sinon : le nom et les rôles de A chez B)
        if (got is MoiApi.Result.Ok) synchronized(guard) { if (generation == asked) _me.value = got.value }
        got
    }

    /** À la fermeture de la session : rien de la personne d'avant ne reste, ni ne revient d'une lecture en vol. */
    fun clear() {
        synchronized(guard) {
            generation++
            _me.value = null
        }
    }
}
