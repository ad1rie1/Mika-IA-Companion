package fr.qwartz.mika.data.phone

import fr.qwartz.mika.core.Clock
import fr.qwartz.mika.core.Logger
import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.db.Kv
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** Les petites valeurs du téléphone (la table `kv`), vues d'ici : de quoi les remplacer dans les tests. */
interface PhoneKv {
    suspend fun get(key: String): String?
    suspend fun put(key: String, value: String?)
}

/** Où en est l'envoi des messages lus, pour les réglages (ADR 0120). */
data class PhoneStatus(
    /** Les messages qui attendent (en 4G : le Wi-Fi de la maison). */
    val queued: Int = 0,
    /** Le serveur a refusé (403) : pas propriétaire, ou la lecture coupée côté serveur. */
    val refused: Boolean = false,
    /** Le serveur ne connaît pas la porte (404) : il est plus ancien que l'app. */
    val outdated: Boolean = false,
    /** Le dernier lot accepté (heure murale) ; 0 : jamais. */
    val sentAt: Long = 0,
)

/**
 * La file des messages lus sur le téléphone et de leur envoi (ADR 0120) : persistée (table `kv`), bornée, et envoyée
 * par lots — un appel HTTP, une réponse, rien ne reste ouvert ni ne boucle (ADR 0077).
 *
 * En 4G le serveur de la maison est injoignable : après un échec de réseau (ou un serveur qui demande d'attendre), on
 * ne réessaie pas avant [RETRY_MS] sur un simple message neuf ; le retour du réseau, la connexion du lecteur de
 * notifications et l'app qui passe au premier plan réessaient tout de suite ([Trigger.forced]).
 *
 * Les réponses de la porte : 200, le lot quitte la file ; 401, la session est morte (rien : la connexion la constatera) ;
 * 403, le serveur refuse — la file se vide, l'état « refusé » se voit dans les réglages, et ce qui arrive dans l'heure
 * n'est pas gardé ; 400/413, le lot est écarté ; 404, le serveur ne connaît pas la porte ; le reste (429, 503…), on
 * garde, et on attend son `Retry-After` s'il en donne un.
 */
