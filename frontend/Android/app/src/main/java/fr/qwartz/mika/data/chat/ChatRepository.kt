package fr.qwartz.mika.data.chat

import fr.qwartz.mika.core.Clock
import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.db.ChatStore
import fr.qwartz.mika.data.db.Kv
import fr.qwartz.mika.data.db.OutboxEntity
import fr.qwartz.mika.data.files.AttachmentPolicy
import fr.qwartz.mika.data.files.OutboxFile
import fr.qwartz.mika.data.files.OutboxFiles
import fr.qwartz.mika.data.files.StagedFile
import fr.qwartz.mika.data.net.ChatFrameWriter
import fr.qwartz.mika.data.net.MikaSocket
import fr.qwartz.mika.data.net.OutgoingFile
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withContext
import kotlinx.serialization.builtins.ListSerializer

/**
 * Le fil vu de l'écran : l'observer, envoyer, réessayer, effacer. Un envoi écrit la bulle et sa
 * ligne de file d'envoi dans une seule transaction, puis la confie à la socket : tapé hors ligne, un
 * message survit à la mort du processus et part à la prochaine connexion.
 */
class ChatRepository(
    private val store: ChatStore,
    private val files: OutboxFiles,
    private val clock: Clock,
    /** Le contexte sérialisé où vit la socket. */
    private val engineContext: CoroutineDispatcher,
    /** La socket courante (elle change avec la session). */
    private val socket: () -> MikaSocket,
    private val io: CoroutineDispatcher = Dispatchers.IO,
) {
    sealed interface SendResult {
        data class Queued(val clientMsgId: String) : SendResult
        data class Rejected(val reason: String) : SendResult
    }

    fun observe(): Flow<List<StoredMessage>> = store.observe()

    fun observeLastReadId(): Flow<Long> = store.observeKv(Kv.LAST_READ_ID).map { it?.toLongOrNull() ?: 0L }

    /** Envoyer ce qui a été tapé, avec des fichiers déjà préparés (copiés dans l'espace de l'app). */
    suspend fun send(text: String, staged: List<StagedFile> = emptyList()): SendResult {
        val message = text.trim()
        AttachmentPolicy.checkSend(message, staged)?.let { return SendResult.Rejected(it) }
        val cid = ChatSync.nextClientMsgId(clock.wallMs())
        val outboxFiles = withContext(io) { files.adopt(cid, staged) }
        val frameBytes = ChatFrameWriter.frameBytes(message, cid, outgoing(cid, outboxFiles))
        // La même composition que le fil relu : la ligne du serveur reconnaîtra sa bulle.
        val display = ChatSync.withAttachments(message, outboxFiles.map { it.name })
        store.mutate {
            thread.add(
                StoredMessage(
                    text = display,
                    sender = Sender.USER,
                    ts = clock.wallMs(),
                    cid = cid,
                    status = MessageStatus.PENDING,
                    matchText = if (outboxFiles.isEmpty()) null else message,
                    attachments = outboxFiles.map {
                        MessageAttachment(it.name, AttachmentPolicy.kindOf(it.mime), it.mime, it.size, local = it.file)
                    },
                ),
            )
            outboxPut(
                OutboxEntity(
                    clientMsgId = cid,
                    message = message,
                    attachments = MikaJson.encodeToString(OUTBOX_FILES, outboxFiles),
                    frameBytes = frameBytes,
                    createdAt = clock.wallMs(),
                ),
            )
        }
        withContext(engineContext) { socket().offer(outbound(cid, message, outboxFiles, frameBytes)) }
        return SendResult.Queued(cid)
    }

    /** Renvoyer une bulle refusée : elle disparaît, un nouveau message part avec ses fichiers encore là. */
    suspend fun retry(localId: Long): SendResult? {
        val failed = store.message(localId) ?: return null
        if (failed.sender != Sender.USER || failed.status != MessageStatus.FAILED) return null
        val typed = if (failed.attachments.isEmpty()) failed.text else failed.matchText.orEmpty()
        val cid = failed.cid
        val staged = if (cid == null) {
            emptyList()
        } else {
            withContext(io) {
                files.restage(
                    cid,
                    failed.attachments.mapNotNull { a -> a.local?.let { a.name to it } },
                ) { name -> failed.attachments.firstOrNull { it.name == name }?.mime ?: "application/octet-stream" }
            }
        }
        store.mutate {
            thread.removeAll { it.localId == localId }
            if (cid != null) outboxDelete(cid)
        }
        if (cid != null) withContext(io) { files.forget(cid) }
        return send(typed, staged)
    }

    /**
     * Au démarrage : ce qui a encore sa ligne de file d'envoi repart ; une bulle « en attente » sans
     * ligne ne partira plus (l'app a été fermée avant qu'elle soit écrite) et le dit.
     */
    suspend fun restore() {
        val rows = store.outboxRows()
        val queued = rows.map { it.clientMsgId }.toSet()
        val known = store.mutate {
            for (m in thread) {
                if (m.sender == Sender.USER && m.status == MessageStatus.PENDING) {
                    val r = ChatSync.restoredStatus("pending", m.cid != null && m.cid in queued)
                    m.status = r.status
                    m.reason = r.reason
                }
            }
            val cids = thread.mapNotNullTo(HashSet()) { it.cid }
            // Une ligne d'envoi sans bulle (fil vidé entre-temps) n'a plus rien à porter.
            rows.filter { it.clientMsgId !in cids }.forEach { outboxDelete(it.clientMsgId) }
            cids
        }
        val offers = rows.filter { it.clientMsgId in known }.map { row ->
            val outboxFiles = decodeFiles(row.attachments)
            outbound(row.clientMsgId, row.message, outboxFiles, row.frameBytes)
        }
        if (offers.isNotEmpty()) withContext(engineContext) { offers.forEach { socket().offer(it) } }
    }

    /** La conversation est ouverte : tout ce qui est là est lu. */
    suspend fun markRead(cursor: Long) {
        val current = store.kvGet(Kv.LAST_READ_ID)?.toLongOrNull() ?: 0L
        if (cursor > current) store.kvPut(Kv.LAST_READ_ID, cursor.toString())
    }

    /**
     * « Effacer les messages de ce téléphone » et la déconnexion : la base et les fichiers.
     * [keepKeys] et [keepStaging] gardent ce qui n'est pas la conversation (brouillon, partage reçu).
     */
    suspend fun wipe(keepKeys: Set<String> = emptySet(), keepStaging: Boolean = false) {
        store.wipe(keepKeys)
        withContext(io) { files.wipe(keepStaging) }
    }

    private fun outbound(cid: String, message: String, outboxFiles: List<OutboxFile>, frameBytes: Long) =
        MikaSocket.OutboundChat(cid, frameBytes) { ChatFrameWriter.render(message, cid, outgoing(cid, outboxFiles)) }

    private fun outgoing(cid: String, outboxFiles: List<OutboxFile>): List<OutgoingFile> =
        outboxFiles.map { f -> OutgoingFile(f.name, f.mime, f.size) { files.open(cid, f.file) } }

    private fun decodeFiles(raw: String): List<OutboxFile> = try {
        MikaJson.decodeFromString(OUTBOX_FILES, raw)
    } catch (_: IllegalArgumentException) {
        emptyList()
    }

    private companion object {
        val OUTBOX_FILES = ListSerializer(OutboxFile.serializer())
    }
}
