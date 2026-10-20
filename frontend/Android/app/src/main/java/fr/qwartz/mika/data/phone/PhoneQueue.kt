package fr.qwartz.mika.data.phone

import kotlinx.serialization.Serializable

/**
 * Ce qui attend de partir au serveur (ADR 0120), gardé sur le téléphone (table `kv`, une ligne JSON) : en 4G, le serveur
 * de la maison ne répond pas, les messages attendent le Wi-Fi.
 */
@Serializable
data class PhoneQueueState(
    /** Les messages lus pas encore acceptés, dans l'ordre où ils sont arrivés. */
    val messages: List<PhoneMessage> = emptyList(),
    /** Le sort des réponses proposées, pas encore dit au serveur. */
    val settled: List<PhoneSettled> = emptyList(),
    /**
     * Les derniers identifiants mis en file, partis ou non : une notification mise à jour redit tous ses messages, ils
     * ne repartent pas à chaque fois.
     */
    val seen: List<String> = emptyList(),
    /** Quand le serveur a refusé (403, heure murale) ; 0 : il ne refuse pas. */
    val refusedAt: Long = 0,
    /** Le dernier lot accepté (heure murale) ; 0 : jamais. */
    val sentAt: Long = 0,
)

/**
 * Les règles de la file, pures (ADR 0120) : bornée à [MAX_MESSAGES] (les plus anciens tombent), dédoublonnée par
 * identifiant, partie par lots de [BATCH] dans l'ordre d'arrivée.
 */
object PhoneQueue {
    const val MAX_MESSAGES = 500
    const val BATCH = 200
    const val MAX_SEEN = 2_000
    const val MAX_SETTLED = 200

    /**
     * Le texte de la file entière, au plus : 500 messages de 4 000 caractères ne tiendraient pas dans une ligne que
     * SQLite relit d'un bloc (2 Mio). Au-delà, les plus anciens tombent aussi.
     */
    const val MAX_CHARS = 400_000

    data class Added(val state: PhoneQueueState, val added: Int)

    /** Les messages neufs (ni en file, ni déjà vus) au bout de la file ; les plus anciens tombent au-delà des bornes. */
    fun add(state: PhoneQueueState, incoming: List<PhoneMessage>): Added {
        val known = HashSet<String>(state.seen)
        state.messages.mapTo(known) { it.id }
        val fresh = incoming.filter { known.add(it.id) }
        if (fresh.isEmpty()) return Added(state, 0)
        val messages = withinChars((state.messages + fresh).takeLast(MAX_MESSAGES))
        val seen = (state.seen + fresh.map { it.id }).takeLast(MAX_SEEN)
        return Added(state.copy(messages = messages, seen = seen), fresh.size)
    }

    /** Le prochain lot : les plus anciens d'abord. */
    fun batch(state: PhoneQueueState): List<PhoneMessage> = state.messages.take(BATCH)

    /** Un lot accepté (ou écarté) : il quitte la file. */
    fun without(state: PhoneQueueState, ids: Set<String>): PhoneQueueState =
        state.copy(messages = state.messages.filterNot { it.id in ids })

    /** Le sort d'une proposition : le dernier dit l'emporte, borné à [MAX_SETTLED]. */
    fun settle(state: PhoneQueueState, item: PhoneSettled): PhoneQueueState =
        state.copy(settled = (state.settled.filterNot { it.id == item.id } + item).takeLast(MAX_SETTLED))

    fun settledBatch(state: PhoneQueueState): List<PhoneSettled> = state.settled.take(BATCH)

    fun withoutSettled(state: PhoneQueueState, items: List<PhoneSettled>): PhoneQueueState {
        val gone = items.toSet()
        return state.copy(settled = state.settled.filterNot { it in gone })
    }

    private fun withinChars(messages: List<PhoneMessage>): List<PhoneMessage> {
        var total = messages.sumOf { it.text.length + it.name.length + it.title.length }
        if (total <= MAX_CHARS) return messages
        var start = 0
        while (start < messages.size && total > MAX_CHARS) {
            val m = messages[start++]
            total -= m.text.length + m.name.length + m.title.length
        }
        return messages.drop(start)
    }
}