class PhoneOutbox(
    private val kv: PhoneKv,
    private val api: PhoneApi,
    private val credentials: () -> Credentials?,
    /** L'interrupteur « Lui montrer mes messages » : coupé, rien ne part et la file se vide. */
    private val enabled: suspend () -> Boolean,
    /** Un réseau existe : sans lui, on n'essaie même pas. */
    private val online: () -> Boolean,
    private val clock: Clock,
    private val scope: CoroutineScope,
    private val logger: Logger = Logger.NONE,
) {
    /** Ce qui demande un envoi ; [forced] : passe outre l'attente d'après un échec. */
    enum class Trigger(val forced: Boolean) {
        /** Un message neuf, un sort de proposition. */
        MESSAGE(false),
        NETWORK(true),
        LISTENER(true),
        FOREGROUND(true),
    }

    /** L'état (la ligne `kv`) : relu à chaque fois, jamais gardé en mémoire — une déconnexion l'efface sous nos pieds. */
    private val lock = Mutex()
    /** Un envoi à la fois : deux lots ne partent pas en même temps. */
    private val sending = Mutex()

    /** Pas d'essai sur un simple message avant cet instant (`elapsedMs`) ; 0 : quand on veut. */
    @Volatile private var retryAt = 0L
    @Volatile private var outdated = false
    private var soon: Job? = null

    private val _status = MutableStateFlow(PhoneStatus())
    val status: StateFlow<PhoneStatus> = _status.asStateFlow()

    /** Au démarrage : l'état gardé, pour les réglages. */
    suspend fun init() = lock.withLock { publish(load()) }

    /** Des messages lus : au bout de la file (neufs seulement). Le nombre ajouté ; 0 : coupé, refusé, ou rien de neuf. */
    suspend fun add(messages: List<PhoneMessage>): Int {
        if (messages.isEmpty() || !enabled()) return 0
        return lock.withLock {
            val state = load()
            if (refusing(state)) return@withLock 0
            val r = PhoneQueue.add(state, messages)
            if (r.added > 0) save(r.state)
            r.added
        }
    }

    /** Le sort d'une proposition (ADR 0120) : il part avec les messages. */
    suspend fun settle(id: Long, result: Settlement, reason: SettleReason = SettleReason.NONE) {
        if (!enabled()) return
        lock.withLock { save(PhoneQueue.settle(load(), PhoneSettled(id, result.wire, reason.wire))) }
    }

    /**
     * Un envoi bientôt, pour un message neuf : les messages d'une rafale (une notification mise à jour plusieurs fois
     * de suite) partent ensemble.
     */
    fun flushSoon() {
        synchronized(this) {
            if (soon?.isActive == true) return
            soon = scope.launch {
                delay(COALESCE_MS)
                flush(Trigger.MESSAGE)
            }
        }
    }

    /** Envoyer ce qui attend, si c'est le moment : les messages, puis le sort des propositions. */
    suspend fun flush(trigger: Trigger) = sending.withLock {
        if (!enabled()) {
            if (lock.withLock { load() != EMPTY }) clear()
            return@withLock
        }
        if (!trigger.forced && clock.elapsedMs() < retryAt) return@withLock
        if (!online()) return@withLock
        val c = credentials() ?: return@withLock
        if (sendMessages(c)) sendSettled(c)
    }

    /** L'interrupteur coupé, la déconnexion : plus rien n'attend, et le refus est oublié. */
    suspend fun clear() = lock.withLock {
        retryAt = 0
        outdated = false
        save(PhoneQueueState())
    }

    /** `false` : on s'arrête là (refus, réseau, serveur qui demande d'attendre). */
    private suspend fun sendMessages(c: Credentials): Boolean {
        while (true) {
            val batch = lock.withLock { PhoneQueue.batch(load()) }
            if (batch.isEmpty()) return true
            val ids = batch.mapTo(HashSet()) { it.id }
            when (val r = api.inbox(c.base, c.token, batch)) {
                is PhoneApi.Result.Ok -> {
                    if (r.value.dropped > 0) logger.w(TAG, "${r.value.dropped} message(s) écarté(s) par le serveur")
                    accepted { PhoneQueue.without(it, ids) }
                }
                is PhoneApi.Result.Http -> if (!onHttpError(r, "messages") { PhoneQueue.without(it, ids) }) return false
                is PhoneApi.Result.Network -> {
                    backOff(null)
                    return false
                }
            }
        }
    }

    private suspend fun sendSettled(c: Credentials) {
        while (true) {
            val batch = lock.withLock { PhoneQueue.settledBatch(load()) }
            if (batch.isEmpty()) return
            when (val r = api.settled(c.base, c.token, batch)) {
                is PhoneApi.Result.Ok -> {
                    if (r.value.unknown > 0) logger.i(TAG, "${r.value.unknown} proposition(s) inconnue(s) du serveur (expirées)")
                    accepted { PhoneQueue.withoutSettled(it, batch) }
                }
                is PhoneApi.Result.Http -> if (!onHttpError(r, "sorts") { PhoneQueue.withoutSettled(it, batch) }) return
                is PhoneApi.Result.Network -> {
                    backOff(null)
                    return
                }
            }
        }
    }

    private suspend fun accepted(drop: (PhoneQueueState) -> PhoneQueueState) {
        retryAt = 0
        outdated = false
        lock.withLock { save(drop(load()).copy(refusedAt = 0, sentAt = clock.wallMs())) }
    }

    /** Une réponse autre que 2xx : `true` si le lot est écarté et qu'on passe au suivant. */
    private suspend fun onHttpError(r: PhoneApi.Result.Http, what: String, drop: (PhoneQueueState) -> PhoneQueueState): Boolean =
        when (r.code) {
            403 -> {
                logger.w(TAG, "le serveur refuse les $what (403) : file vidée")
                lock.withLock { save(load().copy(messages = emptyList(), settled = emptyList(), refusedAt = clock.wallMs())) }
                false
            }
            401 -> {
                // La session est morte : la prochaine connexion le constatera (et effacera tout). D'ici là, rien.
                backOff(null)
                false
            }
            400, 413, 422 -> {
                logger.w(TAG, "lot de $what écarté par le serveur (HTTP ${r.code}) : ${r.error.orEmpty()}")
                lock.withLock { save(drop(load())) }
                true
            }
            404 -> {
                logger.w(TAG, "ce serveur ne connaît pas la porte du téléphone (404)")
                outdated = true
                lock.withLock { publish(load()) }
                backOff(null)
                false
            }
            else -> {
                backOff(r.retryAfter)
                false
            }
        }

    /**
     * Plus d'essai sur un simple message avant [RETRY_MS] — ou avant le `Retry-After` du serveur quand il en donne un
     * (un serveur qui démarre, une rafale), borné entre [RETRY_MIN_MS] et [RETRY_MAX_MS]. Aucun minuteur : c'est le
     * message suivant, le réseau ou l'ouverture de l'app qui réessaient.
     */
    private fun backOff(retryAfter: String?) {
        val asked = retryAfter?.trim()?.toLongOrNull()?.takeIf { it > 0 }?.let { (it * 1_000).coerceIn(RETRY_MIN_MS, RETRY_MAX_MS) }
        retryAt = clock.elapsedMs() + (asked ?: RETRY_MS)
    }

    private fun refusing(state: PhoneQueueState): Boolean =
        state.refusedAt > 0 && clock.wallMs() - state.refusedAt in 0 until REFUSED_HOLD_MS

    private suspend fun load(): PhoneQueueState = try {
        kv.get(Kv.PHONE_QUEUE)?.let { MikaJson.decodeFromString(PhoneQueueState.serializer(), it) } ?: PhoneQueueState()
    } catch (_: IllegalArgumentException) {
        PhoneQueueState()
    }

    private suspend fun save(state: PhoneQueueState) {
        kv.put(Kv.PHONE_QUEUE, if (state == EMPTY) null else MikaJson.encodeToString(PhoneQueueState.serializer(), state))
        publish(state)
    }

    private fun publish(state: PhoneQueueState) {
        _status.value = PhoneStatus(state.messages.size, state.refusedAt > 0, outdated, state.sentAt)
    }

    companion object {
        private const val TAG = "Phone"
        private val EMPTY = PhoneQueueState()

        /** Les messages d'une rafale partent ensemble. */
        const val COALESCE_MS = 2_000L

        /** Après un échec de réseau, pas d'essai avant 10 min sur un simple message (en 4G, rien ne répond). */
        const val RETRY_MS = 10L * 60 * 1000
        const val RETRY_MIN_MS = 30_000L
        const val RETRY_MAX_MS = 60L * 60 * 1000

        /** Refusé par le serveur : ce qui arrive dans l'heure n'est pas gardé ; après, on retente. */
        const val REFUSED_HOLD_MS = 60L * 60 * 1000
    }
}
