package fr.qwartz.mika.data.net

import fr.qwartz.mika.core.Clock
import fr.qwartz.mika.core.Logger
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.coroutines.CoroutineContext
import kotlin.math.min

/**
 * La connexion à Mika — portage fidèle de `frontend/Web/src/network/WebSocketClient.ts` : reconnexion
 * avec attente croissante, battement applicatif (un socket mort reste souvent « ouvert » sans rien
 * dire), file d'envoi bornée qui survit aux coupures, accusés de réception comme seule preuve de
 * livraison, refus terminaux (4401, 1008) dits à voix haute.
 *
 * Ce qui change par rapport au navigateur : le jeton passe en en-tête (`Authorization: Bearer`, jamais
 * d'`Origin`), la présence aussi (`X-Mika-Presence`, puis des trames `presence`), chaque socket porte un
 * numéro de génération (un rappel d'une socket remplacée est ignoré), les trames lourdes sont écrites
 * hors du fil (fichiers relus du disque) et attendent que la file d'OkHttp ait de la place.
 *
 * Fil unique : toutes les méthodes publiques sont appelées depuis le contexte sérialisé de l'app
 * ([scope]) ; les rappels du transport y sont rapatriés par [post].
 */
class MikaSocket(
    private val transport: WsTransport,
    private val scope: CoroutineScope,
    private val clock: Clock,
    private val listener: Listener,
    /** Le plus haut identifiant serveur rendu : c'est l'app, pas le transport, qui sait ce qu'elle a. */
    private val cursor: () -> Long,
    /** Où écrire une trame de chat (lecture de fichiers). */
    private val io: CoroutineContext = Dispatchers.IO,
    private val post: (() -> Unit) -> Unit = { block -> scope.launch { block() } },
    private val logger: Logger = Logger.NONE,
) {
    interface Listener {
        /** Une trame du serveur, ou un accusé synthétique (refus constaté ici). Ne doit pas lever. */
        fun onFrame(frame: ServerFrame)
        fun onStatus(status: ConnectionStatus) {}
    }

    /** Les annonces du client web (`connection`), plus les deux refus et l'attente du réseau. */
    sealed interface ConnectionStatus {
        data object Connected : ConnectionStatus
        data class Disconnected(val retryInMs: Long) : ConnectionStatus
        data object Reconnecting : ConnectionStatus
        data object Unauthorized : ConnectionStatus
        data class Refused(val code: Int) : ConnectionStatus
        data object WaitingNetwork : ConnectionStatus
    }

    /** Où se connecter, et avec quoi. Le jeton n'apparaît jamais dans `toString`. */
    data class Endpoint(val url: String, val token: String, val userAgent: String) {
        override fun toString(): String = "Endpoint(url=$url, userAgent=$userAgent)"
    }

    /**
     * Un message à envoyer. La trame n'est écrite qu'au moment de partir ([render], sur [io]) : une file
     * de vingt messages avec photos ne garde pas vingt fois leurs octets en mémoire.
     */
    class OutboundChat(val clientMsgId: String, val frameBytes: Long, val render: () -> String)

    private class Entry(val chat: OutboundChat) {
        var attempts = 0
        val bytes: Long get() = chat.frameBytes
    }

    private val _state = MutableStateFlow<LinkState>(LinkState.Idle)
    val state: StateFlow<LinkState> = _state.asStateFlow()

    private var endpoint: Endpoint? = null
    private var wanted = false
    /** Refus terminal : réessayer ne peut pas changer la réponse, la session doit changer. */
    private var stopped = false
    private var terminalState: LinkState? = null
    private var terminalAck = MikaProtocol.ACK_UNAUTHORIZED
    private var networkAvailable = true

    /** Devant l'écran (voulu), annoncé par l'en-tête de la socket en cours, puis su du serveur. */
    private var here = false
    private var headerHere = false
    private var announcedHere = false

    private var socket: WsSocket? = null
    private var generation = 0
    private var open = false
    private var lastFrameAt = 0L
    /** Le dernier regard qui a trouvé des octets à monter dans la file d'OkHttp ([lastSignOfLife]). */
    private var uploadSeenAt = 0L
    private var currentDelay = MikaProtocol.RECONNECT_DELAY_MS.toDouble()

    private var reconnectJob: Job? = null
    private var heartbeatJob: Job? = null
    private var judgeJob: Job? = null
    private var flushJob: Job? = null

    // Ce qui attend une socket ouverte, et ce qui est parti sans accusé : bornés en nombre et en octets.
    private val outbox = ArrayDeque<Entry>()
    private var outboxBytes = 0L
    private val unacked = LinkedHashMap<String, Entry>()
    private var unackedBytes = 0L

    val isTerminal: Boolean get() = stopped

    // ── Pilotage ─────────────────────────────────────────────────────────────────────────

    /** Vouloir la connexion. Idempotent pour un même point d'arrivée, même après un refus terminal. */
    fun start(endpoint: Endpoint) {
        if (wanted && endpoint == this.endpoint) return
        if (endpoint != this.endpoint) {
            teardown(graceful = true)
            this.endpoint = endpoint
            stopped = false
            terminalState = null
            currentDelay = MikaProtocol.RECONNECT_DELAY_MS.toDouble()
        }
        wanted = true
        if (stopped) {
            terminalState?.let(::setState)
            return
        }
        if (socket == null && reconnectJob == null) connect()
    }

    /** Ne plus vouloir la connexion : la file d'envoi est gardée pour la prochaine. */
    fun stop() {
        if (!wanted) return
        if (open) sendNow(FrameCodec.presence(false))
        wanted = false
        teardown(graceful = true)
        if (!stopped) setState(LinkState.Idle)
    }

    /** Déconnexion de la session : tout est oublié, rien n'est annoncé. */
    fun reset() {
        wanted = false
        // Oublié avant la fermeture : rien n'est remis en file, donc rien n'est refusé à voix haute.
        outbox.clear()
        outboxBytes = 0
        unacked.clear()
        unackedBytes = 0
        teardown(graceful = true)
        endpoint = null
        stopped = false
        terminalState = null
        setState(LinkState.Idle)
    }

    /** Après un refus terminal levé (session vérifiée, « Réessayer ») : repartir tout de suite. */
    fun retry() {
        if (!wanted) return
        stopped = false
        terminalState = null
        reconnectNow()
    }

    /** Devant l'écran ou non : annoncé tout de suite si la socket est ouverte, jamais mis en file. */
    fun setPresence(here: Boolean) {
        if (this.here == here) return
        this.here = here
        if (open) sendPresence()
    }

    /**
     * Le retour au premier plan : reconnecter tout de suite si la socket n'est pas manifestement
     * utilisable. Silencieuse avec un message sans accusé : c'est un cadavre. Silencieuse sans rien en
     * vol : rien n'est prouvé, on pingue et le battement jugera. Le silence se compte comme au battement :
     * une trame encore en montée n'en est pas un ([lastSignOfLife]).
     */
    fun ensureAlive() {
        if (stopped || !wanted) return
        val s = socket
        if (s != null && open) {
            val now = clock.elapsedMs()
            if (unacked.isNotEmpty() && now - lastSignOfLife(s, now) > MikaProtocol.HEARTBEAT_TIMEOUT_MS) {
                logger.w(TAG, "silencieuse avec un message en vol — reconnexion")
                reconnectNow()
                return
            }
            if (!ping()) reconnectNow()
            return
        }
        if (s != null) return // en cours d'ouverture : on ne la remplace pas
        reconnectNow()
    }

    /** Ce que le moniteur de réseau sait au démarrage : enregistré, rien n'est relancé. */
    fun setNetworkAvailable(available: Boolean) {
        networkAvailable = available
    }

    /** Le réseau par défaut a changé (ou est revenu) : la socket d'avant est à abandonner. */
    fun onNetworkChanged(available: Boolean) {
        networkAvailable = available
        if (stopped || !wanted) return
        if (!available) {
            if (socket == null) setState(LinkState.NoNetwork)
            return
        }
        reconnectNow()
    }

    /** Demander au serveur tout ce qui suit le curseur, maintenant. */
    fun requestSync() {
        sendNow(FrameCodec.sync(cursor()))
    }

    /**
     * Décider d'une carte d'accord : une trame de contrôle, partie maintenant ou pas du tout — jamais
     * en file (un accord rejoué après une coupure vaudrait pour une carte qui a pu changer). `false` :
     * la socket n'est pas ouverte, rien n'est parti.
     */
    fun sendApproval(id: Long, decision: ApprovalDecision, digest: String): Boolean =
        sendNow(FrameCodec.approval(id, decision, digest))

    /**
     * Envoyer un message. `true` : la socket est ouverte, il part maintenant ; `false` : il attend
     * une connexion, ou il est refusé (un accusé synthétique le dit).
     */
    fun offer(chat: OutboundChat): Boolean {
        // Une trame que le transport refusera ne se met pas en file : chaque rejeu refermerait la socket.
        if (chat.frameBytes > MikaProtocol.MAX_FRAME_BYTES) {
            refuse(chat.clientMsgId, MikaProtocol.ACK_FRAME_TOO_LARGE)
            return false
        }
        // Après un refus terminal il n'y aura pas de prochaine ouverture : refusé à voix haute.
        if (stopped) {
            refuse(chat.clientMsgId, terminalAck)
            return false
        }
        enqueue(Entry(chat))
        if (!open) return false
        flushOutbox()
        return true
    }

    // ── Ouverture et fermeture ───────────────────────────────────────────────────────────

    private fun connect() {
        if (stopped || !wanted) return
        val ep = endpoint ?: return
        if (!networkAvailable) {
            setState(LinkState.NoNetwork)
            emit(ConnectionStatus.WaitingNetwork)
            return
        }
        val gen = ++generation
        open = false
        headerHere = here
        announcedHere = here
        val headers = linkedMapOf(
            MikaProtocol.HEADER_AUTHORIZATION to "Bearer ${ep.token}",
            MikaProtocol.HEADER_PRESENCE to if (here) MikaProtocol.PRESENCE_HERE else MikaProtocol.PRESENCE_AWAY,
            MikaProtocol.HEADER_USER_AGENT to ep.userAgent,
        )
        setState(LinkState.Connecting)
        socket = try {
            transport.open(ep.url, headers, Events(gen))
        } catch (e: Exception) {
            logger.w(TAG, "ouverture impossible : ${e.javaClass.simpleName}", e)
            null
        }
        if (socket == null) scheduleReconnect()
    }

    private inner class Events(private val gen: Int) : WsListener {
        override fun onOpen() = post { if (live(gen)) handleOpen() }
        override fun onMessage(text: String) = post { if (live(gen)) handleMessage(text) }
        override fun onClosed(code: Int, reason: String) = post { if (live(gen)) handleGone(code, null) }
        override fun onFailure(error: Throwable, httpCode: Int?) = post {
            if (live(gen)) {
                logger.w(TAG, "échec de la socket (HTTP ${httpCode ?: "-"}) : ${error.javaClass.simpleName}")
                handleGone(null, httpCode)
            }
        }
    }

    /** Un rappel ne compte que pour la socket en cours : une socket remplacée est détachée. */
    private fun live(gen: Int) = gen == generation && socket != null

    private fun handleOpen() {
        currentDelay = MikaProtocol.RECONNECT_DELAY_MS.toDouble()
        lastFrameAt = clock.elapsedMs()
        open = true
        setState(LinkState.Online)
        // Le trou d'abord, la file ensuite : un message rejoué avant le `sync` reviendrait dans le même
        // rattrapage. Une connexion « absente » ne reçoit pas le fil initial : elle demande toujours.
        if (!headerHere || cursor() > 0) requestSync()
        flushOutbox()
        startHeartbeat()
        emit(ConnectionStatus.Connected)
        if (here != announcedHere) sendPresence()
    }

    private fun handleMessage(text: String) {
        // N'importe quelle trame prouve la vie, même illisible.
        lastFrameAt = clock.elapsedMs()
        val frame = FrameCodec.decode(text) ?: return
        // Le reçu : purgé avant les abonnés, pour qu'un abonné qui lève ne fasse jamais renvoyer.
        if (frame is ServerFrame.Ack && frame.clientMsgId.isNotEmpty()) forgetUnacked(frame.clientMsgId)
        deliver(frame)
    }

    private fun handleGone(closeCode: Int?, httpCode: Int?) {
        stopHeartbeat()
        flushJob?.cancel()
        flushJob = null
        socket = null
        open = false
        val terminal: LinkState? = when {
            closeCode == MikaProtocol.CLOSE_UNAUTHORIZED || httpCode == 401 -> LinkState.SessionExpired
            closeCode == MikaProtocol.CLOSE_POLICY || httpCode == 403 ->
                LinkState.Refused(closeCode ?: httpCode ?: MikaProtocol.CLOSE_POLICY)
            else -> null
        }
        if (terminal != null) {
            // Une fermeture que le serveur refera à chaque essai n'est pas une coupure : réessayer
            // donnerait une boucle muette. Rien de ce qui attend ne partira : refusé à voix haute.
            stopped = true
            terminalState = terminal
            reconnectJob?.cancel()
            reconnectJob = null
            terminalAck = if (terminal is LinkState.SessionExpired) {
                MikaProtocol.ACK_UNAUTHORIZED
            } else {
                MikaProtocol.ACK_CONNECTION_REFUSED
            }
            refuseAll(terminalAck)
            setState(terminal)
            emit(if (terminal is LinkState.Refused) ConnectionStatus.Refused(terminal.code) else ConnectionStatus.Unauthorized)
            return
        }
        // Armer la relance AVANT de prévenir : elle ne dépend d'aucun abonné.
        scheduleReconnect()
        requeueUnacked()
        emit(ConnectionStatus.Disconnected(currentDelay.toLong()))
    }

    private fun scheduleReconnect() {
        if (stopped || reconnectJob != null) return
        val wait = currentDelay.toLong()
        setState(LinkState.Offline(clock.elapsedMs() + wait))
        reconnectJob = scope.launch {
            delay(wait)
            reconnectJob = null
            if (!networkAvailable) {
                // Pas de réseau : aucun essai dépensé, on attend son retour (onNetworkChanged).
                setState(LinkState.NoNetwork)
                emit(ConnectionStatus.WaitingNetwork)
                return@launch
            }
            currentDelay = min(currentDelay * MikaProtocol.RECONNECT_FACTOR, MikaProtocol.MAX_RECONNECT_DELAY_MS.toDouble())
            // Rouvrir d'abord, annoncer ensuite.
            connect()
            emit(ConnectionStatus.Reconnecting)
        }
    }

    /** Abattre la socket et repartir sans attendre la fin de l'attente en cours. */
    private fun reconnectNow() {
        if (stopped || !wanted) return
        reconnectJob?.cancel()
        reconnectJob = null
        stopHeartbeat()
        flushJob?.cancel()
        flushJob = null
        // Ce que cette socket a peut-être avalé ne se rattrape que sur la suivante.
        requeueUnacked()
        val dying = socket
        socket = null
        open = false
        generation++ // détachée : son `close` ne relancera rien
        if (dying != null) {
            try {
                dying.cancel()
            } catch (_: Exception) {
                // déjà fermée : rien à sauver
            }
        }
        currentDelay = MikaProtocol.RECONNECT_DELAY_MS.toDouble()
        connect()
        emit(ConnectionStatus.Reconnecting)
    }

    private fun teardown(graceful: Boolean) {
        reconnectJob?.cancel()
        reconnectJob = null
        stopHeartbeat()
        flushJob?.cancel()
        flushJob = null
        requeueUnacked()
        val s = socket
        socket = null
        open = false
        generation++
        if (s != null) {
            try {
                if (graceful) s.close(MikaProtocol.CLOSE_NORMAL, null) else s.cancel()
            } catch (_: Exception) {
                // déjà fermée
            }
        }
    }

    // ── Battement ────────────────────────────────────────────────────────────────────────
    //
    // Une socket tuée par un téléphone endormi ou un mandataire qui ferme les connexions inactives
    // ne prévient souvent pas : elle reste « ouverte » et avale tout. Seules des trames applicatives
    // échangées le prouvent.

    private fun startHeartbeat() {
        stopHeartbeat()
        val gen = generation
        // L'échéance part d'ici, pas du premier passage de la coroutine (qui peut venir plus tard).
        var expected = clock.elapsedMs() + MikaProtocol.HEARTBEAT_INTERVAL_MS
        heartbeatJob = scope.launch {
            while (true) {
                delay(MikaProtocol.HEARTBEAT_INTERVAL_MS)
                val now = clock.elapsedMs()
                val late = now - expected
                expected = now + MikaProtocol.HEARTBEAT_INTERVAL_MS
                if (gen != generation || !open) continue
                if (late > MikaProtocol.LATE_TICK_MS) {
                    // Le processeur dormait : le silence mesuré ne prouve rien. Pinguer, juger après.
                    pingThenJudge()
                    continue
                }
                val s = socket ?: continue
                if (now - lastSignOfLife(s, now) > MikaProtocol.HEARTBEAT_TIMEOUT_MS) {
                    logger.w(TAG, "silencieuse au-delà du délai — reconnexion")
                    reconnectNow()
                    return@launch
                }
                if (!ping()) {
                    reconnectNow()
                    return@launch
                }
            }
        }
    }

    private fun pingThenJudge() {
        val pingAt = clock.elapsedMs()
        // Regardée avant le ping : ses propres octets ne sont pas une montée.
        socket?.let { lastSignOfLife(it, pingAt) }
        if (!ping()) {
            reconnectNow()
            return
        }
        judgeJob?.cancel()
        val gen = generation
        judgeJob = scope.launch {
            delay(MikaProtocol.LATE_TICK_JUDGE_MS)
            judgeJob = null
            val s = socket
            if (gen == generation && open && s != null && lastSignOfLife(s, clock.elapsedMs()) < pingAt) reconnectNow()
        }
    }

    /**
     * Le dernier signe de vie de la socket : une trame reçue, ou une montée encore en cours. Un `pong` ne
     * double pas une trame qui monte — OkHttp écrit un message d'un seul tenant et ne le retire de sa file
     * qu'une fois parti en entier. Tant que cette file porte des octets, le silence ne prouve donc rien
     * (une montée vraiment bloquée, c'est le délai d'écriture d'OkHttp qui la ferme) : il ne se compte
     * qu'à partir du dernier regard qui y a trouvé des octets.
     */
    private fun lastSignOfLife(s: WsSocket, now: Long): Long {
        if (s.queueSize() > 0) uploadSeenAt = now
        return maxOf(lastFrameAt, uploadSeenAt)
    }

    private fun stopHeartbeat() {
        heartbeatJob?.cancel()
        heartbeatJob = null
        judgeJob?.cancel()
        judgeJob = null
    }

    private fun ping(): Boolean = sendNow(FrameCodec.ping(clock.wallMs()))

    private fun sendPresence() {
        if (sendNow(FrameCodec.presence(here))) announcedHere = here
    }

    /**
     * Envoyer si la socket est ouverte, sinon rien — jamais en file. Pour les trames de contrôle
     * (`sync`, `ping`, `presence`, `approval`) dont toute la valeur est d'être actuelles.
     */
    private fun sendNow(text: String): Boolean {
        val s = socket ?: return false
        if (!open) return false
        return try {
            s.send(text)
        } catch (_: Exception) {
            false
        }
    }

    // ── File d'envoi et accusés ──────────────────────────────────────────────────────────

    private fun flushOutbox() {
        if (outbox.isEmpty() || flushJob?.isActive == true) return
        val gen = generation
        flushJob = scope.launch(start = CoroutineStart.UNDISPATCHED) { drain(gen) }
    }

    private suspend fun drain(gen: Int) {
        while (gen == generation) {
            val entry = outbox.firstOrNull() ?: return
            val sock = socket
            if (sock == null || !open) {
                keepForNextOpen()
                return
            }
            val text = try {
                withContext(io) { entry.chat.render() }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                logger.w(TAG, "trame impossible à écrire : ${e.javaClass.simpleName}", e)
                if (outbox.firstOrNull() === entry) {
                    outbox.removeFirst()
                    outboxBytes -= entry.bytes
                }
                refuse(entry.chat.clientMsgId, MikaProtocol.ACK_FILES_MISSING)
                continue
            }
            if (gen != generation || outbox.firstOrNull() !== entry) continue
            // OkHttp ferme la socket quand sa file dépasse 16 Mio : attendre qu'elle se vide assez.
            while (gen == generation && open &&
                sock.queueSize() > 0 && sock.queueSize() + entry.bytes > MikaProtocol.MAX_FRAME_BYTES
            ) {
                delay(MikaProtocol.QUEUE_POLL_MS)
            }
            if (gen != generation || outbox.firstOrNull() !== entry) continue
            if (!open) {
                keepForNextOpen()
                return
            }
            outbox.removeFirst()
            outboxBytes -= entry.bytes
            if (sock.send(text)) {
                holdUntilAck(entry)
            } else {
                // Morte entre-temps : ce qui reste attend la prochaine ouverture.
                outbox.addFirst(entry)
                outboxBytes += entry.bytes
                keepForNextOpen()
                return
            }
        }
    }

    /**
     * La socket est morte au moment de vider la file : on garde tout pour la prochaine ouverture,
     * mais pas éternellement — au-delà de [MikaProtocol.MAX_OUTBOX_ATTEMPTS] réouvertures sans
     * partir, un message ne partira plus, et le garder laisserait sa bulle « en attente » sans issue.
     */
    private fun keepForNextOpen() {
        val pending = outbox.toList()
        outbox.clear()
        outboxBytes = 0
        for (entry in pending) {
            entry.attempts += 1
            if (entry.attempts > MikaProtocol.MAX_OUTBOX_ATTEMPTS) {
                refuse(entry.chat.clientMsgId, MikaProtocol.ACK_SEND_ABANDONED)
                continue
            }
            outbox.addLast(entry)
            outboxBytes += entry.bytes
        }
    }

    /** Mettre en file sous les deux bornes ; l'évincé (le plus ancien) est refusé à voix haute. */
    private fun enqueue(entry: Entry) {
        val evict = OutboxPolicy.evictions(outbox.map { it.bytes }, entry.bytes)
        repeat(evict) {
            val evicted = outbox.removeFirst()
            outboxBytes -= evicted.bytes
            refuse(evicted.chat.clientMsgId, MikaProtocol.ACK_SEND_ABANDONED)
        }
        outbox.addLast(entry)
        outboxBytes += entry.bytes
    }

    /**
     * Garder un message parti jusqu'à son accusé. Borné comme la file ; une éviction ici n'est pas un
     * refus — le message est parti, un accusé peut encore venir — on renonce seulement à le rejouer.
     */
    private fun holdUntilAck(entry: Entry) {
        val cid = entry.chat.clientMsgId
        forgetUnacked(cid)
        val evict = OutboxPolicy.evictions(unacked.values.map { it.bytes }, entry.bytes)
        repeat(evict) { forgetUnacked(unacked.keys.first()) }
        unacked[cid] = entry
        unackedBytes += entry.bytes
    }

    private fun forgetUnacked(cid: String) {
        val entry = unacked.remove(cid) ?: return
        unackedBytes -= entry.bytes
    }

    /**
     * Remettre en tête ce qui est parti sans accusé, devant ce qui a été tapé depuis. Un message reçu
     * dont l'accusé est mort avec la socket reviendra deux fois : un doublon se voit, une question
     * disparue non. Chaque retour compte une tentative, comme dans [keepForNextOpen] : une trame que
     * chaque socket emporte avec elle sans accusé ne partira pas, et la renvoyer sans fin la laisserait
     * « en attente » en remontant ses octets à chaque fois.
     */
    private fun requeueUnacked() {
        if (unacked.isEmpty()) return
        val pending = unacked.values.toList()
        unacked.clear()
        unackedBytes = 0
        val queued = outbox.toList()
        outbox.clear()
        outboxBytes = 0
        for (entry in pending) {
            entry.attempts += 1
            if (entry.attempts > MikaProtocol.MAX_OUTBOX_ATTEMPTS) {
                refuse(entry.chat.clientMsgId, MikaProtocol.ACK_SEND_ABANDONED)
                continue
            }
            enqueue(entry)
        }
        for (entry in queued) enqueue(entry)
    }

    private fun refuseAll(status: String) {
        val doomed = unacked.values.toList() + outbox.toList()
        unacked.clear()
        unackedBytes = 0
        outbox.clear()
        outboxBytes = 0
        for (entry in doomed) refuse(entry.chat.clientMsgId, status)
    }

    /** Un refus passe par le même accusé que ceux du serveur : c'est ce que le fil écoute déjà. */
    private fun refuse(clientMsgId: String, status: String) {
        if (clientMsgId.isEmpty()) return
        deliver(ServerFrame.Ack(clientMsgId = clientMsgId, status = status))
    }

    // ── Diffusion : ne lève jamais ───────────────────────────────────────────────────────

    private fun deliver(frame: ServerFrame) {
        try {
            listener.onFrame(frame)
        } catch (e: Exception) {
            logger.e(TAG, "un abonné a levé sur ${frame.javaClass.simpleName}", e)
        }
    }

    private fun emit(status: ConnectionStatus) {
        try {
            listener.onStatus(status)
        } catch (e: Exception) {
            logger.e(TAG, "un abonné a levé sur $status", e)
        }
    }

    private fun setState(state: LinkState) {
        _state.value = state
    }

    /** Pour les tests : les minuteries encore armées (attente, battement, jugement). */
    internal fun activeTimers(): Int =
        listOfNotNull(reconnectJob, heartbeatJob, judgeJob).count { it.isActive }

    private companion object {
        const val TAG = "MikaSocket"
    }
}
