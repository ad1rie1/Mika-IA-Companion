package fr.qwartz.mika.data.moi.mail

import fr.qwartz.mika.data.moi.Levels
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * Les formes de Mail dans l'API par personne (`backendv2/docs/protocole-moi.md` § 3). Chaque champ a son défaut :
 * `MikaJson` ignore ce qu'il ne connaît pas, et un champ absent ne casse rien. Les instants sont en millisecondes
 * (0 : jamais).
 */

/** Quand un mail ouvert devient lu (ADR 0175) : le client pose le geste `read` lui-même. */
object ReadOnOpen {
    const val NEVER = "jamais"
    const val AT_ONCE = "aussitot"

    /** Le délai avant de le marquer lu ; `null` : jamais. Une valeur inconnue vaut « jamais » (rien sans le vouloir). */
    fun delayMs(value: String): Long? = when (value) {
        AT_ONCE -> 0L
        "3s" -> 3_000L
        "10s" -> 10_000L
        else -> null
    }
}

@Serializable
data class MailFolder(
    val name: String = "",
    val label: String = "",
    /** `inbox`, `sent`, `drafts`, `archive`, `junk`, `trash`, ou vide (un autre dossier). */
    val role: String = "",
    /** Relevé par Mika : sinon, ses mails ne sont pas dans le cache. */
    val polled: Boolean = false,
    val total: Int = 0,
    val unseen: Int = 0,
) {
    val shown: String get() = label.ifBlank { name }
}

@Serializable
data class MailBox(
    val key: String = "",
    val name: String = "",
    val address: String = "",
    /** Le niveau le plus bas par défaut : une forme incomplète n'ouvre rien de plus que lire. */
    val level: String = Levels.READ,
    val ready: Boolean = false,
    @SerialName("can_send") val canSend: Boolean = false,
    val enabled: Boolean = true,
    /** Comment elle y écrit : `elle`, `assistante`, `proprietaire`. */
    val voice: String = "",
    val signature: String = "",
    @SerialName("last_poll") val lastPoll: Long = 0,
    val error: String = "",
    @SerialName("drafts_waiting") val draftsWaiting: Int = 0,
    /** Une boîte partagée : le nom de son propriétaire (« Boîte de Léa ») ; vide pour la sienne. */
    @SerialName("owner_name") val ownerName: String = "",
    /** « À toi » : commune à ses propriétaires. */
    val common: Boolean = false,
    val folders: List<MailFolder> = emptyList(),
) {
    val own: Boolean get() = level == Levels.OWNER
}

@Serializable
data class MailBoxes(
    val plugged: Boolean = true,
    @SerialName("read_on_open") val readOnOpen: String = ReadOnOpen.NEVER,
    /** L'instance a son application Microsoft (ADR 0238) : une boîte Microsoft s'ajoute sans donner la sienne. */
    @SerialName("microsoft_app") val microsoftApp: Boolean = false,
    val boxes: List<MailBox> = emptyList(),
)

@Serializable
data class MailPerson(val name: String = "", val address: String = "") {
    /** Son nom, sinon son adresse. */
    val shown: String get() = name.ifBlank { address }
}

/** Ce qu'elle a fait d'un mail, à part de ton non-lu (`seen`, le drapeau du serveur). */
@Serializable
data class HerMark(
    val noticed: Boolean = false,
    val important: Boolean = false,
    @SerialName("needs_reply") val needsReply: Boolean = false,
    /** Lu de son côté (`how` : « lu », « archivé », « corbeille »…). */
    val read: Boolean = false,
    val how: String = "",
    /** Un brouillon d'elle qui attend (son identifiant). */
    val draft: String = "",
    /** Une réponse qu'on lui a demandée, pas encore écrite. */
    val asked: Boolean = false,
    /** Ce qu'elle en a retenu (le mail entier seulement). */
    val summary: String = "",
)

@Serializable
data class MailRow(
    val ref: String = "",
    val box: String = "",
    val folder: String = "",
    val from: MailPerson = MailPerson(),
    val to: List<MailPerson> = emptyList(),
    val subject: String = "",
    val snippet: String = "",
    val date: Long = 0,
    /** Ton lu : le drapeau du serveur. Absent, le mail ne se dit pas non lu. */
    val seen: Boolean = true,
    val flagged: Boolean = false,
    val answered: Boolean = false,
    val attachments: Int = 0,
    val html: Boolean = false,
    val bulk: Boolean = false,
    val her: HerMark? = null,
)

@Serializable
data class MailPage(
    val total: Int = 0,
    val page: Int = 1,
    val size: Int = 25,
    val items: List<MailRow> = emptyList(),
)

/** Une pièce jointe d'un mail reçu ou parti ([part] : son numéro, pour `/mail/file`). */
@Serializable
data class MailPiece(val part: String = "", val name: String = "", val mime: String = "", val size: Long = 0)

