package fr.qwartz.mika.data.moi.settings

import fr.qwartz.mika.data.moi.teams.ExtensionKey
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * Les formes de Paramètres dans l'API par personne (`backendv2/docs/protocole-moi.md` § 7, 8, 9 ; code
 * `app/me/settings.py`, `mcp.py`, `sharing.py`). Chaque champ a son défaut : `MikaJson` ignore ce qu'il ne connaît pas,
 * et un champ absent ne casse rien. Les instants sont en millisecondes (0 : jamais). Un secret n'est jamais rendu :
 * seulement le fait qu'il est gardé.
 */

// ── Une boîte (§ 7) ─────────────────────────────────────────────────────

/** Ce qu'une personne règle d'une boîte (`MailAccount`, sans `owner` ni `shares` ni ses secrets). Les noms sont ceux du
 *  moteur : ils partent tels quels dans `values` (`mail/box/save`). */
@Serializable
data class BoxValues(
    val label: String = "",
    val address: String = "",
    val enabled: Boolean = true,
    /** `password` ou `microsoft`. */
    val auth: String = Auths.PASSWORD,
    @SerialName("imap_host") val imapHost: String = "",
    @SerialName("imap_port") val imapPort: Int = 993,
    @SerialName("imap_ssl") val imapSsl: Boolean = true,
    val user: String = "",
    val folders: List<String> = listOf("INBOX"),
    @SerialName("sync_all") val syncAll: Boolean = false,
    /** Tout garder en local (ADR 0249) : tous les dossiers, sauf indésirables et corbeille, et leur historique. */
    @SerialName("keep_all") val keepAll: Boolean = false,
    @SerialName("since_days") val sinceDays: Int = 2,
    /** Ses consignes de tri (ADR 0243) : ce que son tri fait de chaque mail qui arrive dans un dossier relevé. */
    @SerialName("triage_instructions") val triageInstructions: String = "",
    @SerialName("oauth_client_id") val oauthClientId: String = "",
    @SerialName("oauth_tenant") val oauthTenant: String = "",
    @SerialName("smtp_host") val smtpHost: String = "",
    @SerialName("smtp_port") val smtpPort: Int = 587,
    /** `starttls`, `ssl`, `none`. */
    @SerialName("smtp_security") val smtpSecurity: String = "starttls",
    @SerialName("smtp_user") val smtpUser: String = "",
    @SerialName("save_sent") val saveSent: Boolean = true,
    /** Comment elle y écrit : `elle`, `assistante`, `proprietaire`. */
    val voice: String = Voices.HER,
    @SerialName("display_name") val displayName: String = "",
    @SerialName("sender_name") val senderName: String = "",
    val tone: String = "",
    val instructions: String = "",
    val signature: String = "",
)

object Auths {
    const val PASSWORD = "password"
    const val MICROSOFT = "microsoft"
}

object Voices {
    const val HER = "elle"
    const val ASSISTANT = "assistante"
    const val OWNER = "proprietaire"
}

/** Ses secrets gardés (jamais rendus). */
@Serializable
data class BoxSecrets(
    val password: Boolean = false,
    @SerialName("smtp_password") val smtpPassword: Boolean = false,
)

/** Où en est la connexion Microsoft d'une boîte (ADR 0166). */
@Serializable
data class SignIn(
    /** `connectee`, `en_attente` (un code à entrer chez Microsoft), ou autre chose (pas connectée). */
    val state: String = "",
    val code: String = "",
    val url: String = "",
    /** Jusqu'à quand le code vaut. */
    val until: Long = 0,
    val error: String = "",
) {
    val connected: Boolean get() = state == CONNECTED
    val waiting: Boolean get() = state == WAITING

    companion object {
        const val CONNECTED = "connectee"
        const val WAITING = "en_attente"
    }
}

/** Une ligne de la règle d'un de ses comptes, en mots (ADR 0207) : qui, quand, préparer d'elle-même, comment ça part. */
@Serializable
data class RuleLine(
    val who: String = "",
    @SerialName("when") val whenWords: String = "",
    val prepare: Boolean = false,
    /** `seule`, `accord`, `brouillon`, `non`. */
    val reply: String = Replies.ASK,
    @SerialName("reply_words") val replyWords: String = "",
)

/** Comment part ce qu'elle prépare (les codes du moteur, `vocab.access.REPLIES`). */
object Replies {
    const val ALONE = "seule"
    const val ASK = "accord"
    const val DRAFT = "brouillon"
    const val NO = "non"
}

/**
 * La règle du canal d'un de ses comptes (`courrier:<boîte>`, `teams:<compte>`), telle que le courrier et Teams la
 * lisent : la sienne ([set]), sinon celle de tout le canal ([common], réglée dans la console), sinon celle de départ.
 * [version] : son empreinte, à renvoyer pour la changer (une autre : 409).
 */
@Serializable
data class SendRules(
    val canal: String = "",
    val set: Boolean = false,
    val common: Boolean = false,
    val version: String = "",
    val lines: List<RuleLine> = emptyList(),
    val default: RuleLine = RuleLine(),
)

/** `GET …/mail/box` : les réglages d'une de ses boîtes. */
@Serializable
data class BoxSettings(
    val box: String = "",
    val values: BoxValues = BoxValues(),
    val secrets: BoxSecrets = BoxSecrets(),
    val ready: Boolean = false,
    @SerialName("can_send") val canSend: Boolean = false,
    val microsoft: Boolean = false,
    val signin: SignIn? = null,
    val rules: SendRules = SendRules(),
)

// ── Un compte Teams (§ 7) ───────────────────────────────────────────────

