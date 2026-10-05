package fr.qwartz.mika.ui.chat

import fr.qwartz.mika.data.chat.ChatSync
import fr.qwartz.mika.data.chat.MessageStatus
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
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

    /** Une bulle. [read] : un message envoyé auquel Mika a répondu depuis (double coche). */
    data class Bubble(override val key: String, val message: StoredMessage, val read: Boolean) : ChatItem

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
 * troncature, bulles et leurs notes, pensées, « Mika écrit… ». Pur : l'heure et le fuseau sont
 * passés, pour que les tests ne dépendent pas de l'horloge.
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
    ): List<ChatItem> {
        val all = ChatSync.sortMessages((messages + ephemeral).toMutableList())
        val out = ArrayList<ChatItem>(all.size * 2 + 2)
        if (truncated) out += ChatItem.TruncatedNote

        // « lu » : une parole de Mika (pas un murmure) vient après ce message.
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
            when {
                m.inner -> out += ChatItem.Thought(key, m)
                isSystemNote(m) -> out += ChatItem.SystemNote(key, m.text)
                else -> out += ChatItem.Bubble(
                    key,
                    m,
                    read = m.sender == Sender.USER && m.status == MessageStatus.SENT && answeredAfter[i],
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
        }
        if (typing) out += ChatItem.Typing
        return out
    }

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
