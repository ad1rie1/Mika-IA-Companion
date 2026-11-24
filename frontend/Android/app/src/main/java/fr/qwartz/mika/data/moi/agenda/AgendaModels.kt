package fr.qwartz.mika.data.moi.agenda

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

/*
 * Les formes de l'Agenda dans l'API par personne (`backendv2/docs/protocole-moi.md` § 13, ADR 0309) : ses agendas, une
 * période, une occurrence, une date de « L'agenda de Mika », ce que Mika propose, ses comptes, le tableau de droits
 * d'un agenda. Les instants sont en millisecondes (UTC) avec le nom de leur fuseau ; un champ absent prend son défaut.
 * Les mêmes que `frontendv2/src/api/agenda.ts`.
 */

/** Les sortes d'agenda : celui du système, ceux qu'on branche, et celui de Mika (sa mémoire). */
object AgendaKinds {
    const val SYSTEM = "systeme"
    const val GOOGLE = "google"
    const val MICROSOFT = "microsoft"
    const val CALDAV = "caldav"
    const val ICAL = "ical"
    const val MIKA = "mika"
}

/** Les groupes de la liste des agendas. */
object AgendaGroups {
    const val MINE = "mine"
    const val SUBSCRIPTIONS = "subscriptions"
    const val SHARED = "shared"
    const val MIKA = "mika"
}

/** Une valeur codée et ses mots (`colors`, `reminders`, `kinds`). */
@Serializable
data class Coded(val code: String = "", val label: String = "")

/** Un rappel du fournisseur : une notification de son application, ou un e-mail, tant de minutes avant. */
@Serializable
data class Alert(val method: String = Alert.NOTIFICATION, val minutes: Int = 0) {
    companion object {
        const val NOTIFICATION = "notification"
        const val EMAIL = "email"
    }
}

/** Ce qu'un agenda garde des rappels de son fournisseur : combien un événement en garde (0 : aucun), si l'e-mail en
 *  est, et ceux de l'agenda chez lui (les `defaultReminders` de Google). */
@Serializable
data class ProviderReminders(val max: Int = 0, val email: Boolean = false, val defaults: List<Alert> = emptyList())

@Serializable
data class CalendarCan(
    val write: Boolean = false,
    val respond: Boolean = false,
    val settings: Boolean = false,
    val share: Boolean = false,
    val rights: Boolean = false,
    val remind: Boolean = false,
    val rename: Boolean = false,
)

/** Un partage d'un de ses agendas : à qui, et son niveau (`lire`, `preparer`, `servir`). */
@Serializable
data class AgendaShare(val person: String = "", val name: String = "", val level: String = "")

/** Un agenda (`…/agenda/calendars`). */
@Serializable
data class AgendaCalendar(
    val key: String = "",
    val account: String = "",
    /** Celui qu'on lui voit : le nom donné dans Mika, sinon celui du fournisseur. */
    val name: String = "",
    @SerialName("provider_name") val providerName: String = "",
    val kind: String = "",
    @SerialName("kind_label") val kindLabel: String = "",
    /** `proprietaire`, ou le niveau d'un partage. */
    val level: String = "",
    @SerialName("owner_name") val ownerName: String = "",
    val group: String = "",
    /** Celle qu'elle a choisie (vide : [providerColor]). */
    val color: String = "",
    @SerialName("provider_color") val providerColor: String = "",
    val primary: Boolean = false,
    /** Masqué dans Paramètres : Mika ne s'en sert plus, la vue ne le montre pas. */
    val hidden: Boolean = false,
    /** Son compte est coché. */
    val enabled: Boolean = true,
    /** « Mika te le rappelle » : `non`, `15`, `30`, `60`, `veille`. */
    val reminder: String = "non",
    /** Son choix (vide : celui du serveur pour sa sorte). */
    @SerialName("reminder_set") val reminderSet: String = "",
    val writable: Boolean = false,
    @SerialName("read_only") val readOnly: Boolean = false,
    val can: CalendarCan = CalendarCan(),
    @SerialName("synced_at") val syncedAt: Long = 0,
    @SerialName("provider_reminders") val providerReminders: ProviderReminders = ProviderReminders(),
    /** Un agenda à elle : la panne de la dernière synchronisation de son compte, en mots. */
    val error: String = "",
    val shares: List<AgendaShare> = emptyList(),
) {
    val owned: Boolean get() = level == AgendaLevels.OWNER
}

