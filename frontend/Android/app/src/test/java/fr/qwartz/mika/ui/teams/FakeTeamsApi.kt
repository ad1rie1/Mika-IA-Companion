package fr.qwartz.mika.ui.teams

import fr.qwartz.mika.data.moi.Corrected
import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.teams.ConversationThread
import fr.qwartz.mika.data.moi.teams.TeamsAccount
import fr.qwartz.mika.data.moi.teams.TeamsAccounts
import fr.qwartz.mika.data.moi.teams.TeamsApi
import fr.qwartz.mika.data.moi.teams.TeamsDone
import fr.qwartz.mika.data.moi.teams.TeamsWork
import kotlinx.coroutines.CompletableDeferred
import okhttp3.OkHttpClient

/**
 * Une fausse API de Teams pour les écrans : ses comptes, des fils en mémoire (par clé de conversation), ce que chaque
 * envoi a porté, où elle en est (ADR 0306) et les lectures faites, et des barrières — un appel retenu ne répond que
 * quand le test le lâche, avec ce qu'il avait lu au moment de la demande.
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

    /** Ce que rend « Préremplir ». */
    var prefillResult: MoiApi.Result<TeamsDone> = MoiApi.Result.Ok(TeamsDone(ok = true, message = "Demandé : elle la préparera.", asked = true))

    /** Ce que rend `/teams/work`, si le test l'impose (sinon : ce que dit le fil en mémoire). */
    var workResult: MoiApi.Result<TeamsWork>? = null

    /** Les lectures, dans l'ordre (« thread:19:marc », « work:19:marc », « prefill:m1 »). */
    val calls = mutableListOf<String>()

    private val gates = HashMap<String, CompletableDeferred<Unit>>()

    /** Retenir le prochain appel de ce nom (`thread`, `send`, `correct`). */
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
        calls += "thread:$conversation"
        val t = threads[conversation] ?: return answer("thread", MoiApi.Result.Failed(MoiError(404, "Introuvable : ce n'est plus là.")))
        // une page d'avant : rien de plus ancien que ce que le fil a
        val page = if (before > 0) t.copy(messages = t.messages.filter { it.at < before }, more = false) else t
        return answer("thread", MoiApi.Result.Ok(page))
    }

    override suspend fun work(conversation: String): MoiApi.Result<TeamsWork> {
        calls += "work:$conversation"
        val got = workResult ?: threads[conversation]?.let { MoiApi.Result.Ok(TeamsWork(it.work, it.asked, it.underWay)) }
            ?: MoiApi.Result.Failed(MoiError(404, "Introuvable : ce n'est plus là."))
        return answer("work", got)
    }

    override suspend fun prefill(message: String, instruction: String, key: String?): MoiApi.Result<TeamsDone> {
        calls += "prefill:$message"
        return answer("prefill", prefillResult)
    }

    override suspend fun send(conversation: String, body: String, replyTo: String, key: String?): MoiApi.Result<TeamsDone> {
        sends += Sent(conversation, body, replyTo, key)
        return answer("send", sendResult)
    }

    /** Ce que rend « Corriger » (ADR 0307) pour le texte reçu ; sinon : rien à corriger, le texte tel quel. */
    var correctResult: (String) -> MoiApi.Result<Corrected> = { MoiApi.Result.Ok(Corrected(it, 0)) }

    /** Les textes partis à « Corriger », dans l'ordre. */
    val corrections = mutableListOf<String>()

    override suspend fun correct(text: String): MoiApi.Result<Corrected> {
        corrections += text
        return answer("correct", correctResult(text))
    }
}
