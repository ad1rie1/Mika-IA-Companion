package fr.qwartz.mika.data.files

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.net.MikaProtocol
import kotlinx.serialization.Serializable

/**
 * Ce qui attend dans la barre de saisie : le texte tapé et les fichiers déjà copiés dans la
 * préparation. Gardé en base (`kv`, clé `draft`) : une app tuée ne perd ni la phrase ni les photos.
 * Le même objet transporte un partage reçu (`kv`, clé `shared_inbox`), avec ce qu'il faut en dire.
 */
@Serializable
data class ComposerDraft(
    val text: String = "",
    val files: List<StagedFile> = emptyList(),
    /** Ce que la préparation a écarté ou réduit (un partage) ; jamais gardé dans le brouillon. */
    val notices: List<String> = emptyList(),
) {
    val isEmpty: Boolean get() = text.isEmpty() && files.isEmpty()

    fun encode(): String = MikaJson.encodeToString(serializer(), this)

    /** Fondre ce qu'apporte un partage dans ce qui est déjà là. */
    data class Merge(val draft: ComposerDraft, val dropped: List<StagedFile>, val notices: List<String>)

    /**
     * Le texte partagé s'ajoute à la ligne (borné à la limite d'un message) ; les fichiers s'ajoutent
     * jusqu'à cinq — ceux de trop sont rendus ([Merge.dropped], à effacer du disque) et comptés.
     */
    fun merge(incoming: ComposerDraft): Merge {
        val notices = incoming.notices.toMutableList()
        val joined = when {
            incoming.text.isBlank() -> text
            text.isBlank() -> incoming.text
            else -> text.trimEnd() + "\n" + incoming.text
        }
        val bounded = joined.take(MikaProtocol.MAX_MESSAGE_CHARS)
        if (bounded.length < joined.length) notices += "Texte partagé coupé à ${MikaProtocol.MAX_MESSAGE_CHARS} caractères."
        val room = (MikaProtocol.MAX_ATTACHMENTS - files.size).coerceAtLeast(0)
        val kept = incoming.files.take(room)
        val dropped = incoming.files.drop(room)
        if (dropped.isNotEmpty()) notices += AttachmentPolicy.tooMany(dropped.size)
        return Merge(ComposerDraft(bounded, files + kept), dropped, notices)
    }

    companion object {
        /** Illisible (une version future, une écriture coupée) → un brouillon vide, jamais une erreur. */
        fun decode(raw: String?): ComposerDraft {
            if (raw.isNullOrBlank()) return ComposerDraft()
            return try {
                MikaJson.decodeFromString(serializer(), raw)
            } catch (_: IllegalArgumentException) {
                ComposerDraft()
            }
        }
    }
}
