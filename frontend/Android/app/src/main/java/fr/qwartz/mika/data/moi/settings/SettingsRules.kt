package fr.qwartz.mika.data.moi.settings

import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.firstName
import fr.qwartz.mika.data.moi.mail.MailBox
import fr.qwartz.mika.data.moi.teams.TeamsAccount
import fr.qwartz.mika.data.moi.tools.Service
import fr.qwartz.mika.data.moi.tools.Services
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/*
 * Les règles pures que les pages de Paramètres partagent, portées du client web sans les réinventer
 * (`frontend/Web/src/shared/sharing.ts`, `shared/settings.ts`, `shared/sendrules.ts`, `screens/parametres/account.ts`) :
 * les niveaux d'un partage et ce qu'ils ouvrent, ce qu'un formulaire a changé, les refus par champ, ton compte, la
 * règle d'envoi d'un compte (ADR 0207) et sa version, les lignes de la page racine. Celles d'un domaine sont dans son
 * paquet : `mail/MailSettingsRules.kt`, `teams/TeamsSettingsRules.kt`, `tools/ToolsSettingsRules.kt`,
 * `phone/PhoneSettingsRules.kt`. Les codes sont ceux du moteur (`vocab/access.py`, `app/me/`). Tout se teste sur la JVM.
 */

// ── Les partages (ADR 0188) ─────────────────────────────────────────────

/** Les niveaux d'un partage : lire ; lire et préparer ; s'en servir. */
val SHARE_LEVELS: List<Pair<String, String>> = listOf(
    Levels.READ to "Lire",
    Levels.PREPARE to "Lire et préparer",
    Levels.USE to "S'en servir",
)

/** Un service se partage pour lire ou pour s'en servir, jamais « préparer » (le serveur refuserait : 400). */
fun shareLevelsFor(kind: String): List<Pair<String, String>> =
    SHARE_LEVELS.filter { (k, _) -> kind != ShareKinds.MCP || k != Levels.PREPARE }

/** « Lire », « Lire et préparer », « S'en servir » ; « Propriétaire » pour la sienne. */
fun shareWords(level: String): String =
    if (level == Levels.OWNER) "Propriétaire" else SHARE_LEVELS.firstOrNull { it.first == level }?.second ?: level

fun kindWords(kind: String): String = when (kind) {
    ShareKinds.TEAMS -> "Compte Teams"
    ShareKinds.MCP -> "Service"
    ShareKinds.AGENDA -> "Agenda"
    else -> "Boîte"
}

/** « Boîte « Pro » », « Service « meteo » ». */
fun whatLabel(kind: String, title: String): String = "${kindWords(kind)} « $title »"

/** Ce que la personne pourra, dit en une phrase (la fenêtre « Partager »). */
fun sharePhrase(kind: String, title: String, person: String, level: String): String {
    val first = firstName(person).ifEmpty { person }
    val where = when (kind) {
        ShareKinds.MCP -> "dans ses Outils"
        ShareKinds.TEAMS -> "dans son Teams"
        ShareKinds.AGENDA -> "dans son Agenda"
        else -> "dans son Mail"
    }
    val can = when (level) {
        Levels.READ -> if (kind == ShareKinds.MCP) {
            "pour que Mika s'en serve pour lire, en tête-à-tête avec elle ou lui"
        } else {
            "en lecture seule : ni répondre ni ranger"
        }
        Levels.PREPARE -> "en lecture, et Mika pourra lui préparer des réponses que tu approuveras"
        else -> if (kind == ShareKinds.MCP) {
            "pour que Mika s'en serve pour elle ou lui, sur son accord pour ce qui agit"
        } else {
            "pour que Mika s'en serve pour elle ou lui, en tête-à-tête, comme pour toi"
        }
    }
    return "$first verra « $title » $where, $can."
}

/** Ce qu'elle peut partager : ses boîtes, ses comptes Teams, ses services ; [common] : « à toi », déjà à chacune de ses
 *  propriétaires, qui ne se la partagent pas. */
data class Shareable(val kind: String, val key: String, val title: String, val sub: String, val common: Boolean = false)

