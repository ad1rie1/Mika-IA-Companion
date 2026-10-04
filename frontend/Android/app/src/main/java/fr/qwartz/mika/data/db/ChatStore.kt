package fr.qwartz.mika.data.db

import androidx.room.withTransaction
import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.chat.ChatSync
import fr.qwartz.mika.data.chat.MessageAttachment
import fr.qwartz.mika.data.chat.MessageStatus
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.serialization.builtins.ListSerializer

/**
 * Le fil en base. Toute écriture passe par [mutate] : charger le fil → une fonction pure de
 * `ChatSync` → la différence (par clé locale) → l'écrire, dans une seule transaction. Le fil fait au
 * plus [fr.qwartz.mika.data.net.MikaProtocol.MAX_LOCAL_MESSAGES] lignes : le tout recharger reste bon
 * marché, et c'est ce qui garde `ChatSync` identique au client web.
 */
class ChatStore(private val db: MikaDatabase) : ThreadStore {
    private val messages = db.messages()
    private val outbox = db.outbox()
    private val kv = db.kv()

    private inner class Draft(override var thread: MutableList<StoredMessage>) : ThreadDraft {
        override suspend fun kvGet(key: String): String? = kv.get(key)
        override suspend fun kvPut(key: String, value: String?) = this@ChatStore.kvPut(key, value)
        override suspend fun outboxPut(row: OutboxEntity) = outbox.put(row)
        override suspend fun outboxDelete(cid: String) = outbox.delete(cid)
    }

    override suspend fun <T> mutate(block: suspend ThreadDraft.() -> T): T = db.withTransaction {
        val rows = messages.all()
        val before = rows.associateBy { it.localId }
        val draft = Draft(rows.map { it.toModel() }.toMutableList())
        val result = draft.block()
        val kept = draft.thread.mapNotNullTo(HashSet()) { m -> m.localId.takeIf { it != 0L } }
        val gone = before.keys.filter { it !in kept }
        // Supprimer d'abord : un identifiant serveur ou de corrélation libéré peut être repris.
        if (gone.isNotEmpty()) gone.chunked(500).forEach { messages.deleteByLocalIds(it) }
        for (m in draft.thread) {
            if (m.localId == 0L) {
                m.localId = messages.insert(m.toEntity())
            } else {
                val row = m.toEntity()
                if (before[m.localId] != row) messages.update(row)
            }
        }
        result
    }

    /** Le fil trié (`ChatSync.sortMessages`), à chaque écriture. */
    fun observe(): Flow<List<StoredMessage>> = messages.observeAll()
        .map { rows -> ChatSync.sortMessages(rows.map { it.toModel() }.toMutableList()) }
        .distinctUntilChanged()

    fun observeKv(key: String): Flow<String?> = kv.observe(key).distinctUntilChanged()

    override suspend fun kvGet(key: String): String? = kv.get(key)
    override suspend fun kvPut(key: String, value: String?) {
        if (value == null) kv.delete(key) else kv.put(KvEntity(key, value))
    }

    override suspend fun maxServerId(): Long = messages.maxServerId()
    suspend fun ownClientMsgIds(): Set<String> = messages.clientMsgIds().toSet()
    suspend fun message(localId: Long): StoredMessage? = messages.byLocalId(localId)?.toModel()
    suspend fun outboxRows(): List<OutboxEntity> = outbox.all()

    /**
     * Tout effacer : déconnexion, changement de compte ou de serveur, « Effacer les messages de ce
     * téléphone ». [keep] : les petites valeurs qui survivent (le brouillon, le propriétaire…).
     */
    suspend fun wipe(keep: Set<String> = emptySet()) = db.withTransaction {
        val saved = keep.mapNotNull { k -> kv.get(k)?.let { KvEntity(k, it) } }
        messages.deleteAll()
        outbox.deleteAll()
        kv.deleteAll()
        saved.forEach { kv.put(it) }
    }

    companion object {
        private val ATTACHMENTS = ListSerializer(MessageAttachment.serializer())

        fun MessageEntity.toModel() = StoredMessage(
            text = text,
            sender = if (sender == SENDER_USER) Sender.USER else Sender.MIKA,
            ts = ts,
            id = serverId,
            cid = clientMsgId,
            status = ChatSync.coerceStatus(status),
            matchText = matchText,
            reason = reason,
            note = note,
            after = afterCursor,
            replyNote = replyNote,
            replyHref = replyHref,
            waiting = waiting,
            localId = localId,
            attachments = decodeAttachments(attachments),
            source = source,
            emotion = emotion,
            emotionIntensity = emotionIntensity,
        )

        fun StoredMessage.toEntity() = MessageEntity(
            localId = localId,
            serverId = id,
            clientMsgId = cid,
            sender = if (sender == Sender.USER) SENDER_USER else SENDER_MIKA,
            text = text,
            matchText = matchText,
            attachments = if (attachments.isEmpty()) "[]" else MikaJson.encodeToString(ATTACHMENTS, attachments),
            ts = ts,
            status = when (status) {
                MessageStatus.PENDING -> "pending"
                MessageStatus.SENT -> "sent"
                MessageStatus.FAILED -> "failed"
                null -> null
            },
            reason = reason,
            note = note,
            replyNote = replyNote,
            replyHref = replyHref,
            waiting = waiting,
            afterCursor = after,
            source = source,
            emotion = emotion,
            emotionIntensity = emotionIntensity,
        )

        private fun decodeAttachments(raw: String): List<MessageAttachment> =
            if (raw.isBlank() || raw == "[]") {
                emptyList()
            } else {
                try {
                    MikaJson.decodeFromString(ATTACHMENTS, raw)
                } catch (_: IllegalArgumentException) {
                    emptyList()
                }
            }

        const val SENDER_USER = "user"
        const val SENDER_MIKA = "mika"
    }
}
