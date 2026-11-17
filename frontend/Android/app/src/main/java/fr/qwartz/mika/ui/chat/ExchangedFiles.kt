package fr.qwartz.mika.ui.chat

import fr.qwartz.mika.data.chat.MessageAttachment
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
import fr.qwartz.mika.data.files.AttachmentPolicy
import fr.qwartz.mika.data.files.MikaFileRefs
import fr.qwartz.mika.data.moi.MoiDates
import java.time.ZoneId

/** Les puces de « Fichiers échangés » : tout, les siens (ce qu'elle t'a envoyé), les tiens. */
enum class FilesChip { ALL, HERS, YOURS }

/**
 * Un fichier échangé dans la conversation (ADR 0215) : la pièce, le message qui la porte (pour « Voir dans la
 * conversation »), à qui elle est. [fetchable] : elle se reprend au serveur (`/files/<id>`, « Enregistrer », « Ouvrir
 * avec… », l'image en grand) ; [removed] : le serveur ne la garde plus ; [local] : une des tiennes encore sur ce
 * téléphone (sa vignette), envoyée d'ici.
 */
data class ExchangedFile(
    val key: String,
    val message: StoredMessage,
    val att: MessageAttachment,
    val hers: Boolean,
    val image: Boolean,
    val fetchable: Boolean,
    val removed: Boolean,
    val local: Boolean,
) {
    val ts: Long get() = message.ts
}

/**
 * La liste des fichiers échangés, portée de `frontendv2/src/screens/chat/markup.ts::filesTable` : les siens et les
 * tiens, du plus récent au plus ancien, tant que le serveur les garde ; les images en grille, les documents en liste.
 * Pur : les messages, l'instant et le fuseau sont passés.
 */
object ExchangedFiles {
    /** Tous les fichiers des messages gardés sur le téléphone (fils de travail compris), le plus récent d'abord. */
    fun of(messages: List<StoredMessage>): List<ExchangedFile> {
        val out = ArrayList<ExchangedFile>()
        for (m in messages.sortedByDescending { it.ts }) {
            if (m.inner) continue
            val hers = m.sender == Sender.MIKA
            m.attachments.forEachIndexed { i, att ->
                val path = MikaFileRefs.path(att)
                val removed = MikaFileRefs.isRemoved(att)
                // une pièce sans de quoi la reprendre ni la montrer ne se liste pas (un vieux message d'un autre appareil)
                val local = !hers && m.cid != null && att.local != null
                if (path == null && !local && !removed) return@forEachIndexed
                out += ExchangedFile(
                    key = "${ChatItems.keyOf(m)}#$i",
                    message = m,
                    att = att,
                    hers = hers,
                    image = MikaFileRefs.isImage(att),
                    fetchable = path != null && !removed,
                    removed = removed,
                    local = local,
                )
            }
        }
        return out
    }

    fun filter(files: List<ExchangedFile>, chip: FilesChip): List<ExchangedFile> = when (chip) {
        FilesChip.ALL -> files
        FilesChip.HERS -> files.filter { it.hers }
        FilesChip.YOURS -> files.filter { !it.hers }
    }

    /** « 212 Ko · Mika · aujourd'hui 13:31 », « toi · hier 21:41 · plus disponible ». */
    fun detail(file: ExchangedFile, nowMs: Long, zone: ZoneId): String = listOfNotNull(
        file.att.size?.takeIf { it > 0 }?.let(AttachmentPolicy::humanSize),
        if (file.hers) "Mika" else "toi",
        MoiDates.dayAndClock(file.ts, nowMs, zone).ifEmpty { null },
        when {
            file.removed -> "plus disponible"
            !file.fetchable -> "sur ce téléphone seulement"
            else -> null
        },
    ).joinToString(" · ")
}