fun shareables(boxes: List<MailBox>, accounts: List<TeamsAccount>, services: List<Service>): List<Shareable> =
    boxes.filter { it.own }.map { Shareable(ShareKinds.MAIL, it.key, it.name.ifBlank { it.key }, it.address, it.common) } +
        accounts.filter { it.own }.map {
            Shareable(ShareKinds.TEAMS, it.key, it.name.ifBlank { it.key }, if (it.selfName.isNotBlank()) "ton nom dans Teams : ${it.selfName}" else "", it.common)
        } +
        services.map { Shareable(ShareKinds.MCP, it.name, it.name, it.purpose) }

/** À qui partager : tout le monde, sauf, pour une ressource « à toi », ses propriétaires — elle est déjà à elles. */
fun sharePeople(common: Boolean, people: List<Person>): List<Person> = if (common) people.filterNot { it.owner } else people

/**
 * Un partage qu'on change ne se change plus quand sa personne n'a plus de compte actif, ou quand elle est devenue une
 * des propriétaires de ce qui est « à toi » : il se retire seulement (un niveau vide).
 */
fun shareGone(share: GivenShare, people: List<Person>, common: Boolean): Boolean {
    val person = people.firstOrNull { it.person == share.person } ?: return true
    return common && person.owner
}

/** Ce qu'ouvre ce qu'on te partage : une boîte dans Mail, un compte dans Teams, un service sur sa page, un agenda dans
 *  l'Agenda. */
enum class ShareOpens { MAIL, TEAMS, SERVICE, AGENDA }

fun openOf(kind: String): ShareOpens = when (kind) {
    ShareKinds.TEAMS -> ShareOpens.TEAMS
    ShareKinds.MCP -> ShareOpens.SERVICE
    ShareKinds.AGENDA -> ShareOpens.AGENDA
    else -> ShareOpens.MAIL
}

// ── Les formulaires ─────────────────────────────────────────────────────

/** Ce qui a changé d'un formulaire : les champs dont la valeur n'est plus celle de départ. */
fun changes(before: JsonObject, after: JsonObject): JsonObject = JsonObject(after.filter { (k, v) -> before[k] != v })

/** Les messages d'un refus, par champ : la dernière partie du chemin (`accounts.pro.imap_port` → `imap_port`). */
fun fieldErrors(fields: Map<String, String>): Map<String, String> {
    val out = linkedMapOf<String, String>()
    for ((path, message) in fields) {
        val name = path.substringAfterLast('.').ifEmpty { path }
        out[name] = out[name]?.let { "$it ; $message" } ?: message
    }
    return out
}

/** Ce qu'un refus dit d'un champ que le formulaire ne montre pas : à dire à part (« Port IMAP : … »). */
fun unplaced(errors: Map<String, String>, shown: Set<String>, labels: Map<String, String>): List<String> =
    errors.filterKeys { it !in shown }.map { (k, v) -> "${labels[k] ?: k} : $v" }

/** Le toast d'un refus de formulaire : son message, et ce qui n'a pas trouvé sa place sous un champ. */
fun refusalToast(message: String, rest: List<String>): String = if (rest.isEmpty()) message else "$message (${rest.joinToString(" ; ")})"

// ── Le compte ───────────────────────────────────────────────────────────

const val PASSWORD_HELP = "8 caractères au moins, pas seulement des chiffres, sans ton identifiant dedans."

/** La question que « Lui demander » pose dans le chat. */
const val ASK_ME = "Qu'est-ce que tu sais de moi ?"

/** Ce que le serveur accepte d'un nom (au-delà : 400). */
const val NAME_MAX = 120

/** Ce que le serveur accepte d'un mot de passe (au-delà : 400, jamais coupé). */
const val PASSWORD_MAX = 200

fun nameProblem(name: String): String? = when {
    name.isBlank() -> "un nom"
    name.trim().length > NAME_MAX -> "$NAME_MAX caractères au plus"
    else -> null
}

