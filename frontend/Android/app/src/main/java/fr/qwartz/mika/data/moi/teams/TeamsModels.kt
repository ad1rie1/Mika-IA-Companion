package fr.qwartz.mika.data.moi.teams

import fr.qwartz.mika.data.moi.Levels
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * Les formes de Teams dans l'API par personne (`backendv2/docs/protocole-moi.md` § 4, code `app/me/teams.py`). Chaque
 * champ a son défaut : `MikaJson` ignore ce qu'il ne connaît pas, et un champ absent ne casse rien. Les instants sont en
 * millisecondes (0 : jamais). Une conversation se désigne par sa clé (`<compte>~<identifiant>`, l'identifiant seul
 * pour le compte `principal`), un message par sa référence (`ref`).
 */

/** La clé de l'extension d'un compte, jamais en clair. */
@Serializable
data class ExtensionKey(val hint: String = "", @SerialName("created_at") val createdAt: Long = 0)

/** Un de ses comptes Teams : le sien, ou un compte qu'on lui partage à son niveau (ADR 0188). */
@Serializable
data class TeamsAccount(
    val key: String = "",
    val name: String = "",
    /** Le niveau le plus bas par défaut : une forme incomplète n'ouvre rien de plus que lire. */
    val level: String = Levels.READ,
    /** Coché : Mika y lit, et ce qui en part passe. */
    val enabled: Boolean = true,
    /** Le dernier lot de son extension (0 : jamais). */
    @SerialName("last_batch") val lastBatch: Long = 0,
    /** Le nom de qui y est connecté, dans Teams. */
    @SerialName("self_name") val selfName: String = "",
    /** `null` : pas de clé, ou un compte qui ne t'est que partagé. */
    @SerialName("extension_key") val extensionKey: ExtensionKey? = null,
    /** Ses réponses qui attendent une décision (0 en lecture seule). */
    @SerialName("drafts_waiting") val draftsWaiting: Int = 0,
    /** Un compte partagé : le nom de son propriétaire ; vide pour le sien. */
    @SerialName("owner_name") val ownerName: String = "",
    /** « À toi » : commun à ses propriétaires. */
    val common: Boolean = false,
) {
    /** Le tien (ou « à toi ») : ce qui y est écrit par la personne du compte, c'est toi. */
    val own: Boolean get() = level == Levels.OWNER
}

@Serializable
data class TeamsAccounts(
    /** Le serveur a Teams. */
    val plugged: Boolean = true,
    /** Teams actif. */
    val enabled: Boolean = true,
    val accounts: List<TeamsAccount> = emptyList(),
)

/** Les sortes d'une conversation. */
object Kinds {
    const val DM = "dm"
    const val GROUP = "group"
    const val CHANNEL = "channel"
    const val MEETING = "meeting"
    const val OTHER = "other"
}

/** Un message d'une conversation. */
@Serializable
data class TeamsMessage(
    val ref: String = "",
    val author: String = "",
    @SerialName("author_id") val authorId: String = "",
    val at: Long = 0,
    val text: String = "",
    /** Écrit par la personne du compte : toi sur un compte à toi, son propriétaire sur un compte qu'on te partage. */
    val own: Boolean = false,
    @SerialName("mentions_me") val mentionsMe: Boolean = false,
)

/** Une réponse de Mika en chemin dans une conversation. */
@Serializable
data class UnderWay(val state: String = "", val draft: String = "")

/** Une conversation de la liste. */
@Serializable
data class Conversation(
    val key: String = "",
    val account: String = "",
    /** Son nom : celui de Teams, sinon (un tête-à-tête) l'autre personne ; vide si rien ne la nomme. */
    val title: String = "",
    val kind: String = Kinds.OTHER,
    @SerialName("last_at") val lastAt: Long = 0,
    val messages: Int = 0,
    /** Son dernier message, texte coupé. */
    val last: TeamsMessage? = null,
    /** Sa réponse en chemin (toujours `null` en lecture seule, et pour une réponse à laquelle on a répondu autrement). */
    val her: UnderWay? = null,
)

@Serializable
data class Conversations(val items: List<Conversation> = emptyList())

/** Les états d'une de ses réponses. */
object ReplyStates {
    /** Attend ta décision. */
    const val WAITING = "attend"
    const val APPROVED = "approuve"
    /** En file pour l'extension. */
    const val QUEUED = "en_file"
    /** Posée dans la zone de saisie de Teams. */
    const val PLACED = "pose"
    const val SENT = "parti"
    /** Pas servie à temps. */
    const val UNUSED = "inutilise"
    const val REFUSED = "refuse"
    const val EXPIRED = "expire"
    const val FAILED = "echec"
}

