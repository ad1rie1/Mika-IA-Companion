package fr.qwartz.mika.data.phone

/**
 * La dernière action « Répondre » de chaque conversation du téléphone (ADR 0120), **en mémoire seulement** : un
 * `PendingIntent` d'une autre appli ne s'écrit pas sur disque, et il ne vaut que le temps de sa notification. C'est par
 * elle qu'une réponse proposée part dans WhatsApp ou Messages ; sans elle (appli redémarrée, aucun message depuis), le
 * texte est copié. Bornée aux [max] conversations les plus récentes.
 *
 * Chaque action garde le nom que sa notification donnait à la conversation (le groupe, sinon qui y écrivait) : c'est à
 * lui qu'elle répond. Deux téléphones du même compte peuvent donner la même clé à deux conversations (un identifiant
 * local à chacun), que le serveur range dans un seul fil : l'écran ne répond d'ici que si ce nom est celui du fil
 * montré (R3-06, `PhoneHere.canDeliver`).
 */
class ReplyRegistry<A : Any>(private val max: Int = DEFAULT_MAX) {
    /** Une action gardée, et le nom de la conversation à qui elle répond (vide : sa notification ne la nommait pas). */
    data class Kept<A>(val action: A, val name: String)

    private val byThread = object : LinkedHashMap<String, Kept<A>>(16, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, Kept<A>>?): Boolean = size > max
    }

    /** Garder l'action de [thread] ; [name] vide (une notification qui ne nomme personne) garde le nom d'avant. */
    @Synchronized fun put(thread: String, action: A, name: String = "") {
        val known = name.trim().ifEmpty { byThread[thread]?.name.orEmpty() }
        byThread[thread] = Kept(action, known)
    }

    @Synchronized fun get(thread: String): A? = byThread[thread]?.action

    /** L'action de [thread] et le nom à qui elle répond ; `null` sans action gardée. */
    @Synchronized fun kept(thread: String): Kept<A>? = byThread[thread]

    @Synchronized fun size(): Int = byThread.size

    /** L'interrupteur coupé, la déconnexion : plus aucune réponse ne part par une action gardée d'avant. */
    @Synchronized fun clear() = byThread.clear()

    companion object {
        const val DEFAULT_MAX = 200
    }
}
