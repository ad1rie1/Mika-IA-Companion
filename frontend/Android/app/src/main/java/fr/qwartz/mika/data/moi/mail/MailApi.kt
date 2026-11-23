package fr.qwartz.mika.data.moi.mail

import fr.qwartz.mika.data.moi.Corrected
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.correct
import fr.qwartz.mika.data.moi.decode
import fr.qwartz.mika.data.moi.jsonOf
import fr.qwartz.mika.data.moi.map
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.RequestBody

/** Une pièce qu'on joint à un mail qui part : son nom, son type, sa taille, et son contenu, lu au moment de partir. */
class OutgoingPiece(
    override val name: String,
    val mime: String,
    override val size: Long,
    val body: () -> RequestBody,
) : Sized

/** Une pièce du mail qu'on transfère : elle compte dans les bornes de ce qu'on y ajoute. */
private class Carried(override val name: String, override val size: Long) : Sized

/** Les pièces d'origine d'un transfert, pour [addPieces]. */
fun carriedPieces(m: MailFull): List<Sized> = m.attachments.map { Carried(it.name, it.size) }

/**
 * Mail par l'API par personne (`backendv2/docs/protocole-moi.md` § 3), sous le jeton du téléphone : ses boîtes et
 * leurs dossiers, une page de messages, un mail entier, ses brouillons, ses envoyés, ses correspondants ; écrire,
 * répondre, transférer (en JSON, ou en `multipart` avec des fichiers), ranger, lui demander une réponse, décider de ses
 * brouillons, relever. [uploads] porte les envois avec des pièces : sans délai global, 50 Mo ne passent pas en 60 s
 * sur une 4G faible. Ouverte : un test JVM des écrans de Mail la remplace par une fausse, qui répond quand il veut.
 */
open class MailApi(private val api: MoiApi, private val uploads: MoiApi = api) {
    // ── Lire ──
    open suspend fun boxes(): MoiApi.Result<MailBoxes> = api.get("/mail/boxes", reader = MailBoxes.serializer())

    open suspend fun messages(query: Map<String, String?>): MoiApi.Result<MailPage> =
        api.get("/mail/messages", query, MailPage.serializer())

    open suspend fun message(ref: String): MoiApi.Result<MailFull> =
        api.get("/mail/message", mapOf("ref" to ref), MailFull.serializer())

    /** Où elle en est d'une réponse à ce mail (ADR 0306) : relu toutes les deux secondes tant qu'elle y travaille,
     *  sans relire le mail ni joindre son serveur. */
    open suspend fun work(ref: String): MoiApi.Result<MailWork> =
        api.get("/mail/work", mapOf("ref" to ref), MailWork.serializer())

    open suspend fun drafts(): MoiApi.Result<List<MailDraft>> =
        api.get("/mail/drafts", reader = MailDrafts.serializer()).map { it.items }

    open suspend fun sent(box: String = ""): MoiApi.Result<List<SentMail>> =
        api.get("/mail/sent", mapOf("box" to box), SentMails.serializer()).map { it.items }

    open suspend fun contacts(q: String, size: Int = 10, box: String = ""): MoiApi.Result<List<MailContact>> =
        api.get("/mail/contacts", mapOf("q" to q, "box" to box, "size" to size.toString()), MailContacts.serializer()).map { it.items }

    /** Une pièce jointe, toujours en téléchargement : son adresse sur le serveur de la session (`null` hors session). */
    fun fileUrl(ref: String, part: String): HttpUrl? = api.url("/mail/file", mapOf("ref" to ref, "part" to part))

    /** Le HTML du mail, purgé, son document isolé (ADR 0169), pour [fr.qwartz.mika.ui.mail.MailFrame] ; [images] :
     *  ses images distantes, cette fois. Un mail sans HTML : 404. */
    open suspend fun frame(ref: String, images: Boolean = false): MoiApi.Result<String> =
        api.text("/mail/frame", mapOf("ref" to ref, "images" to if (images) "1" else null))

    /** Les images distantes de son expéditeur : toujours ([shown]), ou plus (ADR 0175) ; seule une propriétaire. */
    open suspend fun images(ref: String, shown: Boolean, key: String? = MoiApi.newKey()) =
        json("/mail/images", listOf("ref" to ref, "shown" to shown), key)

    // ── Écrire ──
    /** Un mail nouveau ; il part tout de suite. */
    open suspend fun send(box: String, mail: Outgoing, files: List<OutgoingPiece> = emptyList(), key: String? = MoiApi.newKey()) =
        write("/mail/send", listOf("box" to box) + fieldsOf(mail), files, key)

    /** Une réponse, depuis la boîte du mail reçu ; [quote] : citer le mail. */
    open suspend fun reply(ref: String, mail: Outgoing, quote: Boolean, files: List<OutgoingPiece> = emptyList(), key: String? = MoiApi.newKey()) =
        write("/mail/reply", listOf("ref" to ref) + fieldsOf(mail) + ("quote" to quote), files, key)