@Serializable
data class TeamsValues(
    val label: String = "",
    val enabled: Boolean = true,
    @SerialName("display_name") val displayName: String = "",
    val tone: String = "",
    val instructions: String = "",
    val sign: Boolean = false,
    val signature: String = "",
)

/** `GET …/teams/account` : les réglages d'un de ses comptes Teams. */
@Serializable
data class TeamsSettings(
    val account: String = "",
    val values: TeamsValues = TeamsValues(),
    @SerialName("extension_key") val extensionKey: ExtensionKey? = null,
    val rules: SendRules = SendRules(),
)

/** Le sort d'une écriture de Paramètres : `{"ok": true, "message": "…"}`, et ce qu'elle a créé ou rendu. */
@Serializable
data class SettingsDone(
    val ok: Boolean = false,
    val message: String = "",
    /** Une boîte créée : sa clé. */
    val box: String = "",
    /** Un compte Teams créé : sa clé. */
    val account: String = "",
    /** Un service branché : son nom. */
    val name: String = "",
    /** Une clé neuve d'extension, rendue cette fois seulement. */
    val key: String = "",
    /** Le mot de passe a changé : toutes ses sessions sont fermées, on se reconnecte. */
    val relogin: Boolean = false,
    val deduped: Boolean = false,
)

// ── Ses services MCP (§ 8) ──────────────────────────────────────────────

/** Ce qu'on choisit pour un outil (ADR 0129) : coupé, servi en lecture, servi en action ; vide : jamais choisi. */
object ToolChoices {
    const val OFF = "non"
    const val READ = "lecture"
    const val ACT = "action"
    val ALL = listOf(OFF, READ, ACT)
}

@Serializable
data class ServiceTool(
    val remote: String = "",
    /** Son nom chez Mika (vide : jamais regardé). */
    val name: String = "",
    val description: String = "",
    val choice: String = "",
    val new: Boolean = false,
    val changed: Boolean = false,
) {
    /** Nouveau ou changé : il ne sert pas tant qu'on ne l'a pas choisi. */
    val waiting: Boolean get() = new || changed
}

/** Une ligne d'accès, en codes et en mots ; [mine] : elle ne désigne que toi (ta ligne, pas un partage). */
@Serializable
data class AccessLine(
    val who: String = "",
    @SerialName("when") val whenWords: String = "",
    val mine: Boolean = false,
    val read: String = "",
    val act: String = "",
    val keep: String = "",
    @SerialName("read_words") val readWords: String = "",
    @SerialName("act_words") val actWords: String = "",
    @SerialName("keep_words") val keepWords: String = "",
    val tools: List<String> = emptyList(),
)

/** Un de tes services : distant, à toi ; [headers] : des en-têtes sont gardés (jamais rendus). */
@Serializable
data class Service(
    val name: String = "",
    val purpose: String = "",
    @SerialName("when_to_use") val whenToUse: String = "",
    val enabled: Boolean = true,
    val url: String = "",
    val headers: Boolean = false,
    /** `jamais`, `connecte`, `erreur`, `panne`, `incomplet`, `inactif`. */
    val state: String = "jamais",
    val detail: String = "",
    val tools: List<ServiceTool> = emptyList(),
    val access: List<AccessLine> = emptyList(),
    val default: AccessLine? = null,
)

/** Un outil servi d'un service qu'on te partage. */
@Serializable
data class SharedTool(
    val remote: String = "",
    val name: String = "",
    val description: String = "",
    val choice: String = "",
)

/** Un service qu'une autre personne te partage, en lecture : ni son adresse, ni ses en-têtes, ni le détail d'une panne. */
@Serializable
data class ReceivedService(
    val name: String = "",
    val purpose: String = "",
    val enabled: Boolean = true,
    val state: String = "jamais",
    val tools: List<SharedTool> = emptyList(),
    /** `lire` : ses outils qui lisent ; `servir` : aussi ceux qui agissent. */
    val level: String = "lire",
    val line: AccessLine = AccessLine(),
    @SerialName("owner_name") val ownerName: String = "",
)

@Serializable
data class Services(
    val plugged: Boolean = true,
    val items: List<Service> = emptyList(),
    val received: List<ReceivedService> = emptyList(),
)

/** Ce que dit un essai de service : il répond, ou pas (et pourquoi). */
@Serializable
data class ServiceTest(val ok: Boolean = false, val message: String = "")

// ── Ses partages (§ 9) ──────────────────────────────────────────────────

/** Ce qui se partage : une boîte, un compte Teams, un service. */
object ShareKinds {
    const val MAIL = "mail"
    const val TEAMS = "teams"
    const val MCP = "mcp"
    /** Un agenda (ADR 0309) : il se partage depuis l'Agenda ou sa page de Paramètres, et se lit ici avec les autres. */
    const val AGENDA = "agenda"
}

/** Ce que tu partages. */
@Serializable
data class GivenShare(
    val kind: String = "",
    val key: String = "",
    val title: String = "",
    /** La clé de la personne. */
    val person: String = "",
    val name: String = "",
    val level: String = "",
)

/** Ce qu'on te partage. */
@Serializable
data class ReceivedShare(
    val kind: String = "",
    val key: String = "",
    val title: String = "",
    val level: String = "",
    @SerialName("owner_name") val ownerName: String = "",
)

@Serializable
data class Shares(val given: List<GivenShare> = emptyList(), val received: List<ReceivedShare> = emptyList())

/** Une personne à qui partager ; [owner] : une de ses propriétaires (ce qui est « à toi » est déjà à elle). */
@Serializable
data class Person(val person: String = "", val name: String = "", val owner: Boolean = false)

@Serializable
data class People(val items: List<Person> = emptyList())
