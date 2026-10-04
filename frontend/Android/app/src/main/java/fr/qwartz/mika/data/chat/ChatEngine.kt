package fr.qwartz.mika.data.chat

import fr.qwartz.mika.core.Clock
import fr.qwartz.mika.core.Logger
import fr.qwartz.mika.data.db.Kv
import fr.qwartz.mika.data.db.ThreadDraft
import fr.qwartz.mika.data.db.ThreadStore
import fr.qwartz.mika.data.files.OutboxFiles
import fr.qwartz.mika.data.net.MikaProtocol
import fr.qwartz.mika.data.net.ServerFrame
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Ce qui vient d'arriver dans le fil — de quoi décider d'une notification (`NotificationPolicy`). */
sealed interface ChatEvent {
    /**
     * De nouvelles paroles de Mika. [live] : une trame `speech` (et [replyToClientMsgId] ce à quoi
     * elle répond) ; sinon un rattrapage. [cursorBefore] : le curseur avant la trame (0 = première
     * synchronisation).
     */
    data class MikaSpoke(
        val messages: List<StoredMessage>,
        val live: Boolean,
        val replyToClientMsgId: String?,
        val cursorBefore: Long,
        /**
         * Dans un rattrapage : les réponses de Mika à une question posée d'un autre appareil (la
         * question, nouvelle elle aussi, n'est pas une des nôtres). Elles ne se notifient pas.
         */
        val answeredElsewhere: Set<Long> = emptySet(),
    ) : ChatEvent
}

/**
 * Applique les trames du serveur au fil — portage des gestionnaires de `ChatOverlay.ts` (`speech`,
 * `ack`, `history`). Une trame est traitée jusqu'au bout (base écrite) avant la suivante : c'est le
 * contexte sérialisé de l'app qui appelle, l'une après l'autre.
 */
