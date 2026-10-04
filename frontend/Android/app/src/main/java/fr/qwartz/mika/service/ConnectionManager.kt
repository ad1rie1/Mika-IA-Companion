package fr.qwartz.mika.service

import fr.qwartz.mika.core.Clock
import fr.qwartz.mika.core.Logger
import fr.qwartz.mika.core.NetworkStatus
import fr.qwartz.mika.data.approvals.ApprovalsRepository
import fr.qwartz.mika.data.auth.AuthRepository
import fr.qwartz.mika.data.auth.Session
import fr.qwartz.mika.data.chat.ChatEngine
import fr.qwartz.mika.data.mind.MindStateRepository
import fr.qwartz.mika.data.net.ApprovalDecision
import fr.qwartz.mika.data.net.LinkState
import fr.qwartz.mika.data.net.MikaSocket
import fr.qwartz.mika.data.net.ServerFrame
import fr.qwartz.mika.data.net.WsTransport
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/**
 * Qui veut la connexion, et ce qu'elle porte. La socket est voulue quand une session existe et qu'un
 * détenteur la demande : l'écran ([Holder.UI], gardé 30 s après le départ au second plan), le service
 * en arrière-plan ([Holder.SERVICE]), ou une réponse partie d'une notification ([Holder.REPLY]).
 *
 * La présence suit le premier plan : en-tête à la connexion, puis trame `presence` à chaque passage —
 * une app qui garde sa socket en arrière-plan ne fait pas croire à Mika qu'on est devant l'écran.
 *
 * Les trames reçues sont traitées une à une, jusqu'au bout (base écrite), dans le contexte sérialisé.
 * L'ouverture d'une socket passe par la même file : ce qui dépend de la socket (les cartes d'accord)
 * repart de zéro après les trames de la précédente, avant celles de la nouvelle.
 */
