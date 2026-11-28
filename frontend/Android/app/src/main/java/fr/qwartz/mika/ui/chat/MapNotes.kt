package fr.qwartz.mika.ui.chat

import fr.qwartz.mika.data.moi.carte.MapNoteKind
import fr.qwartz.mika.data.net.MessageNote

/**
 * Une note de carte d'un de ses messages, validée (ADR 0196 ; `protocole-chat.md` § 4) : elle a cherché des lieux ou
 * calculé un trajet ([kind] `look`), montré une carte (`map`), créé ou changé un voyage (`trip`). [text] : ce qu'elle a
 * cherché, le titre de la carte ou du voyage ; [at] : l'instant du regard, ou du dernier changement du voyage (ms ; 0 :
 * inconnu) ; [ref] : le `seq` du regard ou de la carte, l'identifiant du voyage.
 */
data class MapNote(val kind: String, val text: String, val at: Long, val ref: String) {
    /** Ce que la miniature garde d'une lecture à l'autre : `trip:640`, `look:812` (celle de `MiniRef.id`). */
    val id: String get() = "$kind:$ref"
}

/**
 * Lire et valider les notes de carte d'un message, portées de `frontend/Web/src/map/notes.ts::mapNotes` sans changer ses
 * règles : les trois sortes seulement (la bulle 📍, `location`, reste à [ChatItems]) ; une sorte inconnue s'ignore ; une
 * note vidée (un regard oublié, un voyage supprimé : `text` vide, pas de `ref`) ne montre rien ; `ref` en chiffres ;
 * le texte sur une ligne, 300 caractères au plus ; sans doublon (même sorte, même `ref`) ; six au plus.
 */
object MapNotes {
    /** Une réponse ne porte pas des dizaines de cartes. */
    const val MAX = 6
    const val MAX_TEXT = 300

    /** Des chiffres, comme les identifiants du serveur (le `seq` d'un événement). */
    private val REF = Regex("^\\d{1,18}$")
    private val SPACES = Regex("\\s+")

    fun read(notes: List<MessageNote>?): List<MapNote> {
        if (notes.isNullOrEmpty()) return emptyList()
        val out = ArrayList<MapNote>()
        for (n in notes) {
            if (n.kind !in MapNoteKind.ALL) continue
            val text = n.text.take(MAX_TEXT).replace(SPACES, " ").trim()
            val ref = n.ref.trim()
            if (text.isEmpty() || !REF.matches(ref)) continue // oubliée, supprimée : rien à montrer
            if (out.any { it.kind == n.kind && it.ref == ref }) continue
            out += MapNote(n.kind, text, n.at.takeIf { it > 0 } ?: 0L, ref)
            if (out.size >= MAX) break
        }
        return out
    }
}
