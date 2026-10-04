package fr.qwartz.mika.share

import fr.qwartz.mika.data.net.MikaProtocol

/** Ce qu'un `Intent` de partage porte, lu sans Android (testable sur la JVM). */
data class ShareInput(
    val action: String?,
    val type: String?,
    val text: String?,
    val subject: String?,
    /** Les adresses des flux (`EXTRA_STREAM` et `ClipData`), telles quelles. */
    val streams: List<String>,
)

/** Ce que Mika recevra : un texte à mettre dans la barre de saisie, des fichiers à copier, et quoi en dire. */
data class ShareRequest(val text: String?, val streams: List<String>, val notices: List<String>)

/**
 * « Partager vers Mika » : lire ce qu'une autre application envoie. Seuls `SEND` et `SEND_MULTIPLE`
 * comptent ; un texte seul pré-remplit la saisie ; les fichiers sont copiés tout de suite (ailleurs).
 *
 * Seuls les flux `content://` d'une autre application sont acceptés : un `file://` — ou un `content://`
 * de notre propre fournisseur — pourrait désigner nos fichiers privés (la base, le jeton) et les faire
 * partir vers le serveur sous couvert d'un partage.
 */
object ShareParser {
    const val ACTION_SEND = "android.intent.action.SEND"
    const val ACTION_SEND_MULTIPLE = "android.intent.action.SEND_MULTIPLE"

    fun parse(input: ShareInput, ownAuthorities: Set<String>): ShareRequest? {
        if (input.action != ACTION_SEND && input.action != ACTION_SEND_MULTIPLE) return null
        val notices = mutableListOf<String>()
        val streams = mutableListOf<String>()
        var refused = 0
        for (raw in input.streams) {
            val uri = raw.trim()
            if (uri.isEmpty() || uri in streams) continue
            if (isForeignContent(uri, ownAuthorities)) streams += uri else refused++
        }
        if (refused > 0) {
            notices += if (refused > 1) "$refused fichiers refusés : source non autorisée." else "1 fichier refusé : source non autorisée."
        }
        var text = composeText(input.text, input.subject)
        if (text != null && text.length > MikaProtocol.MAX_MESSAGE_CHARS) {
            text = text.take(MikaProtocol.MAX_MESSAGE_CHARS)
            notices += "Texte partagé coupé à ${MikaProtocol.MAX_MESSAGE_CHARS} caractères."
        }
        if (streams.isEmpty() && text == null) {
            return if (notices.isEmpty()) null else ShareRequest(null, emptyList(), notices)
        }
        return ShareRequest(text, streams, notices)
    }

    /**
     * Un navigateur partage une page comme un sujet (son titre) et un texte (son adresse) : les deux
     * servent. Un sujet déjà contenu dans le texte n'est pas répété.
     */
    private fun composeText(text: String?, subject: String?): String? {
        val t = text?.trim().orEmpty()
        val s = subject?.trim().orEmpty()
        return when {
            t.isEmpty() && s.isEmpty() -> null
            t.isEmpty() -> s
            s.isEmpty() || t.contains(s) -> t
            else -> "$s\n$t"
        }
    }

    fun isForeignContent(uri: String, ownAuthorities: Set<String>): Boolean {
        if (!uri.startsWith("content://", ignoreCase = true)) return false
        val authority = uri.substring("content://".length).substringBefore('/').substringAfterLast('@').lowercase()
        if (authority.isEmpty()) return false
        return ownAuthorities.none { it.equals(authority, ignoreCase = true) }
    }
}
