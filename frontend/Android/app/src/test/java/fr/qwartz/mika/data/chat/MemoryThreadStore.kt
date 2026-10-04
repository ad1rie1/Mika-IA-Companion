package fr.qwartz.mika.data.chat

import fr.qwartz.mika.data.db.OutboxEntity
import fr.qwartz.mika.data.db.ThreadDraft
import fr.qwartz.mika.data.db.ThreadStore

/** Le fil en mémoire, avec les mêmes règles que `ChatStore` : copie, mutation, écriture d'un bloc. */
class MemoryThreadStore : ThreadStore {
    val rows = mutableListOf<StoredMessage>()
    val kv = mutableMapOf<String, String>()
    val outbox = linkedMapOf<String, OutboxEntity>()
    private var nextId = 1L

    override suspend fun <T> mutate(block: suspend ThreadDraft.() -> T): T {
        val draft = object : ThreadDraft {
            override var thread: MutableList<StoredMessage> = rows.map { it.copy() }.toMutableList()
            override suspend fun kvGet(key: String) = kv[key]
            override suspend fun kvPut(key: String, value: String?) {
                if (value == null) kv.remove(key) else kv[key] = value
            }
            override suspend fun outboxPut(row: OutboxEntity) {
                outbox[row.clientMsgId] = row
            }
            override suspend fun outboxDelete(cid: String) {
                outbox.remove(cid)
            }
        }
        val result = draft.block()
        for (m in draft.thread) if (m.localId == 0L) m.localId = nextId++
        rows.clear()
        rows.addAll(draft.thread.map { it.copy() })
        return result
    }

    override suspend fun kvGet(key: String) = kv[key]
    override suspend fun kvPut(key: String, value: String?) {
        if (value == null) kv.remove(key) else kv[key] = value
    }

    override suspend fun maxServerId(): Long = rows.mapNotNull { it.id }.maxOrNull() ?: 0L

    fun sorted(): List<StoredMessage> = ChatSync.sortMessages(rows.toMutableList())
}