/** Ce qui manque avant de changer son mot de passe, par champ. */
fun passwordProblems(current: String, password: String, again: String): Map<String, String> {
    val out = linkedMapOf<String, String>()
    if (current.isEmpty()) out["current"] = "ton mot de passe actuel"
    if (password.isEmpty()) out["password"] = "le nouveau" else if (password != again) out["again"] = "les deux ne sont pas les mêmes"
    return out
}

/** Ton rôle, en une phrase. */
fun roleHelp(owner: Boolean, operator: Boolean): String = when {
    operator -> "Un opérateur parle avec elle et ouvre aussi la console : tout ce qu'elle vit, sa configuration, les approbations et les apps."
    owner -> "Une de ses propriétaires : ce qui est « à toi » est à toi."
    else -> "Une personne qui a un compte : ce que tu branches ici est à toi seule."
}

// ── Comment part ce qu'elle prépare (ADR 0207) ──────────────────────────

enum class RulesKind { MAIL, TEAMS }

/** Ce qu'on règle d'une ligne : préparer d'elle-même, comment ça part. */
data class RuleEdit(val prepare: Boolean, val reply: String)

val RuleLine.edit: RuleEdit get() = RuleEdit(prepare, reply)

/** Comment ça part, dans les mots du moteur (`vocab.access.REPLY_WORDS`). */
private val SENDS = listOf(
    Replies.ASK to "ton accord",
    Replies.ALONE to "seule",
    Replies.DRAFT to "brouillon — c'est toi qui l'envoies",
    Replies.NO to "non",
)

/** Les choix d'une ligne : le courrier n'a pas de brouillon que tu envoies toi-même — sauf sur une ligne qui l'a déjà,
 *  qu'on montre telle qu'elle est. */
fun sendChoices(kind: RulesKind, current: String): List<Pair<String, String>> =
    SENDS.filter { (k, _) -> k != Replies.DRAFT || kind == RulesKind.TEAMS || current == Replies.DRAFT }

fun replyWords(reply: String): String = SENDS.firstOrNull { it.first == reply }?.second ?: reply

/** Qui (et quand) une ligne désigne : « Tout le monde » sans qui ; « toujours » ne se dit pas. */
fun ruleWho(line: RuleLine): String =
    listOf(line.who.ifBlank { "Tout le monde" }, line.whenWords.takeIf { it.isNotBlank() && it != "toujours" }.orEmpty())
        .filter { it.isNotBlank() }.joinToString(" · ")

/** Ce que dit une ligne une fois réglée : « préparer : oui · envoi : ton accord ». */
fun ruleSummary(edit: RuleEdit): String = "préparer : ${if (edit.prepare) "oui" else "non"} · envoi : ${replyWords(edit.reply)}"

/** Une case de la règle a bougé. */
fun ruleChanged(rules: SendRules, lines: List<RuleEdit>, default: RuleEdit): Boolean =
    rules.lines.map { it.edit } != lines || rules.default.edit != default

/**
 * Ce qui part au serveur quand la règle a bougé : toute la règle, avec l'empreinte de celle qu'on a lue. `null` quand
 * les choix ne sont pas ceux de cette règle (pas une entrée par ligne) : rien ne part, l'écran le dit en mots — jamais
 * une exception qui ferait tomber l'app.
 */
fun ruleBody(rules: SendRules, lines: List<RuleEdit>, default: RuleEdit): JsonObject? {
    if (lines.size != rules.lines.size) return null
    fun choice(e: RuleEdit) = JsonObject(mapOf("prepare" to JsonPrimitive(e.prepare), "reply" to JsonPrimitive(e.reply)))
    return JsonObject(
        mapOf(
            "canal" to JsonPrimitive(rules.canal),
            "version" to JsonPrimitive(rules.version),
            "lines" to JsonArray(lines.map(::choice)),
            "default" to choice(default),
        ),
    )
}

