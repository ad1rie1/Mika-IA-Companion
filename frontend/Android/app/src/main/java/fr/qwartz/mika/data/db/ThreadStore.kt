package fr.qwartz.mika.data.db

import fr.qwartz.mika.data.chat.StoredMessage

/** Ce qu'une mutation du fil voit et touche : le fil (remplaçable), la file d'envoi, les petites valeurs. */
interface ThreadDraft {
    var thread: MutableList<StoredMessage>
    suspend fun kvGet(key: String): String?
    suspend fun kvPut(key: String, value: String?)
    suspend fun outboxPut(row: OutboxEntity)
    suspend fun outboxDelete(cid: String)
}

/**
 * Le fil tel que le moteur le manipule. [ChatStore] le tient dans Room ; les tests JVM, en mémoire —
 * c'est ce qui permet d'éprouver `ChatEngine` sans émulateur.
 */
interface ThreadStore {
    /** Charger le fil, appliquer [block], écrire la différence — en une transaction. */
    suspend fun <T> mutate(block: suspend ThreadDraft.() -> T): T
    suspend fun kvGet(key: String): String?
    suspend fun kvPut(key: String, value: String?)
    suspend fun maxServerId(): Long
}
