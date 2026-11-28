package fr.qwartz.mika.data.moi

import fr.qwartz.mika.data.net.Topics
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.launch
import java.util.concurrent.CopyOnWriteArraySet
import java.util.concurrent.atomic.AtomicLong

/*
 * Le direct (ADR 0308) : ce qui change ce que montrent les routes de `/api/moi` est poussé sur la connexion du chat
 * (`/ws`) que l'app tient déjà, en une trame `changed` qui dit **quoi** a changé, jamais le contenu ; l'écran relit la
 * route qu'il montre. Le contrat — les sujets, leurs clés, ce qu'on relit : `backendv2/docs/protocole-moi.md`, § 2 bis.
 * Porté de `frontend/Web/src/live/live.ts` ; du Kotlin pur, testé sur la JVM.
 */

/**
 * Ce que le direct dit à un écran : ce qui a changé, sujet par sujet — pour chacun ce qu'il nomme, ou `null` : tout le
 * domaine —, ou, à une ouverture de la connexion, « relis tout ce que tu montres » ([resync] : rien de ce qui a changé
 * avant qu'elle écoute, ni pendant une coupure, n'est rattrapé).
 */
data class LiveSignal(val changes: Map<String, Set<String>?> = emptyMap(), val resync: Boolean = false) {
    /** Un changement de ce sujet (ou une resynchronisation, qui les vaut tous). */
    fun touches(topic: String): Boolean = resync || topic in changes

    /** Un changement d'un de ces sujets. */
    fun touchesAny(vararg topics: String): Boolean = topics.any(::touches)

    /**
     * Ce changement concerne-t-il [key] dans [topic] (une boîte, le mail ou la conversation ouverts, un projet) ? Tout
     * le domaine, ou une resynchronisation : oui ; ce sujet absent : non ; rien d'ouvert (une clé vide) : non.
     */
    fun names(topic: String, key: String?): Boolean {
        if (resync) return true
        if (topic !in changes) return false
        val named = changes[topic] ?: return true
        return !key.isNullOrEmpty() && key in named
    }

    /** Ce changement concerne-t-il l'une de ces clés ? */
    fun namesAny(topic: String, keys: Collection<String>): Boolean = names(topic, null) || keys.any { names(topic, it) }

    /** Ce qui, de ce signal, touche [topics] ; rien : `null`. */
    internal fun only(topics: Set<String>): LiveSignal? {
        if (resync) return this
        val mine = changes.filterKeys { it in topics }
        return if (mine.isEmpty()) null else LiveSignal(mine)
    }

    /** Deux signaux en un : les clés réunies, « tout le domaine » et la resynchronisation l'emportent. */
    internal fun merge(other: LiveSignal): LiveSignal {
        if (resync || other.resync) return RESYNC
        val out = LinkedHashMap(changes)
        for ((topic, keys) in other.changes) {
            out[topic] = if (topic !in out) keys else out[topic]?.let { before -> keys?.let { before + it } }
        }
        return LiveSignal(out)
    }

    companion object {
        /** « Relis tout ce que tu montres. » */
        val RESYNC = LiveSignal(resync = true)

        /** Un signal à la main (les tests) : chaque sujet et ce qu'il nomme (`null` : tout le domaine). */
        fun of(vararg changes: Pair<String, Set<String>?>): LiveSignal = LiveSignal(linkedMapOf(*changes))
    }
}

/**
 * Le service du direct, un pour l'app (`AppGraph.live`) : la connexion lui donne chaque trame `changed` ([onChanged])
 * et chacune de ses ouvertures ([onOpened]) ; il réveille les écrans abonnés ([follow]), chacun pour ses sujets.
 *
 * - **Rien n'est rattrapé** : à chaque ouverture, la première comprise, chaque écran abonné reçoit
 *   [LiveSignal.RESYNC] et relit ce qu'il montre — au démarrage, l'écran a lu pendant la poignée de main, avant que la
 *   connexion l'écoute. Un écran qui n'est pas à l'écran (l'app au second plan, un autre écran par-dessus) n'est pas
 *   abonné : il se relit à son retour (`ui/shell/FollowLive`, qui relit aussi l'écran dont la première lecture a
 *   précédé une ouverture survenue avant son abonnement : [opens]).
 * - **Une rafale ne fait pas dix lectures** : un abonné traite un signal à la fois, jusqu'au bout (sa lecture finie) ;
 *   ce qui arrive pendant ce temps se réunit en un seul signal, traité après. Rien ne se perd, rien ne s'empile.
 * - Sûr depuis n'importe quel fil : la connexion l'appelle depuis le sien, les écrans le suivent depuis le leur.
 */
