package fr.qwartz.mika.data.moi.settings

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * Les formes communes de Paramètres dans l'API par personne (`backendv2/docs/protocole-moi.md` § 7, 9 ; code
 * `app/me/settings.py`, `app/me/sharing.py`) : la règle d'envoi d'un compte (ADR 0207), le sort d'une écriture, les
 * partages. Celles d'un domaine sont dans son paquet : une boîte dans `mail/MailSettingsModels.kt`, un compte Teams
 * dans `teams/TeamsSettingsModels.kt`, les services MCP dans `tools/ToolsSettingsModels.kt`. Chaque champ a son
 * défaut : `MikaJson` ignore ce qu'il ne connaît pas, et un champ absent ne casse rien. Les instants sont en
 * millisecondes (0 : jamais).
 */

// ── Comment part ce qu'elle prépare (ADR 0207) ──────────────────────────

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
