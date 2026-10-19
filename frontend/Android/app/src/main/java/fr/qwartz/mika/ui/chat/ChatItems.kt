package fr.qwartz.mika.ui.chat

import fr.qwartz.mika.data.chat.ChatSync
import fr.qwartz.mika.data.chat.MessageStatus
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
import fr.qwartz.mika.data.chat.WorkCard
import fr.qwartz.mika.data.chat.WorkText
import fr.qwartz.mika.data.net.MessageNote
import fr.qwartz.mika.data.net.MikaProtocol
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/** Une ligne de la conversation telle que l'écran la dessine, avec une clé stable pour la liste. */
sealed interface ChatItem {
    val key: String

    data class DateSeparator(override val key: String, val label: String) : ChatItem

    data object TruncatedNote : ChatItem {
        override val key = "truncated"
    }

    /**
     * Une bulle. [read] : un message envoyé que Mika a lu — elle a répondu depuis, ou choisi de se
     * taire (double coche). [part] : une des bulles d'une réponse de Mika (une ligne vide les sépare,
     * ADR 0112) — null, tout le message ; [last] : la dernière, qui porte ses fichiers et l'heure.
     * [toolsLine] : sous une réponse pro relue sans sa carte de travail, ses outils (« a ✓ · b ✗ », ADR 0116).
     */
    data class Bubble(
        override val key: String,
        val message: StoredMessage,
        val read: Boolean,
        val part: String? = null,
        val last: Boolean = true,
        val toolsLine: String? = null,
    ) : ChatItem

    /**
     * Sa carte de travail pendant une réponse pro (ADR 0116) : ses outils en direct, après le message de la
     * personne ; [folded] une fois sa réponse arrivée, repliée en un résumé juste au-dessus d'elle.
     */
    data class Work(override val key: String, val card: WorkCard, val folded: Boolean) : ChatItem

    /**
     * Une note de la machine sous une bulle — jamais une parole de Mika. [resendLocalId] : sous une
     * réponse qui n'est pas venue, la bulle à redemander (« Le lui redemander »).
     */
    data class Note(
        override val key: String,
        val text: String,
        val href: String? = null,
        val resendLocalId: Long? = null,
    ) : ChatItem

    /**
     * Une petite bulle juste avant sa réponse : ce qu'elle a fait en l'écrivant (ADR 0119 : elle a regardé où tu es,
     * [note] le lieu et de quand datait la position). [messageTs] : l'heure de sa réponse, à laquelle la position se
     * compare (« position de 14:10 »).
     */
    data class Looked(override val key: String, val note: MessageNote, val messageTs: Long) : ChatItem

    /** Une pensée à voix haute : éphémère, en italique. */
    data class Thought(override val key: String, val message: StoredMessage) : ChatItem

    /** Une réponse ratée sans message à qui la rattacher (`source: "error"`). */
    data class SystemNote(override val key: String, val text: String) : ChatItem

    data object Typing : ChatItem {
        override val key = "typing"
    }
}

/**
 * Construire la liste à dessiner, du plus ancien au plus récent : séparateurs de date, note de
 * troncature, bulles et leurs notes, ses petites bulles, pensées, cartes de travail, « Mika écrit… ». Pur : l'heure et le
 * fuseau sont passés, pour que les tests ne dépendent pas de l'horloge.
 */
object ChatItems {
    private val DAY = DateTimeFormatter.ofPattern("EEEE d MMMM", Locale.FRENCH)
    private val DAY_YEAR = DateTimeFormatter.ofPattern("EEEE d MMMM yyyy", Locale.FRENCH)