class Live {
    private class Subscriber(val topics: Set<String>) {
        private var pending: LiveSignal? = null
        val wake = Channel<Unit>(Channel.CONFLATED)

        fun offer(signal: LiveSignal) {
            val mine = signal.only(topics) ?: return
            synchronized(this) { pending = pending?.merge(mine) ?: mine }
            wake.trySend(Unit)
        }

        fun take(): LiveSignal? = synchronized(this) { pending.also { pending = null } }
    }

    private val subscribers = CopyOnWriteArraySet<Subscriber>()
    private val openings = AtomicLong(0)

    /** Une trame `changed`, déjà lue (`FrameCodec`) : chaque abonné en reçoit ce qui touche ses sujets. */
    fun onChanged(changes: Map<String, Set<String>?>) {
        if (changes.isEmpty()) return
        val signal = LiveSignal(changes)
        for (s in subscribers) s.offer(signal)
    }

    /** La connexion vient de s'ouvrir, la première fois comprise : chaque abonné relit tout ce qu'il montre. */
    fun onOpened() {
        openings.incrementAndGet()
        for (s in subscribers) s.offer(LiveSignal.RESYNC)
    }

    /** Combien d'ouvertures depuis le lancement : un écran qui a lu avant l'une d'elles sans être encore abonné l'a
     *  manquée, et relit à son abonnement (`ui/shell/FollowLive`). */
    val opens: Long get() = openings.get()

    /** Combien d'écrans suivent le direct en ce moment (les tests). */
    val followers: Int get() = subscribers.size

    /**
     * Suivre ces sujets tant que l'appelant n'est pas annulé : [ready] une fois abonné (la lecture qui ouvre ou qui
     * accompagne un retour : rien de ce qui change à partir de là ne lui échappe), puis [onSignal] pour chaque signal qui
     * les touche — un à la fois, ce qui arrive pendant l'un se réunit pour le suivant. Ne rend jamais la main d'elle-même.
     */
    suspend fun follow(topics: Set<String>, ready: () -> Unit = {}, onSignal: suspend (LiveSignal) -> Unit) {
        val unknown = topics - Topics.ALL.toSet()
        require(unknown.isEmpty()) { "sujets inconnus du direct : $unknown" }
        val me = Subscriber(topics)
        subscribers += me
        try {
            ready()
            for (wake in me.wake) {
                val signal = me.take() ?: continue
                onSignal(signal)
            }
        } finally {
            subscribers -= me
        }
    }
}

/**
 * Une lecture à la fois : redemandée pendant qu'elle est en vol, elle se refait une fois après (ce qui a changé
 * entre-temps a pu partir après elle) — une rafale de demandes, deux lectures au plus. Pour ce qui n'est pas un écran
 * abonné au direct (les pastilles, que relisent aussi les gestes) ; [run] ne suspend pas, [read] tourne dans [scope].
 */
class OneAtATime(private val scope: CoroutineScope, private val read: suspend () -> Unit) {
    private val lock = Any()
    private var busy = false
    private var again = false

    fun run() {
        synchronized(lock) {
            if (busy) {
                again = true
                return
            }
            busy = true
        }
        scope.launch {
            var done = false
            try {
                while (!done) {
                    read()
                    synchronized(lock) {
                        if (again) {
                            again = false
                        } else {
                            busy = false
                            done = true
                        }
                    }
                }
            } finally {
                // annulée, ou une lecture qui a levé : la suivante pourra repartir
                if (!done) synchronized(lock) {
                    busy = false
                    again = false
                }
            }
        }
    }

    /** Une lecture en vol. */
    val running: Boolean get() = synchronized(lock) { busy }
}
