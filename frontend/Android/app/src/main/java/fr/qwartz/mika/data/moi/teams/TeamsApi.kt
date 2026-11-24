package fr.qwartz.mika.data.moi.teams

import fr.qwartz.mika.data.moi.Corrected
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.correct
import fr.qwartz.mika.data.moi.correctClient
import fr.qwartz.mika.data.moi.decode
import fr.qwartz.mika.data.moi.jsonOf
import fr.qwartz.mika.data.moi.map

/**
 * Teams par l'API par personne (`backendv2/docs/protocole-moi.md` § 4), sous le jeton du téléphone : ses comptes, ses
 * conversations et leurs fils, les réponses qu'elle y prépare ; écrire soi-même (ADR 0189), lui demander une réponse,
 * décider des siennes. Chaque écriture porte sa clé d'envoi ([key]) : le même geste redit ne refait rien. [corrections]
 * porte « Corriger » (ADR 0307) : la même API sur un client qui attend la fin d'une correction ([correctClient]).
 * Ouverte pour qu'une fausse API la remplace (les écrans sur la JVM).
 */
open class TeamsApi(private val api: MoiApi, private val corrections: MoiApi = api) {
    // ── Lire ──
    open suspend fun accounts(): MoiApi.Result<TeamsAccounts> = api.get("/teams/accounts", reader = TeamsAccounts.serializer())

    /** Ses conversations, la plus récente d'abord ; [account] : celles d'un compte ; [q] : celles qui s'appellent ainsi. */
    open suspend fun conversations(account: String = "", q: String = "", size: Int = TeamsLimits.CONVERSATIONS): MoiApi.Result<List<Conversation>> =
        api.get(
            "/teams/conversations",
            linkedMapOf("account" to account, "q" to q.trim(), "size" to size.toString()),
            Conversations.serializer(),
        ).map { it.items }

    /** Le fil d'une conversation, les plus récents ; [before] : ceux d'avant cet instant (ms). */
    open suspend fun thread(conversation: String, before: Long = 0, size: Int = TeamsLimits.PAGE): MoiApi.Result<ConversationThread> =
        api.get(
            "/teams/thread",
            linkedMapOf("conversation" to conversation, "before" to before.takeIf { it > 0 }?.toString(), "size" to size.toString()),
            ConversationThread.serializer(),
        )

    /** Où elle en est d'une réponse dans cette conversation (ADR 0306) : relu toutes les deux secondes tant qu'elle y
     *  travaille, sans relire le fil. */
    open suspend fun work(conversation: String): MoiApi.Result<TeamsWork> =
        api.get("/teams/work", mapOf("conversation" to conversation), TeamsWork.serializer())

    /** Ses réponses dans tes comptes (ADR 0191), la plus récente d'abord. */
    open suspend fun replies(): MoiApi.Result<List<TeamsReply>> =
        api.get("/teams/replies", reader = TeamsReplies.serializer()).map { it.items }

    // ── Écrire ──
    /** Ton message (ADR 0189) : en file pour l'extension du compte, qui l'envoie sous le nom de sa personne ; [replyTo] :
     *  la référence du message que tu cites (le serveur fait la citation dans Teams, ADR 0305). */
    open suspend fun send(conversation: String, body: String, replyTo: String = "", key: String? = MoiApi.newKey()): MoiApi.Result<TeamsDone> =
        write("/teams/send", listOf("conversation" to conversation, "body" to body) + optional("reply_to", replyTo), key)

    /** « Préremplir avec Mika » : elle s'y met tout de suite (ADR 0306) et prépare une réponse à ce message ; une réponse
     *  déjà en chemin rend `draft`, une demande déjà faite `asked` (le serveur le dit dans `message`). */
    open suspend fun prefill(message: String, instruction: String = "", key: String? = MoiApi.newKey()): MoiApi.Result<TeamsDone> =
        write("/teams/prefill", listOf("message" to message) + optional("instruction", instruction), key)

    /** L'envoyer telle qu'elle a été lue ([seen] : le `digest` de son aperçu). */
    open suspend fun replySend(id: String, seen: String, key: String? = MoiApi.newKey()): MoiApi.Result<TeamsDone> =
        write("/teams/reply/send", listOf("id" to id, "seen" to seen), key)

    /** Ta version remplace la sienne (elle apprendra de la différence). */
    open suspend fun replyEdit(id: String, body: String, key: String? = MoiApi.newKey()): MoiApi.Result<TeamsDone> =
        write("/teams/reply/edit", listOf("id" to id, "body" to body), key)

    /** Elle ne partira pas ; elle le saura ([note] : pourquoi, si tu veux). */
    open suspend fun replyRefuse(id: String, note: String = "", key: String? = MoiApi.newKey()): MoiApi.Result<TeamsDone> =
        write("/teams/reply/refuse", listOf("id" to id, "note" to note), key)

    /** La refuser, et qu'elle en écrive une autre selon [instruction]. */
    open suspend fun replyRedo(id: String, instruction: String, key: String? = MoiApi.newKey()): MoiApi.Result<TeamsDone> =
        write("/teams/reply/redo", listOf("id" to id, "instruction" to instruction), key)

    /** « Corriger » (ADR 0307) : les fautes de ton message, sans changer ses mots (`/api/moi/correct`). */
    open suspend fun correct(text: String): MoiApi.Result<Corrected> = corrections.correct(text)

    private fun optional(name: String, value: String): List<Pair<String, Any>> =
        if (value.isBlank()) emptyList() else listOf(name to value)

    private suspend fun write(path: String, fields: List<Pair<String, Any>>, key: String?): MoiApi.Result<TeamsDone> =
        api.post(path, jsonOf(fields), key).decode(TeamsDone.serializer())
}
