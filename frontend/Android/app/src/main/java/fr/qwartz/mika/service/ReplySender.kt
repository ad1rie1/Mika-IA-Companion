package fr.qwartz.mika.service

import fr.qwartz.mika.core.Logger
import fr.qwartz.mika.data.chat.ChatRepository
import fr.qwartz.mika.data.chat.MessageStatus
import fr.qwartz.mika.data.settings.SettingsStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Répondre depuis la notification, application fermée. La réponse s'écrit comme un message tapé
 * (bulle + file d'envoi, une transaction), la connexion est demandée le temps de son accusé
 * ([ConnectionManager.Holder.REPLY]) ; si l'arrière-plan est coupé, un service d'un coup garde le
 * processus en vie jusque-là (60 s au plus), jusqu'à la dernière réponse accusée s'il y en a plusieurs.
 */
class ReplySender(
    private val scope: CoroutineScope,
    private val chat: ChatRepository,
    private val connection: ConnectionManager,
    private val notifier: MessageNotifier,
    private val settings: SettingsStore,
    private val controller: () -> ServiceController,
    private val logger: Logger = Logger.NONE,
) {
    private val lock = Mutex()
    private var inFlight = 0

    /** Les réponses que tient le service d'un coup : un seul pour toutes, arrêté à la dernière accusée. */
    private var oneShots = 0

    suspend fun reply(text: String) {
        hold()
        val result = chat.send(text)
        if (result !is ChatRepository.SendResult.Queued) {
            val reason = (result as ChatRepository.SendResult.Rejected).reason
            notifier.onReplied("Non envoyé — $reason")
            release(oneShot = false)
            return
        }
        notifier.onReplied(text)
        val oneShot = !settings.current().background && startOneShot()
        scope.launch {
            try {
                val settled = withTimeoutOrNull(ACK_WAIT_MS) {
                    chat.observe().first { thread ->
                        val status = thread.firstOrNull { it.cid == result.clientMsgId }?.status
                        status != MessageStatus.PENDING
                    }
                }
                if (settled == null) logger.w(TAG, "réponse sans accusé après 60 s : elle repartira à la prochaine connexion")
            } finally {
                release(oneShot)
            }
        }
    }

    private suspend fun hold() = lock.withLock {
        if (inFlight++ == 0) connection.acquire(ConnectionManager.Holder.REPLY)
    }

    private suspend fun startOneShot(): Boolean = lock.withLock {
        controller().startOneShot().also { if (it) oneShots++ }
    }

    private suspend fun release(oneShot: Boolean) {
        // L'arrière-plan a pu être activé entre-temps : ce service-là reste.
        val background = oneShot && settings.current().background
        lock.withLock {
            if (--inFlight == 0) connection.release(ConnectionManager.Holder.REPLY)
            // Sous le verrou, comme le démarrage : la fin ne double pas un « d'un coup » demandé après elle.
            if (oneShot && --oneShots == 0 && !background) controller().endOneShot()
        }
    }

    private companion object {
        const val TAG = "Reply"
        const val ACK_WAIT_MS = 60_000L
    }
}