/** L'aide sous la règle : dans quel ordre elle se lit, ce qui se règle ici, d'où elle vient. */
fun rulesHelp(rules: SendRules, kind: RulesKind): String {
    val where = if (kind == RulesKind.TEAMS) "Teams" else "Mail"
    val origin = when {
        rules.set -> ""
        rules.common -> " Ce compte suit la règle de tout ${if (kind == RulesKind.TEAMS) "Teams" else "le courrier"}, réglée dans la console : l'enregistrer ici lui en donne une à lui."
        else -> " Elle n'a jamais été réglée : c'est sa règle de départ."
    }
    val mail = if (kind == RulesKind.MAIL) " Le courrier n'a pas de brouillon que tu envoies toi-même : « ton accord » en tient lieu." else ""
    return "Lue de haut en bas : la première ligne qui correspond décide. Tu règles ici ce qu'elle prépare d'elle-même et comment ça part ; " +
        "qui écrit et l'ordre des lignes se règlent dans la console.$mail Ce qu'elle prépare se relit dans $where, dans « Ses brouillons ».$origin"
}

// ── Une boîte dans la liste de Paramètres ───────────────────────────────

/**
 * Le non-lu de la réception d'une boîte. Il reste ici, pas avec les autres règles d'une boîte (`mail/MailSettingsRules.kt`,
 * qui l'importe d'ici) : Mail a déjà un `unseenOf` de même signature (`mail/MailRules.kt`, le premier dossier de
 * réception), quand celui-ci additionne tous les dossiers de réception.
 */
fun unseenOf(b: MailBox): Int = b.folders.filter { it.role == "inbox" || it.name == "INBOX" }.sumOf { it.unseen }

// ── La page racine ──────────────────────────────────────────────────────

/** « 3 à toi · 1 partagée avec toi » ; « aucune boîte ». */
fun boxesSummary(boxes: List<MailBox>): String {
    val own = boxes.count { it.own }
    val shared = boxes.size - own
    return listOfNotNull(
        if (own > 0) "$own à toi" else null,
        if (shared > 0) "$shared partagée${if (shared > 1) "s" else ""} avec toi" else null,
    ).joinToString(" · ").ifEmpty { "aucune boîte" }
}

/** Les noms de tes comptes, et combien on t'en partage ; « aucun compte ». */
fun teamsSummary(accounts: List<TeamsAccount>): String {
    val own = accounts.filter { it.own }.map { it.name.ifBlank { it.key } }
    val shared = accounts.count { !it.own }
    return listOfNotNull(
        own.takeIf { it.isNotEmpty() }?.joinToString(", "),
        if (shared > 0) "$shared partagé${if (shared > 1) "s" else ""} avec toi" else null,
    ).joinToString(" · ").ifEmpty { "aucun compte" }
}

/** « Rando Cassel → Julien · Météo → Léa », deux au plus puis combien d'autres ; ce qu'on te partage ; « rien ». */
fun sharesSummary(shares: Shares): String {
    val given = shares.given.map { "${it.title} → ${firstName(it.name).ifEmpty { it.name }}" }
    val shown = given.take(2) + (if (given.size > 2) listOf("+${given.size - 2}") else emptyList())
    val received = shares.received.size
    return listOfNotNull(
        shown.takeIf { it.isNotEmpty() }?.joinToString(" · "),
        if (received > 0) "$received partagé${if (received > 1) "s" else ""} avec toi" else null,
    ).joinToString(" · ").ifEmpty { "rien de partagé" }
}

/** Les noms de tes services, et combien on t'en partage ; « aucun service ». */
fun servicesSummary(services: Services): String = listOfNotNull(
    services.items.map { it.name }.takeIf { it.isNotEmpty() }?.joinToString(", "),
    services.received.size.takeIf { it > 0 }?.let { "$it partagé${if (it > 1) "s" else ""} avec toi" },
).joinToString(" · ").ifEmpty { "aucun service" }

/** Le texte d'une réponse sans corps (un `ok` muet) : son message, sinon [fallback]. */
fun doneText(message: String, fallback: String): String = message.ifBlank { fallback }

/** La valeur d'un champ texte d'un objet JSON (pour les tests et les toasts). */
internal fun JsonObject.text(key: String): String? = (this[key] as? JsonPrimitive)?.contentOrNull