    fun build(
        messages: List<StoredMessage>,
        ephemeral: List<StoredMessage> = emptyList(),
        truncated: Boolean = false,
        typing: Boolean = false,
        nowMs: Long,
        zone: ZoneId,
        /** Ses cartes de travail (ADR 0116), en mémoire seulement. */
        work: List<WorkCard> = emptyList(),
    ): List<ChatItem> {
        val all = ChatSync.sortMessages((messages + ephemeral).toMutableList())
        val out = ArrayList<ChatItem>(all.size * 2 + 2)
        if (truncated) out += ChatItem.TruncatedNote
        val cards = placeWork(all, work)

        // « lu » : une parole de Mika (pas un murmure) vient après ce message — ou elle s'est tue (`seen`).
        val answeredAfter = BooleanArray(all.size)
        var seenReply = false
        for (i in all.indices.reversed()) {
            answeredAfter[i] = seenReply
            if (all[i].sender == Sender.MIKA && !all[i].inner) seenReply = true
        }

        val today = Instant.ofEpochMilli(nowMs).atZone(zone).toLocalDate()
        var runningMax = Long.MIN_VALUE
        var previousDay: LocalDate? = null
        for ((i, m) in all.withIndex()) {
            // Un maximum courant : un message relu plus tôt dans l'ordre, mais horodaté plus tard, ne
            // fait pas revenir la date en arrière.
            runningMax = maxOf(runningMax, m.ts)
            val day = Instant.ofEpochMilli(runningMax).atZone(zone).toLocalDate()
            if (day != previousDay) {
                out += ChatItem.DateSeparator("d$day", dayLabel(day, today))
                previousDay = day
            }
            val key = keyOf(m)
            // sa carte de travail, repliée juste au-dessus de sa réponse pro
            val above = if (m.sender == Sender.MIKA) m.id?.let { cards.aboveAnswer[it] } else null
            if (above != null) out += ChatItem.Work(above.key, above, folded = true)
            // ses petites bulles (ADR 0119), juste avant la première bulle de sa réponse : les sortes connues seulement
            if (m.sender == Sender.MIKA && !m.inner && !isSystemNote(m)) {
                m.notes?.forEachIndexed { n, note ->
                    if (note.kind == MikaProtocol.NOTE_LOCATION) out += ChatItem.Looked("l$key.$n", note, m.ts)
                }
            }
            when {
                m.inner -> out += ChatItem.Thought(key, m)
                isSystemNote(m) -> out += ChatItem.SystemNote(key, m.text)
                // une réponse pro : une seule bulle, ses outils dits en une ligne si sa carte n'est plus là
                m.sender == Sender.MIKA && m.isPro -> out += ChatItem.Bubble(
                    key,
                    m,
                    read = false,
                    toolsLine = m.tools?.takeIf { it.isNotEmpty() && above == null }?.let(WorkText::toolsLine),
                )
                // sa réponse en plusieurs bulles, comme quelqu'un qui écrit : la première garde la clé du message
                m.sender == Sender.MIKA && BubbleContent.parts(m.text).size > 1 -> {
                    val parts = BubbleContent.parts(m.text)
                    parts.forEachIndexed { n, part ->
                        out += ChatItem.Bubble(if (n == 0) key else "$key.$n", m, read = false, part = part,
                            last = n == parts.lastIndex)
                    }
                }
                else -> out += ChatItem.Bubble(
                    key,
                    m,
                    read = m.sender == Sender.USER && m.status == MessageStatus.SENT &&
                        (answeredAfter[i] || m.waiting == ChatSync.SEEN),
                )
            }
            m.note?.let { out += ChatItem.Note("n$key", it) }
            val replyNote = m.replyNote
            if (replyNote != null) {
                // Une bulle encore à écrire (sans clé locale) n'a rien à redemander.
                val resend = m.localId.takeIf { it > 0L && m.sender == Sender.USER && m.status == MessageStatus.SENT }
                out += ChatItem.Note("r$key", replyNote, ChatSync.consoleHref(m.replyHref), resend)
            } else if (ChatSync.asleepNoteShown(all, i)) {
                out += ChatItem.Note("s$key", ChatSync.ASLEEP_NOTE)
            }
            // sa carte de travail en cours, sous le message auquel elle répond
            if (m.sender == Sender.USER) {
                m.id?.let { cards.afterUser[it] }?.forEach { out += ChatItem.Work(it.key, it, folded = it.answered) }
            }
        }
        cards.atEnd.forEach { out += ChatItem.Work(it.key, it, folded = false) }
        // la carte de travail tient la place de « Mika écrit… »
        if (typing && !cards.live) out += ChatItem.Typing
        return out
    }

    /** Où va chaque carte de travail : au-dessus de sa réponse, sous le message auquel elle répond, ou en bas. */
    private class Placement(
        val aboveAnswer: Map<Long, WorkCard>,
        val afterUser: Map<Long, List<WorkCard>>,
        val atEnd: List<WorkCard>,
        /** Une carte attend encore sa réponse (elle travaille, ou a fini sans encombre) : « Mika écrit… » ne s'ajoute pas. */
        val live: Boolean,
    )

    /**
     * Une carte dont la réponse est dans le fil se replie au-dessus d'elle ; sinon elle suit le message de la
     * personne (quand il a déjà son identifiant) ; sinon, en attente de sa réponse, elle va en bas du fil — juste
     * après le message qui vient de partir. Une carte répondue qui n'a plus où se mettre ne se montre pas.
     */
    private fun placeWork(all: List<StoredMessage>, work: List<WorkCard>): Placement {
        if (work.isEmpty()) return Placement(emptyMap(), emptyMap(), emptyList(), live = false)
        val answers = all.filter { it.sender == Sender.MIKA && !it.inner }.mapNotNullTo(HashSet()) { it.id }
        val asked = all.filter { it.sender == Sender.USER }.mapNotNullTo(HashSet()) { it.id }
        val aboveAnswer = HashMap<Long, WorkCard>()
        val afterUser = LinkedHashMap<Long, MutableList<WorkCard>>()
        val atEnd = ArrayList<WorkCard>()
        var live = false
        for (card in work) {
            val answerId = card.answerId
            val replyTo = card.replyTo
            when {
                card.answered && answerId != null && answerId in answers && answerId !in aboveAnswer ->
                    aboveAnswer[answerId] = card
                replyTo != null && replyTo in asked -> {
                    afterUser.getOrPut(replyTo) { ArrayList() } += card
                    if (awaited(card)) live = true
                }
                !card.answered -> {
                    atEnd += card
                    if (awaited(card)) live = true
                }
            }
        }
        return Placement(aboveAnswer, afterUser, atEnd, live)
    }

    /** Sa réponse est attendue : elle travaille, ou l'épisode a fini sans encombre (la `speech` peut suivre le `done`). */
    private fun awaited(card: WorkCard): Boolean =
        !card.answered && (card.running || card.outcome == MikaProtocol.TOOL_OUTCOME_DONE)

    fun dayLabel(day: LocalDate, today: LocalDate): String = when (day) {
        today -> "Aujourd'hui"
        today.minusDays(1) -> "Hier"
        else -> (if (day.year == today.year) DAY else DAY_YEAR).format(day)
    }

    private fun isSystemNote(m: StoredMessage) =
        m.sender == Sender.MIKA && m.id == null && m.source == MikaProtocol.SOURCE_ERROR

    private fun keyOf(m: StoredMessage): String = when {
        m.localId != 0L -> "m${m.localId}"
        m.id != null -> "s${m.id}"
        m.cid != null -> "c${m.cid}"
        else -> "t${m.ts}-${m.text.hashCode()}"
    }
}