/** Les niveaux : le sien, ou celui d'un partage. */
object AgendaLevels {
    const val OWNER = "proprietaire"
    const val READ = "lire"
    const val PREPARE = "preparer"
    const val USE = "servir"
}

@Serializable
data class Calendars(
    val plugged: Boolean = true,
    /** Le fuseau du serveur : une période et ce qu'on écrit se lisent à son heure. */
    val zone: String = "",
    val calendars: List<AgendaCalendar> = emptyList(),
    val colors: List<Coded> = emptyList(),
    val reminders: List<Coded> = emptyList(),
)

/** Un participant, ou l'organisateur. */
@Serializable
data class AgendaPerson(
    val address: String = "",
    val name: String = "",
    val person: String = "",
    /** `attente`, `oui`, `peut`, `non` ; vide : on ne sait pas. */
    val response: String = "",
    val optional: Boolean = false,
    val me: Boolean = false,
)

/** Ce que Mika y a mis, et la conversation où elle l'a fait. */
@Serializable
data class Added(val by: String = "", val conversation: String = "", val at: Long = 0)

@Serializable
data class ItemCan(
    val edit: Boolean = false,
    val delete: Boolean = false,
    val respond: Boolean = false,
    val duplicate: Boolean = false,
    val remind: Boolean = false,
)

/** Une occurrence d'un événement (une période, un événement, une invitation). */
@Serializable
data class AgendaItem(
    val event: Int = 0,
    /** Sa clé dans la série (vide : un événement simple, ou la série). */
    val occurrence: String = "",
    val uid: String = "",
    val calendar: String = "",
    val title: String = "",
    /** Un événement privé d'une autre personne : « Occupé », son créneau seul. */
    val masked: Boolean = false,
    val start: Long = 0,
    val end: Long = 0,
    @SerialName("all_day") val allDay: Boolean = false,
    @SerialName("first_day") val firstDay: String = "",
    @SerialName("last_day") val lastDay: String = "",
    val zone: String = "",
    val location: String = "",
    val description: String = "",
    val conference: String = "",
    val status: String = "",
    val busy: Boolean = true,
    val private: Boolean = false,
    val recurring: Boolean = false,
    val rule: String = "",
    val organizer: AgendaPerson? = null,
    val participants: List<AgendaPerson> = emptyList(),
    /** La réponse du compte de l'agenda (`attente`, `oui`, `peut`, `non` ; vide : il n'est pas invité). */
    val response: String = "",
    /** Elle attend sa réponse. */
    val invitation: Boolean = false,
    /** Faux pour une invitation : seul qui l'organise la modifie. */
    val organized: Boolean = true,
    val added: Added? = null,
    /** « Mika te le rappelle » pour cet événement (vide : le choix de l'agenda). */
    val remind: String = "",
    val forgotten: Boolean = false,
    val reminders: List<Alert> = emptyList(),
    @SerialName("reminders_default") val remindersDefault: Boolean = false,
    val can: ItemCan = ItemCan(),
    /** Une invitation à laquelle elle ne répond pas d'ici (`can.respond` faux) : pourquoi, en une ligne. */
    @SerialName("respond_why") val respondWhy: String = "",
    /** Une invitation, un événement : le nom de son agenda. */
    @SerialName("calendar_name") val calendarName: String = "",
    /** La réponse qu'elle a préparée à cette invitation. */
    val prepared: Proposal? = null,
    /** Ce que Mika propose sur cet événement (`…/agenda/event`). */
    val proposals: List<Proposal> = emptyList(),
)