@Serializable
data class MailImages(val remote: Boolean = false, val shown: Boolean = false)

/** Un mail entier (`/mail/message`). */
@Serializable
data class MailFull(
    val ref: String = "",
    val box: String = "",
    val folder: String = "",
    val from: MailPerson = MailPerson(),
    val to: List<MailPerson> = emptyList(),
    val cc: List<MailPerson> = emptyList(),
    val subject: String = "",
    val snippet: String = "",
    val date: Long = 0,
    val seen: Boolean = true,
    val flagged: Boolean = false,
    val answered: Boolean = false,
    val attachments: List<MailPiece> = emptyList(),
    val html: Boolean = false,
    val bulk: Boolean = false,
    val her: HerMark? = null,
    @SerialName("reply_to") val replyTo: String = "",
    @SerialName("in_reply_to") val inReplyTo: String = "",
    val body: String = "",
    /** Faux : la copie gardée n'en est qu'une partie. */
    val complete: Boolean = true,
    /** Parti d'une de ses boîtes (un envoi qu'elle sait, ou rangé dans « Envoyés »). */
    val sent: Boolean = false,
    /** Une copie reçue ailleurs que dans « Envoyés » (en copie à soi) : on y répond. */
    val received: Boolean = false,
    val images: MailImages = MailImages(),
)

/** Exactement ce qui partira (seulement tant qu'il attend). */
@Serializable
data class DraftPreview(
    val sender: String = "",
    val to: String = "",
    val cc: String = "",
    val subject: String = "",
    val text: String = "",
    /** À renvoyer pour l'envoyer tel qu'il a été lu. */
    val digest: String = "",
    /** Pourquoi il ne peut pas partir tel quel (un `[À COMPLÉTER`). */
    val blocked: String = "",
)

@Serializable
data class DraftOrigin(val subject: String = "", val from: String = "")

/** Les états d'un de ses brouillons. */
object DraftStates {
    const val WAITING = "attend"
    const val APPROVED = "approuve"
    const val SENT = "parti"
    const val REFUSED = "refuse"
    const val FAILED = "echec"
}

/** Un de ses brouillons (`/mail/drafts`, ADR 0191). */
@Serializable
data class MailDraft(
    val id: String = "",
    val box: String = "",
    val state: String = "",
    val at: Long = 0,
    @SerialName("decided_at") val decidedAt: Long = 0,
    val by: String = "",
    /** Ce qu'a dit qui a décidé. */
    val note: String = "",
    /** Le mail auquel il répond (sa référence). */
    @SerialName("in_reply_to") val inReplyTo: String = "",
    /** On le lui avait demandé (sinon d'elle-même). */
    val asked: Boolean = false,
    val voice: String = "",
    /** Faux : il attend l'accord du propriétaire de la boîte (une boîte qu'on te partage). */
    val decides: Boolean = false,
    val original: DraftOrigin? = null,
    /** Ses destinataires tels qu'on les retouche (le texte de l'en-tête). */
    val to: String = "",
    @SerialName("to_people") val toPeople: List<MailPerson> = emptyList(),
    val cc: String = "",
    val subject: String = "",
    val body: String = "",
    val quote: Boolean = false,
    val edited: Boolean = false,
    @SerialName("to_fill") val toFill: Boolean = false,
    val preview: DraftPreview? = null,
) {
    val waiting: Boolean get() = state == DraftStates.WAITING
}

@Serializable
data class MailDrafts(val items: List<MailDraft> = emptyList())

/** Ce qui est parti d'une de ses boîtes (`/mail/sent`). */
@Serializable
data class SentMail(
    val ref: String = "",
    val box: String = "",
    val to: List<MailPerson> = emptyList(),
    val cc: List<MailPerson> = emptyList(),
    val subject: String = "",
    val snippet: String = "",
    val date: Long = 0,
    /** Vide : elle, après un accord. */
    val by: String = "",
    val draft: String = "",
    val attachments: Int = 0,
)

@Serializable
data class SentMails(val items: List<SentMail> = emptyList())

/** Un correspondant (`/mail/contacts`), pour écrire. */
@Serializable
data class MailContact(
    val address: String = "",
    val name: String = "",
    val received: Int = 0,
    val sent: Int = 0,
    val last: Long = 0,
)

@Serializable
data class MailContacts(val items: List<MailContact> = emptyList())

/** Ce qu'une écriture a donné (`{"ok": true, "message": "…"}`), avec ce que certaines disent de plus. */
@Serializable
data class MailDone(
    val ok: Boolean = false,
    val message: String = "",
    val deduped: Boolean = false,
    /** `tidy` avec `move` : combien sont partis dans le dossier. */
    val moved: Int = 0,
    /** `prefill` : un brouillon d'elle qui attend déjà pour ce mail. */
    val draft: String = "",
    /** `prefill` : elle l'écrira à son prochain moment de travail. */
    val asked: Boolean = false,
)
