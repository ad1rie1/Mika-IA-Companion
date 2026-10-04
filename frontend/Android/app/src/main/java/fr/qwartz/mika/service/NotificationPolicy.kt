package fr.qwartz.mika.service

import fr.qwartz.mika.data.chat.ChatEvent
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
import kotlinx.serialization.Serializable

/**
 * Quand une parole de Mika mérite une notification — une décision pure, pour que les règles se
 * testent sans système de notification. `MessageNotifier` ne fait qu'afficher ce qu'elle dit.
 */
object NotificationPolicy {
    /** Les dernières lignes montrées dans une notification groupée. */
    const val MAX_LINES = 5

    /** Ce que la notification garde en mémoire au plus (le reste n'est que compté). */
    const val MAX_KEPT = 50

    /** L'état au moment de décider. */
    data class Context(
        /** L'app est au premier plan : la personne voit déjà la conversation. */
        val foreground: Boolean,
        /** Le plus haut message lu (conversation ouverte) et le plus haut déjà notifié. */
        val lastReadId: Long,
        val lastNotifiedId: Long,
        /** Le curseur avant cette trame : 0 = toute première synchronisation (rien n'est « nouveau »). */
        val cursorBefore: Long,
    )

    /**
     * Notifier ce message ? Seulement hors premier plan ; une parole de Mika, pas un murmure, avec du
     * texte et un identifiant au-delà du lu et du notifié ; jamais à la toute première synchronisation
     * (l'historique d'une installation neuve n'est pas du courrier) ; et pour une parole en direct,
     * pas la réponse à une question posée depuis un autre appareil ([replyToOtherDevice]).
     */
    fun shouldNotify(message: StoredMessage, ctx: Context, replyToOtherDevice: Boolean = false): Boolean {
        if (ctx.foreground) return false
        if (message.sender != Sender.MIKA || message.inner) return false
        if (message.text.isBlank()) return false
        val id = message.id ?: return false
        if (id <= maxOf(ctx.lastReadId, ctx.lastNotifiedId)) return false
        if (ctx.cursorBefore <= 0) return false
        return !replyToOtherDevice
    }

    /**
     * Une parole en direct répond-elle à une question posée ailleurs ? Oui quand elle porte un
     * identifiant de corrélation qui n'est pas l'un des nôtres. Sans identifiant (elle écrit la
     * première), non.
     */
    fun isReplyToOtherDevice(clientMsgId: String?, isOwn: (String) -> Boolean): Boolean =
        clientMsgId != null && !isOwn(clientMsgId)

    data class Summary(val lines: List<String>, val more: Int)

    /** Un rattrapage = une notification : les [MAX_LINES] dernières lignes, et « et N autres ». */
    fun summarize(texts: List<String>, max: Int = MAX_LINES): Summary {
        val kept = texts.takeLast(max)
        return Summary(kept, texts.size - kept.size)
    }

    /** Une ligne de la notification : un message de Mika encore non lu. */
    @Serializable
    data class Line(val id: Long, val text: String, val ts: Long)

    /**
     * Ce qu'une annonce du fil devient. [notify] : les messages à ajouter à la notification ;
     * [lastNotifiedId] : le nouveau « dernier notifié » — il avance sur tout ce que l'annonce portait,
     * notifié ou non (premier plan, première synchronisation, réponse à un autre appareil) : un message
     * écarté une fois l'est pour de bon, il ne ressurgira pas au prochain rattrapage. [alertOnce] : un
     * rattrapage met à jour la notification sans resonner ; une parole en direct sonne.
     */
    data class Plan(val notify: List<StoredMessage>, val lastNotifiedId: Long, val alertOnce: Boolean)

    fun plan(event: ChatEvent.MikaSpoke, context: Context, isOwn: (String) -> Boolean): Plan {
        // Le curseur d'avant est celui de la trame : c'est elle qui sait si c'était la première synchronisation.
        val ctx = context.copy(cursorBefore = event.cursorBefore)
        val otherDevice = event.live && isReplyToOtherDevice(event.replyToClientMsgId, isOwn)
        val notify = event.messages.filter { m ->
            val elsewhere = m.id?.let { it in event.answeredElsewhere } == true
            shouldNotify(m, ctx, replyToOtherDevice = otherDevice || elsewhere)
        }.sortedBy { it.id }
        val highest = event.messages.mapNotNull { it.id }.maxOrNull() ?: 0L
        return Plan(notify, maxOf(ctx.lastNotifiedId, highest), alertOnce = !event.live)
    }

    /**
     * Les lignes de la notification après cet ajout : sans doublon, dans l'ordre du fil, sans ce qui a
     * été lu entre-temps, bornées à [MAX_KEPT].
     */
    fun merge(shown: List<Line>, added: List<StoredMessage>, lastReadId: Long): List<Line> {
        val byId = LinkedHashMap<Long, Line>()
        for (l in shown) byId[l.id] = l
        for (m in added) {
            val id = m.id ?: continue
            byId[id] = Line(id, m.text, m.ts)
        }
        return byId.values.filter { it.id > lastReadId }.sortedBy { it.id }.takeLast(MAX_KEPT)
    }
}