/** Une date de « L'agenda de Mika » : sa mémoire, en lecture seule. */
@Serializable
data class HerDate(
    val ref: String = "",
    val calendar: String = AgendaKinds.MIKA,
    /** `promesse`, `moment`, `chaque_annee`. */
    val kind: String = "",
    val title: String = "",
    val start: Long = 0,
    val end: Long = 0,
    @SerialName("all_day") val allDay: Boolean = false,
    val day: String = "",
    /** D'où ça vient, en mots. */
    val source: String = "",
    val conversation: String = "",
    @SerialName("said_at") val saidAt: Long = 0,
)

/** Un ajout que Mika propose. */
@Serializable
data class ProposalDraft(
    val title: String = "",
    val start: Long = 0,
    val end: Long = 0,
    @SerialName("all_day") val allDay: Boolean = false,
    val zone: String = "",
    val location: String = "",
    val description: String = "",
    val rule: String = "",
    val invite: List<String> = emptyList(),
)

@Serializable
data class ProposalTarget(val event: Int = 0, val uid: String = "", val occurrence: String = "")

/** Ce qui partirait, à qui décide : son texte, son empreinte, et pourquoi il ne peut pas partir. */
@Serializable
data class ProposalPreview(val text: String = "", val digest: String = "", val blocked: String = "")

/** Ce que Mika propose d'écrire dans un de ses agendas et qui attend un accord. */
@Serializable
data class Proposal(
    val id: Int = 0,
    /** `ajouter`, `modifier`, `supprimer`, `repondre`. */
    val op: String = "",
    val calendar: String = "",
    /** Ce qu'elle propose, dans ses mots. */
    val summary: String = "",
    val at: Long = 0,
    val starts: Long = 0,
    /** C'est elle qui décide (sinon le propriétaire de l'agenda, ou qui s'occupe de Mika). */
    val decides: Boolean = false,
    val conversation: String = "",
    val invitation: String = "",
    val target: ProposalTarget? = null,
    val draft: ProposalDraft? = null,
    val change: JsonObject? = null,
    val scope: String = "",
    /** Une réponse préparée : `oui`, `peut`, `non`, et son mot. */
    val answer: String = "",
    val comment: String = "",
    /** Pourquoi cette réponse (à qui décide seulement). */
    val why: String = "",
    /** « Mika te le rappelle » qu'elle poserait. */
    val remind: String? = null,
    val preview: ProposalPreview? = null,
) {
    companion object {
        const val ADD = "ajouter"
        const val EDIT = "modifier"
        const val DELETE = "supprimer"
        const val RESPOND = "repondre"
    }
}

@Serializable
data class Period(
    val start: String = "",
    val end: String = "",
    val zone: String = "",
    val items: List<AgendaItem> = emptyList(),
    val her: List<HerDate> = emptyList(),
    val proposals: List<Proposal> = emptyList(),
)

@Serializable
data class Found(
    val q: String = "",
    val items: List<AgendaItem> = emptyList(),
    val her: List<HerDate> = emptyList(),
    val more: Boolean = false,
)

@Serializable
data class Invitations(val items: List<AgendaItem> = emptyList())

@Serializable
data class Proposals(val items: List<Proposal> = emptyList())

/** Ce qu'une écriture rend : son message, ce qu'elle a créé, et ce qu'un parcours de connexion donne. */
@Serializable
data class AgendaDone(
    val ok: Boolean = true,
    val message: String = "",
    val deduped: Boolean = false,
    val made: Made? = null,
    /** Un compte branché. */
    val account: String = "",
    /** La connexion Google : l'adresse de consentement, jusqu'à quand, si Google revient seul au serveur. */
    val url: String = "",
    val until: Long = 0,
    val direct: Boolean = false,
    /** La connexion Microsoft : le code à entrer. */
    val code: String = "",
    val state: String = "",
    val error: String = "",
) {
    @Serializable
    data class Made(val calendar: String = "", val uid: String = "", val event: Int = 0)
}

// ── Ses comptes (Paramètres › Agendas) ──────────────────────────────────

