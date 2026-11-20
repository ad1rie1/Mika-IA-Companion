package fr.qwartz.mika.ui.mail

import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.mail.MailApi
import fr.qwartz.mika.data.moi.mail.MailBox
import fr.qwartz.mika.data.moi.mail.MailBoxes
import fr.qwartz.mika.data.moi.mail.MailDone
import fr.qwartz.mika.data.moi.mail.MailDraft
import fr.qwartz.mika.data.moi.mail.MailFull
import fr.qwartz.mika.data.moi.mail.MailPage
import fr.qwartz.mika.data.moi.mail.MailRow
import fr.qwartz.mika.data.moi.mail.Outgoing
import fr.qwartz.mika.data.moi.mail.OutgoingPiece
import kotlinx.coroutines.CompletableDeferred
import okhttp3.OkHttpClient

/**
 * Une fausse API de Mail pour les écrans : un petit serveur en mémoire (ses boîtes, ses mails, ses brouillons, une
 * réception paginée), et des barrières — un appel retenu ne répond que quand le test le lâche, avec ce qu'il avait lu
 * au moment de la demande (le serveur a répondu avant ce qui se passe ensuite).
 */
class FakeMailApi : MailApi(MoiApi(OkHttpClient(), { null }, {})) {
    var boxes = MailBoxes(
        boxes = listOf(
            MailBox(key = "pro", name = "Atelier", address = "moi@atelier.fr", level = Levels.OWNER, ready = true, canSend = true),
            MailBox(key = "perso", name = "Perso", address = "moi@perso.fr", level = Levels.OWNER, ready = true, canSend = true),
        ),
    )
    val mails = HashMap<String, MailFull>()
    var drafts: List<MailDraft> = emptyList()
    /** La réception, dans l'ordre du serveur ; un rangement en ôte ce qui s'en va. */
    var inbox: MutableList<MailRow> = mutableListOf()

    /** Ce qu'une lecture ou une écriture rend, si le test l'impose (sinon ce que le faux serveur sait). */
    var draftsFail: MoiError? = null
    /** Un rangement refusé par le serveur : rien ne bouge. */
    var tidyFail: MoiError? = null
    var sendResult: MoiApi.Result<MailDone> = MoiApi.Result.Ok(MailDone(ok = true, message = "Parti."))
    var prefillResult: MoiApi.Result<MailDone> = MoiApi.Result.Ok(MailDone(ok = true, asked = true))

    /** Les appels, dans l'ordre (« reply », « draftSend:d1 », « messages:1:50 », « tidy:move:INBOX »…). */
    val calls = mutableListOf<String>()

    private val gates = HashMap<String, CompletableDeferred<Unit>>()

    /** Retenir le prochain appel de ce nom (`boxes`, `message:<ref>`, `drafts`, `prefill`, `send`, `tidy`, `messages`). */
    fun hold(name: String) {
        gates[name] = CompletableDeferred()
    }

    /** Le lâcher : il répond ce qu'il avait lu en arrivant. */
    fun release(name: String) {
        gates.remove(name)?.complete(Unit)
    }

    private suspend fun <T> answer(name: String, value: T): T {
        gates[name]?.await()
        return value
    }

    override suspend fun boxes(): MoiApi.Result<MailBoxes> = answer("boxes", MoiApi.Result.Ok(boxes))

    override suspend fun message(ref: String): MoiApi.Result<MailFull> {
        val got = mails[ref]?.let { MoiApi.Result.Ok(it) } ?: MoiApi.Result.Failed(MoiError(404, "Introuvable : ce n'est plus là."))
        return answer("message:$ref", got)
    }

    override suspend fun drafts(): MoiApi.Result<List<MailDraft>> {
        calls += "drafts"
        val got = draftsFail?.let { MoiApi.Result.Failed(it) } ?: MoiApi.Result.Ok(drafts)
        return answer("drafts", got)
    }

    override suspend fun messages(query: Map<String, String?>): MoiApi.Result<MailPage> {
        val page = query["page"]!!.toInt()
        val size = query["size"]!!.toInt()
        calls += "messages:$page:$size"
        val items = inbox.drop((page - 1) * size).take(size)
        return answer("messages", MoiApi.Result.Ok(MailPage(total = inbox.size, page = page, size = size, items = items)))
    }

    override suspend fun send(box: String, mail: Outgoing, files: List<OutgoingPiece>, key: String?): MoiApi.Result<MailDone> {
        calls += "send:$box"
        return answer("send", sendResult)
    }

    override suspend fun reply(ref: String, mail: Outgoing, quote: Boolean, files: List<OutgoingPiece>, key: String?): MoiApi.Result<MailDone> {
        calls += "reply:$ref"
        return answer("send", sendResult)
    }

    override suspend fun draftEdit(id: String, mail: Outgoing, quote: Boolean, key: String?): MoiApi.Result<MailDone> {
        calls += "draftEdit:$id"
        return answer("draftEdit", MoiApi.Result.Ok(MailDone(ok = true, message = "Ta version est enregistrée.")))
    }

    override suspend fun draftSend(id: String, seen: String, key: String?): MoiApi.Result<MailDone> {
        calls += "draftSend:$id"
        return answer("send", sendResult)
    }

    override suspend fun tidy(refs: List<String>, gesture: String, folder: String, key: String?): MoiApi.Result<MailDone> {
        calls += if (folder.isEmpty()) "tidy:$gesture" else "tidy:$gesture:$folder"
        tidyFail?.let { return answer("tidy", MoiApi.Result.Failed(it)) }
        if (gesture == "archive" || gesture == "trash" || gesture == "move") inbox.removeAll { it.ref in refs }
        return answer("tidy", MoiApi.Result.Ok(MailDone(ok = true, message = "C'est fait.")))
    }

    override suspend fun prefill(ref: String, instruction: String, key: String?): MoiApi.Result<MailDone> {
        calls += "prefill:$ref"
        return answer("prefill", prefillResult)
    }

    /** Un cadre refusé par le serveur (sinon : le HTML du mail s'il en a, 404 sans). */
    var frameFail: MoiError? = null

    override suspend fun frame(ref: String, images: Boolean): MoiApi.Result<String> {
        calls += if (images) "frame:$ref:images" else "frame:$ref"
        val m = mails[ref]
        val got = frameFail?.let { MoiApi.Result.Failed(it) }
            ?: if (m != null && m.html) MoiApi.Result.Ok("<!doctype html><meta charset=\"utf-8\"><p>${m.subject}</p>") else MoiApi.Result.Failed(MoiError(404, "Introuvable : ce n'est plus là."))
        return answer("frame", got)
    }

    override suspend fun images(ref: String, shown: Boolean, key: String?): MoiApi.Result<MailDone> {
        calls += "images:$ref:$shown"
        return answer("images", MoiApi.Result.Ok(MailDone(ok = true)))
    }
}
