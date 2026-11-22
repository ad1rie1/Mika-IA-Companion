package fr.qwartz.mika.ui.teams

import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.teams.ConversationThread
import fr.qwartz.mika.data.moi.teams.TeamsAccount
import fr.qwartz.mika.data.moi.teams.TeamsAccounts
import fr.qwartz.mika.data.moi.teams.TeamsApi
import fr.qwartz.mika.data.moi.teams.TeamsDone
import kotlinx.coroutines.CompletableDeferred
import okhttp3.OkHttpClient

/**
 * Une fausse API de Teams pour les écrans : ses comptes, des fils en mémoire (par clé de conversation), ce que chaque
 * envoi a porté, et des barrières — un appel retenu ne répond que quand le test le lâche, avec ce qu'il avait lu au
 * moment de la demande.
 */
class FakeTeamsApi : TeamsApi(MoiApi(OkHttpClient(), { null }, {})) {
    var accounts = TeamsAccounts(
        accounts = listOf(TeamsAccount(key = "principal", name = "Atelier", level = Levels.OWNER, selfName = "Adrien Moreau")),
    )
    val threads = HashMap<String, ConversationThread>()

    /** Ce que rend un envoi, si le test l'impose. */
    var sendResult: MoiApi.Result<TeamsDone> = MoiApi.Result.Ok(TeamsDone(ok = true, message = "En file : l'extension l'enverra dans Teams."))

    /** Un envoi tel qu'il est parti : sa conversation, son texte, le message qu'il cite (`reply_to`), sa clé. */
    data class Sent(val conversation: String, val body: String, val replyTo: String, val key: String?)

    val sends = mutableListOf<Sent>()

    private val gates = HashMap<String, CompletableDeferred<Unit>>()

    /** Retenir le prochain appel de ce nom (`thread`, `send`). */
    fun hold(name: String) {
        gates[name] = CompletableDeferred()
    }

    fun release(name: String) {
        gates.remove(name)?.complete(Unit)
    }

    private suspend fun <T> answer(name: String, value: T): T {
        gates[name]?.await()
        return value
    }

    override suspend fun accounts(): MoiApi.Result<TeamsAccounts> = MoiApi.Result.Ok(accounts)

    override suspend fun thread(conversation: String, before: Long, size: Int): MoiApi.Result<ConversationThread> {
        val t = threads[conversation] ?: return answer("thread", MoiApi.Result.Failed(MoiError(404, "Introuvable : ce n'est plus là.")))
        // une page d'avant : rien de plus ancien que ce que le fil a
        val page = if (before > 0) t.copy(messages = t.messages.filter { it.at < before }, more = false) else t
        return answer("thread", MoiApi.Result.Ok(page))
    }

    override suspend fun send(conversation: String, body: String, replyTo: String, key: String?): MoiApi.Result<TeamsDone> {
        sends += Sent(conversation, body, replyTo, key)
        return answer("send", sendResult)
    }
}
