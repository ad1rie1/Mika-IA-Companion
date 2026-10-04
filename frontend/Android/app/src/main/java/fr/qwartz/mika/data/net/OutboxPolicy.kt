package fr.qwartz.mika.data.net

/**
 * Les deux bornes d'une file d'envoi : en nombre et en octets (WebSocketClient.ts `enqueue`,
 * `holdUntilAck`). Une borne en nombre seule laisse une coupure accumuler 20 trames de 15 Mio ;
 * une borne en octets seule laisse des centaines de petits messages.
 *
 * L'éviction se fait par la tête — le plus ancien part le premier — et ne vide jamais plus que la
 * file : une entrée seule tient toujours ([MikaProtocol.MAX_FRAME_BYTES] < [MikaProtocol.MAX_OUTBOX_BYTES]).
 */
object OutboxPolicy {

    /** Combien d'entrées de tête évincer pour admettre une entrée de [incomingBytes]. */
    fun evictions(
        sizes: List<Long>,
        incomingBytes: Long,
        maxCount: Int = MikaProtocol.MAX_OUTBOX,
        maxBytes: Long = MikaProtocol.MAX_OUTBOX_BYTES,
    ): Int {
        var total = sizes.sum()
        var count = sizes.size
        var evicted = 0
        while (count > 0 && (count >= maxCount || total + incomingBytes > maxBytes)) {
            total -= sizes[evicted]
            count -= 1
            evicted += 1
        }
        return evicted
    }
}
