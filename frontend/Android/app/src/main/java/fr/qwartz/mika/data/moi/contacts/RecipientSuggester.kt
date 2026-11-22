package fr.qwartz.mika.data.moi.contacts

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.chars
import fr.qwartz.mika.data.moi.mail.MailApi
import fr.qwartz.mika.data.moi.mail.MailLimits

/**
 * Les destinataires proposés quand on écrit un mail (la maquette validée, `ecrans/contacts.js` : « Écrire ») : **tous
 * tes contacts** (`GET /contacts?q=`, § 12), plus seulement tes correspondants du courrier, une ligne par adresse, une
 * adresse générique marquée ([proposals]). Quand l'annuaire n'est pas là — pas branché (503), ou un serveur qui n'a pas
 * encore la route (404) —, tes correspondants (`GET /mail/contacts?q=`, § 3), comme avant ; une autre panne (le
 * réseau) ne propose rien.
 */
class RecipientSuggester(private val directory: ContactsApi?, private val mail: MailApi) {
    suspend fun lookup(text: String, chosen: Set<String>): List<RecipientProposal> {
        val q = text.trim()
        if (q.isEmpty()) return emptyList()
        if (directory != null && chars(q) <= ContactsLimits.SEARCH) {
            when (val got = directory.page(q = q, size = LOOKUP)) {
                is MoiApi.Result.Ok -> return proposals(got.value.items, chosen)
                is MoiApi.Result.Failed -> if (got.error.code != 503 && got.error.code != 404) return emptyList()
            }
        }
        if (chars(q) > MailLimits.CONTACTS) return emptyList()
        return when (val got = mail.contacts(q, PROPOSED + 4)) {
            is MoiApi.Result.Ok -> proposalsFromMail(got.value, chosen)
            is MoiApi.Result.Failed -> emptyList()
        }
    }

    companion object {
        /** Les contacts lus pour une recherche : plus que ce qu'on propose (un contact du téléphone n'a pas d'adresse). */
        const val LOOKUP = 20
    }
}