    /** Le transférer ; [attachments] : ses pièces avec, et [files] en plus. */
    open suspend fun forward(ref: String, mail: Outgoing, attachments: Boolean, files: List<OutgoingPiece> = emptyList(), key: String? = MoiApi.newKey()) =
        write("/mail/forward", listOf("ref" to ref) + fieldsOf(mail) + ("attachments" to attachments), files, key)

    /** Un geste sur le serveur (`read`, `unread`, `archive`, `flag`, `unflag`, `trash`), ou `move` dans [folder]. */
    open suspend fun tidy(refs: List<String>, gesture: String, folder: String = "", key: String? = MoiApi.newKey()): MoiApi.Result<MailDone> {
        val body = buildMap {
            put("refs", JsonArray(refs.map(::JsonPrimitive)))
            put("gesture", JsonPrimitive(gesture))
            if (folder.isNotEmpty()) put("folder", JsonPrimitive(folder))
        }
        return api.post("/mail/tidy", JsonObject(body), key).decode(MailDone.serializer())
    }

    /** « Préremplir avec Mika » : elle s'y met tout de suite (`asked`, ADR 0306 ; où elle en est : [work]), ou un
     *  brouillon attend déjà (`draft`). */
    open suspend fun prefill(ref: String, instruction: String = "", key: String? = MoiApi.newKey()) =
        json("/mail/prefill", listOf("ref" to ref) + (if (instruction.isNotBlank()) listOf("instruction" to instruction) else emptyList()), key)

    /** L'envoyer tel qu'il a été lu ([seen] : le `digest` de son aperçu). */
    open suspend fun draftSend(id: String, seen: String, key: String? = MoiApi.newKey()) =
        json("/mail/draft/send", listOf("id" to id, "seen" to seen), key)

    /** Ta version remplace la sienne (la sienne est gardée : elle apprendra). */
    open suspend fun draftEdit(id: String, mail: Outgoing, quote: Boolean, key: String? = MoiApi.newKey()) =
        json("/mail/draft/edit", listOf("id" to id, "to" to mail.to, "cc" to mail.cc, "subject" to mail.subject, "body" to mail.body, "quote" to quote), key)

    /** Il ne partira pas ; elle le saura ([note] : pourquoi, si tu veux). */
    open suspend fun draftRefuse(id: String, note: String = "", key: String? = MoiApi.newKey()) =
        json("/mail/draft/refuse", listOf("id" to id, "note" to note), key)

    /** Le refuser, et qu'elle en écrive un autre selon [instruction]. */
    open suspend fun draftRedo(id: String, instruction: String, key: String? = MoiApi.newKey()) =
        json("/mail/draft/redo", listOf("id" to id, "instruction" to instruction), key)

    /** Relever sans attendre, par une boîte que tu peux relever. */
    open suspend fun poll(box: String, key: String? = MoiApi.newKey()) = json("/mail/poll", listOf("box" to box), key)

    /** « Corriger » (ADR 0307) : les fautes de ton texte, sans changer ses mots (`/api/moi/correct`). */
    open suspend fun correct(text: String): MoiApi.Result<Corrected> = api.correct(text)

    private fun fieldsOf(mail: Outgoing): List<Pair<String, Any>> =
        listOf("to" to mail.to, "cc" to mail.cc, "bcc" to mail.bcc, "subject" to mail.subject, "body" to mail.body)

    private suspend fun json(path: String, fields: List<Pair<String, Any>>, key: String?): MoiApi.Result<MailDone> =
        api.post(path, jsonOf(fields), key).decode(MailDone.serializer())

    /** Sans fichier, en JSON ; avec, en `multipart/form-data` — les mêmes champs (protocole § 3, ADR 0214). */
    private suspend fun write(path: String, fields: List<Pair<String, Any>>, files: List<OutgoingPiece>, key: String?): MoiApi.Result<MailDone> =
        if (files.isEmpty()) {
            json(path, fields, key)
        } else {
            uploads.postForm(path, formOf(fields, files), key).decode(MailDone.serializer())
        }

    companion object {
        /** Le corps `multipart` : un champ vide ou faux ne part pas, un vrai vaut `1` (comme le formulaire du web) ;
         *  chaque fichier sous `files`. */
        internal fun formOf(fields: List<Pair<String, Any>>, files: List<OutgoingPiece>): MultipartBody {
            val b = MultipartBody.Builder().setType(MultipartBody.FORM)
            for ((k, v) in fields) {
                when (v) {
                    is Boolean -> if (v) b.addFormDataPart(k, "1")
                    else -> v.toString().takeIf { it.isNotEmpty() }?.let { b.addFormDataPart(k, it) }
                }
            }
            for (f in files) b.addFormDataPart("files", f.name, PieceBody(f))
            return b.build()
        }
    }
}

/** Le contenu d'une pièce, sous le type qu'elle annonce (le serveur juge ce qu'elle vaut). */
private class PieceBody(private val piece: OutgoingPiece) : RequestBody() {
    private val inner by lazy { piece.body() }
    override fun contentType() = piece.mime.toMediaTypeOrNull() ?: inner.contentType()
    override fun contentLength(): Long = inner.contentLength()
    override fun writeTo(sink: okio.BufferedSink) = inner.writeTo(sink)
}