class ConnectionManager(
    private val scope: CoroutineScope,
    private val engineContext: CoroutineDispatcher,
    private val auth: AuthRepository,
    private val chat: ChatEngine,
    private val mind: MindStateRepository,
    private val approvals: ApprovalsRepository,
    private val foreground: StateFlow<Boolean>,
    private val network: StateFlow<NetworkStatus>,
    clock: Clock,
    transport: WsTransport,
    private val userAgent: String,
    private val logger: Logger = Logger.NONE,
) : MikaSocket.Listener {

    enum class Holder { UI, SERVICE, REPLY }

    val socket = MikaSocket(transport, scope, clock, this, cursor = { chat.cursor }, logger = logger)

    /** L'état du lien, pour la ligne d'état, le bandeau et la notification du service. */
    val link: StateFlow<LinkState> = socket.state

    private val holders = mutableSetOf<Holder>()
    private var uiRelease: Job? = null
    private var lastNetworkId: Long? = null
    private var networkSeen = false

    /** Une trame, ou `null` : une socket vient de s'ouvrir. */
    private class Tagged(val epoch: Int, val frame: ServerFrame?)

    private val frames = Channel<Tagged>(Channel.UNLIMITED)
    private val frameLock = Mutex()
    /** Change à chaque fin de session : une trame d'avant n'écrit plus rien après l'effacement. */
    @Volatile private var epoch = 0

    /** À appeler une fois, après la restauration de la session. */
    fun start() {
        scope.launch {
            for (t in frames) {
                frameLock.withLock {
                    if (t.epoch == epoch) {
                        val frame = t.frame
                        if (frame == null) approvals.onOpened() else route(frame)
                    }
                }
            }
        }
        scope.launch { foreground.collect { onForeground(it) } }
        scope.launch { network.collect { onNetwork(it) } }
        scope.launch { auth.session.collect { reconcile() } }
    }

    fun acquire(holder: Holder) {
        scope.launch {
            if (holder == Holder.UI) {
                uiRelease?.cancel()
                uiRelease = null
            }
            holders += holder
            reconcile()
        }
    }

    fun release(holder: Holder) {
        scope.launch {
            holders -= holder
            reconcile()
        }
    }

    /** « Réessayer » du bandeau de connexion refusée. */
    fun retry() {
        scope.launch { socket.retry() }
    }

    /**
     * Décider d'une carte d'accord, maintenant ou pas du tout : `false` si la socket n'est pas ouverte
     * (rien ne part, rien n'est mis en file). Partie, la décision attend sa réponse (`approval_result`).
     */
    suspend fun decide(id: Long, decision: ApprovalDecision, digest: String): Boolean = withContext(engineContext) {
        val sent = socket.sendApproval(id, decision, digest)
        if (sent) approvals.onSent(id, decision)
        sent
    }

    /** Fin de session : plus rien ne part ni n'arrive, et une trame en cours de traitement finit d'abord. */
    suspend fun shutdown() = withContext(engineContext) {
        epoch++
        socket.reset()
        frameLock.withLock { }
        chat.reset()
        mind.reset()
        approvals.reset()
    }

    /**
     * « Effacer les messages de ce téléphone » sans fermer la session : la socket repart de zéro
     * (sa file d'envoi oubliée avec les bulles), [wipe] efface, puis on se reconnecte — le serveur
     * renvoie le fil récent, que rien ici ne notifiera (curseur à zéro).
     */
    suspend fun clearThread(wipe: suspend () -> Unit) = withContext(engineContext) {
        epoch++
        socket.reset()
        frameLock.withLock { }
        wipe()
        chat.reset()
        reconcile()
    }

    private fun reconcile() {
        val creds = auth.credentials()
        if (creds != null && auth.session.value is Session.LoggedIn && holders.isNotEmpty()) {
            socket.start(MikaSocket.Endpoint(creds.base.ws(), creds.token, userAgent))
        } else {
            socket.stop()
        }
    }

    private fun onForeground(visible: Boolean) {
        chat.foreground = visible
        socket.setPresence(visible)
        if (visible) {
            uiRelease?.cancel()
            uiRelease = null
            holders += Holder.UI
            reconcile()
            // Revenue au premier plan : une socket qui dort ouverte est peut-être un cadavre.
            socket.ensureAlive()
        } else {
            // Les pensées à voix haute ne survivent pas au départ de l'écran.
            chat.clearEphemeral()
            if (Holder.UI in holders && uiRelease == null) {
                uiRelease = scope.launch {
                    delay(UI_GRACE_MS)
                    uiRelease = null
                    holders -= Holder.UI
                    reconcile()
                }
            }
        }
    }

    private fun onNetwork(status: NetworkStatus) {
        val first = !networkSeen
        val previous = lastNetworkId
        networkSeen = true
        lastNetworkId = status.networkId
        if (first) {
            // Le réseau connu au démarrage n'est pas un changement.
            socket.setNetworkAvailable(status.available)
            return
        }
        if (!status.available) {
            socket.onNetworkChanged(false)
            return
        }
        // Un autre réseau (Wi-Fi → données), ou son retour : la socket d'avant est à abandonner.
        if (previous != status.networkId) socket.onNetworkChanged(true)
    }

    override fun onFrame(frame: ServerFrame) {
        frames.trySend(Tagged(epoch, frame))
    }

    override fun onStatus(status: MikaSocket.ConnectionStatus) {
        // Le serveur n'envoie les cartes d'accord à l'ouverture que s'il y en a : la nouvelle socket
        // part d'une liste vide, dans l'ordre des trames.
        if (status is MikaSocket.ConnectionStatus.Connected) frames.trySend(Tagged(epoch, null))
        if (status is MikaSocket.ConnectionStatus.Unauthorized) scope.launch { verifySession() }
    }

    /** Un 4401 : `whoami` tranche — session finie (écran de connexion) ou autre chose (on reprend). */
    private suspend fun verifySession() {
        when (auth.checkAfterUnauthorized()) {
            AuthRepository.Check.VALID -> socket.retry()
            AuthRepository.Check.EXPIRED -> Unit // la session est fermée, `reconcile` arrête tout
            AuthRepository.Check.UNKNOWN -> {
                delay(VERIFY_RETRY_MS)
                if (socket.isTerminal && auth.session.value is Session.LoggedIn) socket.retry()
            }
        }
    }

    private suspend fun route(frame: ServerFrame) {
        try {
            when (frame) {
                is ServerFrame.Speech -> {
                    chat.onSpeech(frame)
                    mind.onSpeech(frame)
                }
                is ServerFrame.History -> chat.onHistory(frame)
                is ServerFrame.Ack -> chat.onAck(frame)
                is ServerFrame.EmotionUpdate -> mind.onEmotion(frame)
                is ServerFrame.InnerStateUpdate -> mind.onInnerState(frame.state)
                is ServerFrame.Approvals -> approvals.onApprovals(frame)
                is ServerFrame.ApprovalResult -> approvals.onResult(frame)
                is ServerFrame.Pong, is ServerFrame.Unknown -> Unit
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            // Un gestionnaire qui lève n'arrête rien : la trame suivante passera.
            logger.e(TAG, "trame ${frame.javaClass.simpleName} non appliquée", e)
        }
    }

    private companion object {
        const val TAG = "Connection"
        const val UI_GRACE_MS = 30_000L
        const val VERIFY_RETRY_MS = 30_000L
    }
}
