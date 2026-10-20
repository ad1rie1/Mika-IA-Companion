package fr.qwartz.mika.data.phone

/**
 * La dernière action « Répondre » de chaque conversation du téléphone (ADR 0120), **en mémoire seulement** : un
 * `PendingIntent` d'une autre appli ne s'écrit pas sur disque, et il ne vaut que le temps de sa notification. C'est par
 * elle qu'une réponse proposée part dans WhatsApp ou Messages ; sans elle (appli redémarrée, aucun message depuis), le
 * texte est copié. Bornée aux [max] conversations les plus récentes.
 */
class ReplyRegistry<A : Any>(private val max: Int = DEFAULT_MAX) {
    private val byThread = object : LinkedHashMap<String, A>(16, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, A>?): Boolean = size > max
    }

    @Synchronized fun put(thread: String, action: A) {
        byThread[thread] = action
    }

    @Synchronized fun get(thread: String): A? = byThread[thread]

    @Synchronized fun size(): Int = byThread.size

    /** L'interrupteur coupé, la déconnexion : plus aucune réponse ne part par une action gardée d'avant. */
    @Synchronized fun clear() = byThread.clear()

    companion object {
        const val DEFAULT_MAX = 200
    }
}