/** Comment part ce qu'elle prépare : posé dans Teams, après ton accord, seule. */
object ReplyModes {
    const val DRAFT = "brouillon"
    const val APPROVAL = "validation"
    const val ALONE = "autonome"
}

/** Exactement ce qui partira, tant qu'elle attend (signature comprise). */
@Serializable
data class ReplyPreview(
    val text: String = "",
    /** À renvoyer pour l'envoyer telle qu'elle a été lue. */
    val digest: String = "",
    /** Pourquoi elle ne peut pas partir telle quelle (un `[À COMPLÉTER`). */
    val blocked: String = "",
)

/** Une réponse qu'elle a préparée dans un de tes comptes (ADR 0191), et ce qu'elle est devenue. */
@Serializable
data class TeamsReply(
    val id: String = "",
    val account: String = "",
    /** La clé de sa conversation. */
    val conversation: String = "",
    val title: String = "",
    /** Le message auquel elle répond (sa référence). */
    @SerialName("in_reply_to") val inReplyTo: String = "",
    val state: String = "",
    val mode: String = "",
    val at: Long = 0,
    @SerialName("decided_at") val decidedAt: Long = 0,
    val by: String = "",
    /** Ce qu'a dit qui l'a refusée (sur un compte à toi seulement). */
    val note: String = "",
    /** Demandée (« Préremplir avec Mika »), sinon d'elle-même. */
    val asked: Boolean = false,
    /** Ta version a remplacé la sienne. */
    val edited: Boolean = false,
    /** Une carte d'accord : jusqu'à quand elle vaut (0 : sans délai). */
    val expires: Long = 0,
    /** La personne du compte a répondu autrement dans la discussion : elle ne partira pas (ADR 0199). */
    val answered: Boolean = false,
    val body: String = "",
    /** Ce qui est vraiment parti. */
    @SerialName("sent_text") val sentText: String = "",
    @SerialName("to_fill") val toFill: Boolean = false,
    val preview: ReplyPreview? = null,
) {
    val waiting: Boolean get() = state == ReplyStates.WAITING
}

@Serializable
data class TeamsReplies(val items: List<TeamsReply> = emptyList())

/** Ce que devient un message que tu as écrit toi-même (ADR 0189), tant qu'il n'est pas revenu dans le fil. */
object OwnStates {
    const val QUEUED = "en_file"
    const val SENDING = "envoi"
    const val PLACED = "pose"
    /** Jamais parti : l'extension ne l'a pas relevé à temps (montré un jour). */
    const val UNUSED = "inutilise"
    const val FAILED = "echec"
}

/** Un message que tu as écrit et qui n'est pas (encore) dans le fil. */
@Serializable
data class OwnPending(
    val id: String = "",
    val body: String = "",
    /** Quand tu l'as écrit. */
    val at: Long = 0,
    val state: String = "",
    /** Qui l'a écrit (son adresse `user_N`). */
    val by: String = "",
    /** Pourquoi il n'est pas parti, quand le moteur le dit. */
    val reason: String = "",
)

/** Le fil d'une conversation (`/teams/thread`) : les plus récents, et ses réponses à elle. */
@Serializable
data class ConversationThread(
    val key: String = "",
    val account: String = "",
    val title: String = "",
    val kind: String = Kinds.OTHER,
    val messages: List<TeamsMessage> = emptyList(),
    /** Il y a des messages plus anciens (`before`). */
    val more: Boolean = false,
    /** Ses réponses ici, la plus récente d'abord (vides en lecture seule). */
    val replies: List<TeamsReply> = emptyList(),
    /** Ce que tu y as écrit toi-même et qui n'est pas (encore) dans le fil ; `null` : un moteur qui ne le dit pas. */
    val pending: List<OwnPending>? = null,
    /** Une réponse d'elle en chemin. */
    @SerialName("under_way") val underWay: Boolean = false,
    /** Une réponse demandée, qu'elle n'a pas encore rendue. */
    val asked: Boolean = false,
)

/** Ce qu'une écriture a donné (`{"ok": true, "message": "…"}`), avec ce que « Préremplir » dit de plus. */
@Serializable
data class TeamsDone(
    val ok: Boolean = false,
    val message: String = "",
    val deduped: Boolean = false,
    /** `prefill` : une réponse d'elle déjà en chemin dans cette conversation. */
    val draft: String = "",
    /** `prefill` : elle y travaille (demandée maintenant, ou déjà). */
    val asked: Boolean = false,
)