/** Où en est la connexion d'un compte Google ou Microsoft. */
@Serializable
data class AgendaSignin(
    /** `connectee`, `en_attente`, `a_faire`. */
    val state: String = "",
    val code: String = "",
    val url: String = "",
    val until: Long = 0,
    val error: String = "",
) {
    companion object {
        const val CONNECTED = "connectee"
        const val WAITING = "en_attente"
        const val TODO = "a_faire"
    }
}

@Serializable
data class AccountAbilities(val write: Boolean = false, val calendars: Boolean = false)

@Serializable
data class AccountSecrets(val password: Boolean = false)

/** Un compte d'agenda : son compte du système, ou un compte branché. */
@Serializable
data class AgendaAccount(
    val key: String = "",
    val kind: String = "",
    @SerialName("kind_label") val kindLabel: String = "",
    val label: String = "",
    val system: Boolean = false,
    val address: String = "",
    val enabled: Boolean = true,
    /** CalDAV : l'adresse du serveur ; un abonnement ne la rend jamais ([urlSet]). */
    val url: String = "",
    @SerialName("url_set") val urlSet: Boolean = false,
    val username: String = "",
    val secrets: AccountSecrets = AccountSecrets(),
    @SerialName("oauth_client_id") val oauthClientId: String = "",
    @SerialName("oauth_tenant") val oauthTenant: String = "",
    @SerialName("synced_at") val syncedAt: Long = 0,
    @SerialName("tried_at") val triedAt: Long = 0,
    val failures: Int = 0,
    val error: String = "",
    val signin: AgendaSignin? = null,
    val abilities: AccountAbilities = AccountAbilities(),
    val calendars: List<AgendaCalendar> = emptyList(),
)

@Serializable
data class GoogleApp(val app: Boolean = false, val direct: Boolean = false)

/** Une aide pour un serveur CalDAV (Outlook pro par DavMail, iCloud, Nextcloud, Fastmail). */
@Serializable
data class AgendaService(val key: String = "", val name: String = "", val url: String = "", val help: String = "")

@Serializable
data class Accounts(
    val plugged: Boolean = true,
    val accounts: List<AgendaAccount> = emptyList(),
    val google: GoogleApp = GoogleApp(),
    @SerialName("microsoft_app") val microsoftApp: Boolean = false,
    val kinds: List<Coded> = emptyList(),
    val services: List<AgendaService> = emptyList(),
    val colors: List<Coded> = emptyList(),
    val reminders: List<Coded> = emptyList(),
    /** Combien de comptes elle peut brancher (`null` : une opératrice). */
    val max: Int? = null,
)

/** Un agenda trouvé en essayant un serveur CalDAV. */
@Serializable
data class TriedCalendar(
    val local: String = "",
    val name: String = "",
    val color: String = "",
    val writable: Boolean = false,
    val primary: Boolean = false,
    val selected: Boolean = false,
)

@Serializable
data class TryResult(val ok: Boolean = false, val message: String = "", val calendars: List<TriedCalendar> = emptyList())

// ── Son tableau de droits (Outils › Droits) ─────────────────────────────

/** Une ligne en mots, telle que le serveur la dit. */
@Serializable
data class RuleWords(
    val who: String = "",
    val canal: String = "",
    @SerialName("when") val moment: String = "",
    val read: String = "",
    val write: String = "",
    val respond: String = "",
    val keep: String = "",
)

/** Une ligne du tableau d'un agenda : qui, par où, quand ; lire, écrire (`non`, `accord`, `seule`), répondre (`non`,
 *  `accord`), ce qu'elle en garde (`rien`, `prive`, `perso`, `public`). */
@Serializable
data class AgendaRule(
    val who: List<String> = emptyList(),
    val canal: List<String> = emptyList(),
    @SerialName("when") val moment: List<String> = emptyList(),
    val read: Boolean = false,
    val write: String = "non",
    val respond: String = "non",
    val keep: String = "rien",
    val words: RuleWords? = null,
)

@Serializable
data class AgendaRights(
    val calendar: String = "",
    val set: Boolean = false,
    val lines: List<AgendaRule> = emptyList(),
    val default: AgendaRule = AgendaRule(),
)