class ChatEngine(
    private val store: ThreadStore,
    private val files: OutboxFiles,
    private val clock: Clock,
    private val scope: CoroutineScope,
    private val logger: Logger = Logger.NONE,
    private val io: CoroutineDispatcher = Dispatchers.IO,
) {
    /** « Mika écrit… » : entre l'accusé `accepted` et la réponse, plafonné à 5 min. */
    private val _typing = MutableStateFlow(false)
    val typing: StateFlow<Boolean> = _typing.asStateFlow()
    private var typingTimer: Job? = null

    /**
     * Ses pensées à voix haute et les notes de la machine : jamais en base, montrées seulement au
     * premier plan, rangées après le curseur de leur arrivée.
     */
    private val _ephemeral = MutableStateFlow<List<StoredMessage>>(emptyList())
    val ephemeral: StateFlow<List<StoredMessage>> = _ephemeral.asStateFlow()
    private var nextEphemeralId = -1L

    private val _truncated = MutableStateFlow(false)
    val truncated: StateFlow<Boolean> = _truncated.asStateFlow()

    private val _events = MutableSharedFlow<ChatEvent>(extraBufferCapacity = 16)
    val events: SharedFlow<ChatEvent> = _events.asSharedFlow()

    /** Le curseur, tenu en mémoire pour la socket (qui le lit sans attendre la base). */
    @Volatile var cursor: Long = 0
        private set

    /** Le premier plan : une pensée n'est montrée qu'à qui regarde. */
    @Volatile var foreground: Boolean = false

    suspend fun init() {
        cursor = store.maxServerId()
        _truncated.value = store.kvGet(Kv.TRUNCATED) == "1"
    }

    suspend fun onSpeech(f: ServerFrame.Speech) {
        setTyping(false)
        val cursorBefore = cursor
        val text = ChatSync.stripProsody(f.text)
        val cid = f.clientMsgId
        val systemNote = f.source == MikaProtocol.SOURCE_ERROR && f.messageId == null
        val added = store.mutate {
            if (cid != null) {
                ChatSync.bindServerId(thread, cid, f.userMessageId)
                // Elle dort : la réponse attend son réveil. Sans ce mot, la bulle restait sans explication.
                if (f.text.isEmpty() && f.voiceReason == MikaProtocol.VOICE_REASON_ASLEEP) {
                    ChatSync.markAsleep(thread, cid)
                }
            }
            if (text.isEmpty() || f.isInner || systemNote) return@mutate null
            // Une réponse peut arriver deux fois : en direct, puis dans un rattrapage qui croise le même tour.
            if (f.messageId != null && thread.any { it.id == f.messageId }) return@mutate null
            val row = StoredMessage(
                text = text,
                sender = Sender.MIKA,
                ts = clock.wallMs(),
                id = f.messageId,
                after = if (f.messageId == null) ChatSync.cursorOf(thread) else null,
                attachments = f.attachments.map(MessageAttachment::of),
                source = f.source.ifEmpty { null },
                emotion = f.emotion.ifEmpty { null },
                emotionIntensity = f.emotionIntensity,
            )
            thread.add(row)
            trim(this)
            row
        }
        refreshCursor()
        if (text.isNotEmpty() && f.isInner && foreground) {
            addEphemeral(StoredMessage(text, Sender.MIKA, clock.wallMs(), after = cursor, inner = true))
        }
        if (text.isNotEmpty() && systemNote) {
            addEphemeral(StoredMessage(text, Sender.MIKA, clock.wallMs(), after = cursor, source = MikaProtocol.SOURCE_ERROR))
        }
        if (added != null) {
            _events.tryEmit(ChatEvent.MikaSpoke(listOf(added), live = true, replyToClientMsgId = cid, cursorBefore = cursorBefore))
        }
    }

    suspend fun onAck(f: ServerFrame.Ack) {
        if (f.clientMsgId.isEmpty()) return
        val result = store.mutate {
            outboxDelete(f.clientMsgId)
            ChatSync.applyAck(thread, f.clientMsgId, f.status, f.rejectedAttachments, f.reason, f.detail, f.href)
        }
        // Reçu ou refusé, il ne repartira pas d'ici : ses fichiers quittent la file d'envoi.
        try {
            withContext(io) { files.release(f.clientMsgId) }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            logger.w(TAG, "fichiers du message non rangés", e)
        }
        if (!result.changed) return
        // Un message refusé, ou dont la réponse ne viendra pas, n'est pas en train d'être répondu.
        if (result.settled) setTyping(false) else if (f.status == MikaProtocol.ACK_ACCEPTED) setTyping(true)
    }

    suspend fun onHistory(f: ServerFrame.History) {
        val cursorBefore = cursor
        val result = store.mutate {
            val cachedLife = kvGet(Kv.LIFE).orEmpty()
            var truncated = kvGet(Kv.TRUNCATED) == "1"
            if (ChatSync.fromAnotherLife(cachedLife, f.life, f.reset)) {
                // Un fil d'une autre vie : ses identifiants ne veulent rien dire ici.
                thread = ChatSync.keepAcrossLives(thread)
                truncated = false
            }
            if (!f.life.isNullOrEmpty()) kvPut(Kv.LIFE, f.life)
            val merge = ChatSync.mergeHistory(thread, f.messages, MikaProtocol.MAX_LOCAL_MESSAGES, clock.wallMs())
            thread = merge.history
            // Un fil initial est une fenêtre entière : il tranche la question du trou ; un rattrapage l'ajoute.
            truncated = if (f.isInitial) f.truncated else truncated || f.truncated
            kvPut(Kv.TRUNCATED, if (truncated) "1" else null)
            if (f.truncated) {
                f.messages.orEmpty().mapNotNull { it.id }.minOrNull()?.let { kvPut(Kv.GAP_BEFORE_ID, it.toString()) }
            }
            _truncated.value = truncated
            Triple(merge, thread.filter { it.sender == Sender.MIKA && it.localId == 0L && !it.inner }, answeredElsewhere(thread))
        }
        refreshCursor()
        // Tout ce à quoi le serveur a répondu n'est plus attendu.
        if (result.first.sawReply) setTyping(false)
        if (result.second.isNotEmpty()) {
            _events.tryEmit(
                ChatEvent.MikaSpoke(
                    result.second, live = false, replyToClientMsgId = null, cursorBefore = cursorBefore,
                    answeredElsewhere = result.third,
                ),
            )
        }
    }

    /**
     * Les nouvelles paroles de Mika qui suivent immédiatement une question nouvelle venue d'ailleurs
     * (une ligne de la personne sans identifiant de corrélation : tapée sur la page web). Le fil est
     * trié ; « nouvelle » = pas encore écrite en base (`localId` à 0).
     */
    private fun answeredElsewhere(thread: List<StoredMessage>): Set<Long> {
        val out = HashSet<Long>()
        for (i in 1 until thread.size) {
            val m = thread[i]
            val prev = thread[i - 1]
            val id = m.id ?: continue
            if (m.sender != Sender.MIKA || m.inner || m.localId != 0L) continue
            if (prev.sender == Sender.USER && prev.cid == null && prev.localId == 0L) out += id
        }
        return out
    }

    /** Les pensées ne survivent pas au départ de l'écran (`ON_STOP`). */
    fun clearEphemeral() {
        _ephemeral.value = emptyList()
    }

    /** Déconnexion : rien de cette conversation ne reste en mémoire. */
    fun reset() {
        setTyping(false)
        _ephemeral.value = emptyList()
        _truncated.value = false
        cursor = 0
    }

    internal suspend fun refreshCursor() {
        cursor = store.maxServerId()
    }

    private fun addEphemeral(m: StoredMessage) {
        m.localId = nextEphemeralId--
        _ephemeral.update { (it + m).takeLast(MAX_EPHEMERAL) }
    }

    private fun trim(draft: ThreadDraft) {
        ChatSync.sortMessages(draft.thread)
        if (draft.thread.size > MikaProtocol.MAX_LOCAL_MESSAGES) {
            draft.thread = draft.thread.subList(draft.thread.size - MikaProtocol.MAX_LOCAL_MESSAGES, draft.thread.size)
                .toMutableList()
        }
    }

    private fun setTyping(on: Boolean) {
        typingTimer?.cancel()
        typingTimer = null
        _typing.value = on
        if (on) {
            typingTimer = scope.launch {
                delay(MikaProtocol.TYPING_TIMEOUT_MS)
                _typing.value = false
            }
        }
    }

    private companion object {
        const val TAG = "ChatEngine"
        const val MAX_EPHEMERAL = 20
    }
}
