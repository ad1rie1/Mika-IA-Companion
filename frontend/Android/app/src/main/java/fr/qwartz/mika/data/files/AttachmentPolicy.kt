package fr.qwartz.mika.data.files

import fr.qwartz.mika.data.net.ChatFrameWriter
import fr.qwartz.mika.data.net.MikaProtocol
import java.text.NumberFormat
import java.util.Locale

/**
 * Ce qu'on peut joindre, et ce qu'on dit de ce qui ne passe pas — avant que rien ne quitte le
 * téléphone : un fichier refusé ici n'atteindra jamais le serveur, aucun accusé ne le dirait.
 * Formules reprises du client web (ChatOverlay.ts `handleFiles`).
 */
object AttachmentPolicy {

    /** Le résultat d'un ajout : ce qui est retenu, et ce qu'il faut en dire. */
    data class Admission<T>(val accepted: List<T>, val notices: List<String>)

    /**
     * Ajouter des fichiers à ceux déjà joints. [sizeOf] et [nameOf] lisent un candidat ; un candidat
     * de taille négative est illisible.
     */
    fun <T> admit(alreadyAttached: Int, candidates: List<T>, nameOf: (T) -> String, sizeOf: (T) -> Long): Admission<T> {
        val notices = mutableListOf<String>()
        val room = (MikaProtocol.MAX_ATTACHMENTS - alreadyAttached).coerceAtLeast(0)
        val dropped = candidates.size - room
        if (dropped > 0) notices += tooMany(dropped)
        val accepted = mutableListOf<T>()
        for (c in candidates.take(room)) {
            val size = sizeOf(c)
            when {
                size < 0 -> notices += unreadable(nameOf(c))
                size > MikaProtocol.MAX_FILE_BYTES -> notices += tooLarge(nameOf(c), size)
                else -> accepted += c
            }
        }
        return Admission(accepted, notices)
    }

    /** « 2 fichiers ignorés : maximum 5 pièces jointes. » */
    fun tooMany(dropped: Int): String = if (dropped > 1) {
        "$dropped fichiers ignorés : maximum ${MikaProtocol.MAX_ATTACHMENTS} pièces jointes."
    } else {
        "1 fichier ignoré : maximum ${MikaProtocol.MAX_ATTACHMENTS} pièces jointes."
    }

    /** « photo.jpg ignoré : 7,2 Mo (maximum 5 Mo). » */
    fun tooLarge(name: String, size: Long): String =
        "$name ignoré : ${formatSize(size)} (maximum ${formatSize(MikaProtocol.MAX_FILE_BYTES)})."

    fun unreadable(name: String): String = "$name illisible : non joint."

    /** Une photo réduite pour passer : on le dit, la personne n'enverra pas l'original. */
    fun reduced(name: String, toFitMessage: Boolean): String =
        if (toFitMessage) "$name réduite pour tenir dans un seul message." else "$name réduite pour tenir sous 5 Mo."

    /** « 312 o », « 12 Ko », « 7,2 Mo » : la taille d'une pièce jointe, sous sa puce. */
    fun humanSize(bytes: Long): String = when {
        bytes < 1024 -> "$bytes o"
        bytes < 1024 * 1024 -> "${(bytes + 512) / 1024} Ko"
        else -> formatSize(bytes)
    }

    const val TOO_HEAVY = "Trop lourd pour un seul message (11 Mo de fichiers au plus) : envoie le reste à part."

    /** Pourquoi ce message ne peut pas partir tel quel, ou `null` s'il le peut. */
    fun checkSend(text: String, files: List<StagedFile>): String? {
        if (text.isEmpty() && files.isEmpty()) return "Message vide."
        if (text.length > MikaProtocol.MAX_MESSAGE_CHARS) {
            return "Message trop long : ${MikaProtocol.MAX_MESSAGE_CHARS} caractères au plus."
        }
        if (files.size > MikaProtocol.MAX_ATTACHMENTS) {
            return "${MikaProtocol.MAX_ATTACHMENTS} pièces jointes au plus."
        }
        files.firstOrNull { it.size > MikaProtocol.MAX_FILE_BYTES }?.let { return tooLarge(it.name, it.size) }
        val total = files.sumOf { it.size }
        val frame = ChatFrameWriter.base64Length(total) + text.length * 6L + 4096
        if (total > MikaProtocol.MAX_FILES_BYTES_PER_MESSAGE || frame > MikaProtocol.MAX_FRAME_BYTES) return TOO_HEAVY
        return null
    }

    /** « 7,2 Mo » — un refus qui donne la taille dit du même coup pourquoi. */
    fun formatSize(bytes: Long): String {
        val format = NumberFormat.getNumberInstance(Locale.FRANCE).apply { maximumFractionDigits = 1 }
        return "${format.format(bytes / (1024.0 * 1024.0))} Mo"
    }

    /** La sorte d'une pièce jointe, d'après son type (`protocol.py::Attachment.kind`). */
    fun kindOf(mime: String): String = when (mime.substringBefore('/')) {
        "image" -> "image"
        "audio" -> "audio"
        else -> "file"
    }
}
