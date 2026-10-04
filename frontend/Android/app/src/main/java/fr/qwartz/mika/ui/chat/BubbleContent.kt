package fr.qwartz.mika.ui.chat

import fr.qwartz.mika.data.chat.MessageStatus
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
import fr.qwartz.mika.ui.components.InlineMarkup
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * Ce qu'une bulle écrit et ce qu'elle dit à un lecteur d'écran. Pur, pour que les tests n'aient pas
 * besoin d'un écran : l'heure et le fuseau sont passés.
 */
object BubbleContent {
    private val TIME = DateTimeFormatter.ofPattern("HH:mm", Locale.FRENCH)

    /**
     * Le texte de la bulle. Un message de la personne avec des fichiers est enregistré
     * `texte [a.png, b.pdf]` (la même composition que le serveur) ; ici les fichiers ont leurs puces,
     * la bulle n'écrit que ce qui a été tapé.
     */
    fun text(m: StoredMessage): String {
        if (m.sender != Sender.USER || m.attachments.isEmpty()) return m.text
        m.matchText?.let { return it }
        val label = "[" + m.attachments.map { it.name }.filter { it.isNotEmpty() }.joinToString(", ") + "]"
        return when {
            m.text == label -> ""
            m.text.endsWith(" $label") -> m.text.removeSuffix(" $label")
            else -> m.text
        }
    }

    /** « 21:04 » sous la bulle. */
    fun time(ts: Long, zone: ZoneId): String = TIME.format(Instant.ofEpochMilli(ts).atZone(zone))

    /** « 21 h 04 » : ce qu'un lecteur d'écran prononce bien, contrairement à « 21:04 ». */
    fun spokenTime(ts: Long, zone: ZoneId): String {
        val t = Instant.ofEpochMilli(ts).atZone(zone)
        return "${t.hour} h ${t.minute.toString().padStart(2, '0')}"
    }

    /** L'état d'un message envoyé, en mots ; `null` pour une parole de Mika. */
    fun status(m: StoredMessage, read: Boolean): String? {
        if (m.sender != Sender.USER) return null
        return when {
            m.status == MessageStatus.PENDING -> "en attente d'envoi"
            m.status == MessageStatus.FAILED -> "refusé — ${m.reason ?: "refusé par le serveur"}"
            read -> "lu"
            else -> "envoyé"
        }
    }

    /**
     * Une bulle = un nœud pour le lecteur d'écran : « Toi, 21 h 04, envoyé : salut » ou
     * « Mika, 21 h 05 : coucou. Fichiers : liste.md ».
     */
    fun describe(m: StoredMessage, read: Boolean, zone: ZoneId): String {
        val who = if (m.sender == Sender.USER) "Toi" else "Mika"
        val head = listOfNotNull(who, spokenTime(m.ts, zone), status(m, read)).joinToString(", ")
        val body = InlineMarkup.plain(text(m))
        val files = m.attachments.map { it.name }.filter { it.isNotEmpty() }
        val tail = if (files.isEmpty()) "" else (if (body.isEmpty()) "" else ". ") + "Fichiers : " + files.joinToString(", ")
        return "$head : $body$tail"
    }
}
