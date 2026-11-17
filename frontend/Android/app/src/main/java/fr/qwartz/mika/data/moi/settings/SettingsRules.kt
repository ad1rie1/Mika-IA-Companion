package fr.qwartz.mika.data.moi.settings

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.ago
import fr.qwartz.mika.data.moi.firstName
import fr.qwartz.mika.data.moi.mail.MailBox
import fr.qwartz.mika.data.moi.ofName
import fr.qwartz.mika.data.moi.phone.PhoneDevice
import fr.qwartz.mika.data.moi.phone.thisPhone
import fr.qwartz.mika.data.moi.teams.TeamsAccount
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import java.net.URI
import java.net.URISyntaxException

/*
 * Les règles pures de Paramètres, portées du client web (`frontendv2/src/screens/parametres/words.ts`, `form.ts` et ses
 * pages) sans les réinventer : les niveaux d'un partage et ce qu'ils ouvrent, l'état d'une boîte, d'un compte Teams ou
 * d'un service, ce qu'un formulaire a changé et ce qui en part, les secrets à redonner, les refus par champ, la règle
 * d'envoi d'un compte (ADR 0207) et sa version, les outils d'un service (ADR 0129), les lignes de la page racine. Les
 * codes sont ceux du moteur (`vocab/access.py`, `adapters/mail/config.py`, `app/me/`). Tout se teste sur la JVM.
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

/** Ce qu'ouvre ce qu'on te partage : une boîte dans Mail, un compte dans Teams, un service sur sa page. */
enum class ShareOpens { MAIL, TEAMS, SERVICE }

fun openOf(kind: String): ShareOpens = when (kind) {
    ShareKinds.TEAMS -> ShareOpens.TEAMS
    ShareKinds.MCP -> ShareOpens.SERVICE
    else -> ShareOpens.MAIL
}

// ── Les boîtes ──────────────────────────────────────────────────────────

/** Son état : inactive, incomplète, en erreur, prête. */
fun boxState(enabled: Boolean, ready: Boolean, error: String): Pair<Tone, String> = when {
    !enabled -> Tone.NEUTRAL to "inactive"
    !ready -> Tone.WARN to "incomplète"
    error.isNotBlank() -> Tone.DANGER to "erreur"
    else -> Tone.OK to "prête"
}

fun boxState(b: MailBox): Pair<Tone, String> = boxState(b.enabled, b.ready, b.error)

/** Comment elle y écrit : en son nom, en assistante, à ta place. */
val VOICES: List<Pair<String, String>> = listOf(
    Voices.HER to "En son nom",
    Voices.ASSISTANT to "En assistante",
    Voices.OWNER to "À ta place",
)

fun voiceWords(voice: String): String = when (voice) {
    Voices.HER -> "elle y écrit en son nom"
    Voices.ASSISTANT -> "elle y écrit en assistante"
    Voices.OWNER -> "elle y écrit à ta place"
    else -> ""
}

fun authWords(auth: String): String =
    if (auth == Auths.MICROSOFT) "Microsoft · OAuth2 (code d'appareil)" else "IMAP/SMTP · mot de passe"

/** Les deux connexions d'une boîte : par mot de passe, ou par un compte Microsoft. */
val AUTHS: List<Pair<String, String>> = listOf(
    Auths.PASSWORD to "Par mot de passe",
    Auths.MICROSOFT to "Par un compte Microsoft",
)

val SMTP_SECURITY: List<Pair<String, String>> = listOf(
    "starttls" to "STARTTLS (587)",
    "ssl" to "SSL (465)",
    "none" to "aucune (tests)",
)

/** Le non-lu de la réception d'une boîte. */
fun unseenOf(b: MailBox): Int = b.folders.filter { it.role == "inbox" || it.name == "INBOX" }.sumOf { it.unseen }

/** Ce qu'en dit la liste : relevée quand, ses non-lus, ses brouillons ; ou sa dernière erreur. */
fun boxStatusLine(b: MailBox, now: Long): String {
    val polled = if (b.lastPoll > 0) "relevée ${ago(b.lastPoll, now)}" else "pas encore relevée"
    if (b.error.isNotBlank()) {
        return "${if (b.lastPoll > 0) "dernier relevé ${ago(b.lastPoll, now)}" else "pas encore relevée"} : ${b.error}"
    }
    val parts = mutableListOf(polled)
    val unseen = unseenOf(b)
    if (unseen > 0) parts += "$unseen non lu${if (unseen > 1) "s" else ""}"
    if (b.draftsWaiting > 0) parts += "${b.draftsWaiting} brouillon${if (b.draftsWaiting > 1) "s" else ""} d'elle à relire"
    return parts.joinToString(" · ")
}

/** Une boîte qu'on te partage, en une phrase : ce que son niveau t'ouvre. */
fun sharedBoxSentence(b: MailBox): String {
    val owner = b.ownerName.ifBlank { "Son propriétaire" }
    return when (b.level) {
        Levels.PREPARE -> "$owner te l'a ouverte en lecture et préparation : tu la lis dans Mail, et Mika peut t'y préparer des réponses que $owner approuve."
        Levels.USE -> "$owner te l'a ouverte pour t'en servir : Mika s'en sert pour toi, en tête-à-tête, comme pour $owner."
        else -> "$owner te l'a ouverte en lecture : tu la lis dans Mail ; tu ne peux ni répondre ni ranger."
    }
}

/** Le nom d'une boîte partagée : « Boîte de Léa ». */
fun sharedBoxTitle(b: MailBox): String =
    if (b.ownerName.isNotBlank()) "Boîte ${ofName(firstName(b.ownerName))}" else b.name.ifBlank { b.key }

/** Les fournisseurs d'« Ajouter une boîte ». */
enum class Provider(val title: String, val description: String) {
    MICROSOFT("Microsoft", "Outlook.com, Hotmail, Live : connexion par code d'appareil (OAuth2)"),
    DAVMAIL("Exchange pro", "Ta boîte de travail par la passerelle DavMail (O365Graph) sur la machine de Mika"),
    GMAIL("Gmail", "Avec un mot de passe d'application"),
    IMAP("Autre", "N'importe quelle boîte IMAP et SMTP, par mot de passe"),
}

/** Ce qu'on peut proposer : la passerelle DavMail vit sur la machine de Mika, qu'une personne qui n'est pas opératrice
 *  ne fait pas joindre (l'API refuse la boucle locale et le réseau privé). Pas encore su : tout. */
fun providersFor(operator: Boolean?): List<Provider> =
    if (operator == false) Provider.entries.filter { it != Provider.DAVMAIL } else Provider.entries

/** Les réglages de départ d'une boîte, selon son fournisseur. */
fun providerPreset(p: Provider): BoxValues = when (p) {
    Provider.MICROSOFT -> BoxValues(
        auth = Auths.MICROSOFT, imapHost = "outlook.office365.com", imapPort = 993, imapSsl = true,
        smtpHost = "smtp-mail.outlook.com", smtpPort = 587, smtpSecurity = "starttls", oauthTenant = "consumers",
    )
    Provider.GMAIL -> BoxValues(
        auth = Auths.PASSWORD, imapHost = "imap.gmail.com", imapPort = 993, imapSsl = true, smtpHost = "smtp.gmail.com",
        smtpPort = 587, smtpSecurity = "starttls", saveSent = false,
    )
    Provider.DAVMAIL -> BoxValues(
        auth = Auths.PASSWORD, imapHost = "127.0.0.1", imapPort = 1143, imapSsl = false, smtpHost = "127.0.0.1",
        smtpPort = 1025, smtpSecurity = "none",
    )
    Provider.IMAP -> BoxValues(auth = Auths.PASSWORD, imapPort = 993, imapSsl = true, smtpPort = 587, smtpSecurity = "starttls")
}

/** La sécurité SMTP que son port appelle (465 : SSL ; 587 : STARTTLS), sinon celle qu'on avait. */
fun securityFor(port: Int, current: String): String = when (port) {
    465 -> "ssl"
    587 -> "starttls"
    else -> current
}

/** Ce qu'on tape pour une boîte nouvelle (les ports en texte : le champ peut être vide ou faux). */
data class NewBox(
    val address: String = "",
    val label: String = "",
    val user: String = "",
    val password: String = "",
    val imapHost: String = "",
    val imapPort: String = "",
    val smtpHost: String = "",
    val smtpPort: String = "",
    val oauthClientId: String = "",
    val oauthTenant: String = "",
) {
    companion object {
        /** Le formulaire tel qu'il s'ouvre pour ce fournisseur : ses serveurs et ses ports déjà remplis. */
        fun of(p: Provider): NewBox {
            val preset = providerPreset(p)
            return NewBox(
                imapHost = preset.imapHost, imapPort = preset.imapPort.toString(), smtpHost = preset.smtpHost,
                smtpPort = preset.smtpPort.toString(), oauthTenant = preset.oauthTenant,
            )
        }
    }
}

/** Ce qu'il manque ou ne va pas avant d'envoyer une boîte nouvelle, par champ. */
fun newBoxProblems(p: Provider, typed: NewBox): Map<String, String> {
    val out = linkedMapOf<String, String>()
    if (typed.address.isBlank()) out["address"] = "son adresse"
    if (p != Provider.MICROSOFT) {
        out += rangeProblems(mapOf("imap_port" to typed.imapPort.trim(), "smtp_port" to typed.smtpPort.trim()).filterValues { it.isNotEmpty() })
    }
    return out
}

/** Les valeurs d'une boîte nouvelle : le préréglage du fournisseur, ce qui est tapé, l'adresse pour utilisateur. */
fun newBoxValues(p: Provider, typed: NewBox): JsonObject {
    val preset = providerPreset(p)
    val address = typed.address.trim()
    val label = typed.label.trim().ifEmpty { address.substringBefore('@') }
    val base = linkedMapOf<String, JsonElement>(
        "auth" to JsonPrimitive(preset.auth),
        "address" to JsonPrimitive(address),
        "label" to JsonPrimitive(label),
    )
    if (p == Provider.MICROSOFT) {
        base += mapOf(
            "imap_host" to JsonPrimitive(preset.imapHost), "imap_port" to JsonPrimitive(preset.imapPort),
            "imap_ssl" to JsonPrimitive(preset.imapSsl), "smtp_host" to JsonPrimitive(preset.smtpHost),
            "smtp_port" to JsonPrimitive(preset.smtpPort), "smtp_security" to JsonPrimitive(preset.smtpSecurity),
            "user" to JsonPrimitive(address), "oauth_client_id" to JsonPrimitive(typed.oauthClientId.trim()),
            "oauth_tenant" to JsonPrimitive(typed.oauthTenant.trim().ifEmpty { "consumers" }),
        )
        return JsonObject(base)
    }
    val imapPort = typed.imapPort.trim().toIntOrNull()?.takeIf { it > 0 } ?: preset.imapPort
    val smtpPort = typed.smtpPort.trim().toIntOrNull()?.takeIf { it > 0 } ?: preset.smtpPort
    base += mapOf(
        "imap_ssl" to JsonPrimitive(preset.imapSsl),
        "user" to JsonPrimitive(typed.user.trim().ifEmpty { address }),
        "password" to JsonPrimitive(typed.password),
        "imap_host" to JsonPrimitive(typed.imapHost.trim()),
        "imap_port" to JsonPrimitive(imapPort),
        "smtp_host" to JsonPrimitive(typed.smtpHost.trim()),
        "smtp_port" to JsonPrimitive(smtpPort),
        "smtp_security" to JsonPrimitive(securityFor(smtpPort, preset.smtpSecurity)),
    )
    if (!preset.saveSent) base["save_sent"] = JsonPrimitive(false)
    return JsonObject(base)
}

/** Des noms de dossiers tapés à la main (avant la première relève) : séparés par des virgules ou des retours. */
fun foldersOf(text: String): List<String> = text.split(',', '\n').map { it.trim() }.filter { it.isNotEmpty() }

/** Les dossiers à cocher : ceux que le serveur connaît, puis ceux qu'on a choisis et qu'il ne connaît pas (encore). */
fun folderChoices(box: MailBox?, chosen: List<String>): List<Pair<String, String>> {
    val known = box?.folders.orEmpty().map { it.name to it.shown }
    return known + chosen.filter { n -> known.none { it.first == n } }.map { it to it }
}

// ── Les formulaires ─────────────────────────────────────────────────────

/** Ce qui a changé d'un formulaire : les champs dont la valeur n'est plus celle de départ. */
fun changes(before: JsonObject, after: JsonObject): JsonObject = JsonObject(after.filter { (k, v) -> before[k] != v })

private fun json(values: BoxValues): JsonObject = MikaJson.encodeToJsonElement(BoxValues.serializer(), values).jsonObject

/** Ce qui part au serveur d'une boîte réglée : ce qui a changé, et un secret seulement s'il est tapé (vide : gardé). */
fun boxChanges(before: BoxValues, after: BoxValues, password: String = "", smtpPassword: String = ""): JsonObject {
    val out = changes(json(before), json(after)).toMutableMap()
    if (password.isNotEmpty()) out["password"] = JsonPrimitive(password)
    if (smtpPassword.isNotEmpty()) out["smtp_password"] = JsonPrimitive(smtpPassword)
    return JsonObject(out)
}

/** Ce qui part d'un compte Teams réglé : ce qui a changé. */
fun teamsChanges(before: TeamsValues, after: TeamsValues): JsonObject = changes(
    MikaJson.encodeToJsonElement(TeamsValues.serializer(), before).jsonObject,
    MikaJson.encodeToJsonElement(TeamsValues.serializer(), after).jsonObject,
)

/** Les bornes que le serveur ne vérifie pas d'avance : un port, la fenêtre de relève. */
private val RANGES = mapOf(
    "imap_port" to Triple(1, 65_535, "un port entre 1 et 65535"),
    "smtp_port" to Triple(1, 65_535, "un port entre 1 et 65535"),
    "since_days" to Triple(1, 60, "entre 1 et 60 jours"),
)

/** Ce qui sort de ses bornes, par champ ; [values] : la valeur telle que tapée. */
fun rangeProblems(values: Map<String, String>): Map<String, String> {
    val out = linkedMapOf<String, String>()
    for ((name, bound) in RANGES) {
        val raw = values[name] ?: continue
        val n = raw.trim().toIntOrNull()
        if (n == null || n < bound.first || n > bound.second) out[name] = bound.third
    }
    return out
}

/** La connexion de chaque secret : quand l'une de ces valeurs change, le secret gardé se redonne (`app/me/settings.py`,
 *  `IMAP_CONNECTION` et `SMTP_CONNECTION`). */
val CONNECTION: Map<String, List<String>> = mapOf(
    "password" to listOf("auth", "imap_host", "imap_port", "imap_ssl", "user", "oauth_client_id", "oauth_tenant"),
    "smtp_password" to listOf("smtp_host", "smtp_port", "smtp_security", "smtp_user"),
)

/**
 * Les secrets gardés qu'un enregistrement doit redonner : sa connexion change et rien n'est tapé à sa place — le serveur
 * le refuserait (400, `_kept_secrets`). L'envoi sans mot de passe à lui se sert de celui de la lecture : changer le
 * serveur d'envoi le redemande aussi, sauf s'il est redonné pour lire dans le même envoi. Une connexion dont le serveur
 * est vidé ne redemande rien ; une boîte qui entre par Microsoft n'a aucun mot de passe. [imapHost], [smtpHost] : ses
 * serveurs tels que le formulaire les montre.
 */
fun secretsToRetype(changes: JsonObject, kept: BoxSecrets, auth: String, imapHost: String, smtpHost: String): Map<String, String> {
    val out = linkedMapOf<String, String>()
    if (auth == Auths.MICROSOFT) return out
    for (secret in listOf("password", "smtp_password")) {
        if (changes.containsKey(secret)) continue
        val host = if (secret == "password") imapHost else smtpHost
        if (host.isBlank()) continue // la connexion est retirée : rien ne part
        val outgoing = (if (secret == "password") kept.password else kept.smtpPassword) ||
            (secret == "smtp_password" && kept.password && !changes.containsKey("password"))
        if (!outgoing || CONNECTION.getValue(secret).none { changes.containsKey(it) }) continue
        out[secret] = "à redonner : la connexion a changé, il ne part pas vers un autre serveur"
    }
    return out
}

/** Les messages d'un refus, par champ : la dernière partie du chemin (`accounts.pro.imap_port` → `imap_port`). */
fun fieldErrors(fields: Map<String, String>): Map<String, String> {
    val out = linkedMapOf<String, String>()
    for ((path, message) in fields) {
        val name = path.substringAfterLast('.').ifEmpty { path }
        out[name] = out[name]?.let { "$it ; $message" } ?: message
    }
    return out
}

/** Les noms des champs d'une boîte, tels que le formulaire les montre. */
val BOX_LABELS: Map<String, String> = mapOf(
    "label" to "Nom court", "address" to "Adresse", "enabled" to "Active", "auth" to "Connexion",
    "imap_host" to "Serveur IMAP", "imap_port" to "Port IMAP", "imap_ssl" to "SSL", "user" to "Utilisateur",
    "password" to "Mot de passe", "folders" to "Dossiers relevés", "sync_all" to "Synchroniser tous les dossiers",
    "since_days" to "Fenêtre de relève", "oauth_client_id" to "Application Microsoft", "oauth_tenant" to "Annuaire Microsoft",
    "smtp_host" to "Serveur SMTP", "smtp_port" to "Port SMTP", "smtp_security" to "Sécurité SMTP",
    "smtp_user" to "Utilisateur SMTP", "smtp_password" to "Mot de passe SMTP", "save_sent" to "Copier les envois",
    "voice" to "Elle écrit", "display_name" to "Ton nom", "sender_name" to "Son nom d'expéditrice", "tone" to "Son ton",
    "instructions" to "Consignes", "signature" to "Signature",
)

/** Les champs que le formulaire d'une boîte montre pour ces valeurs (certains ne valent que pour un choix). */
fun boxShownFields(v: BoxValues): Set<String> {
    val hidden = buildSet {
        if (v.auth == Auths.MICROSOFT) addAll(listOf("password", "smtp_password")) else addAll(listOf("oauth_client_id", "oauth_tenant"))
        if (v.voice == Voices.HER) add("display_name") else add("sender_name")
    }
    return BOX_LABELS.keys - hidden
}

val TEAMS_LABELS: Map<String, String> = mapOf(
    "label" to "Nom affiché", "enabled" to "Actif", "display_name" to "Ton nom", "tone" to "Ton",
    "instructions" to "Consignes", "sign" to "Signer ses réponses", "signature" to "Signature",
)

val SERVICE_LABELS: Map<String, String> = mapOf(
    "name" to "Son nom", "purpose" to "À quoi il lui sert", "when_to_use" to "Quand y penser", "url" to "Adresse",
    "headers" to "En-têtes secrets", "secret_headers" to "En-têtes secrets", "enabled" to "Actif",
)

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

// ── Les comptes Teams ───────────────────────────────────────────────────

/** Ce que l'on sait de son extension : inactif, rien reçu, ou son dernier envoi. */
fun batchWords(a: TeamsAccount, now: Long): Pair<Tone, String> = when {
    !a.enabled -> Tone.NEUTRAL to "inactif"
    a.lastBatch <= 0 -> Tone.WARN to "rien reçu de son extension"
    else -> Tone.OK to "dernier envoi ${ago(a.lastBatch, now)}"
}

/** Un compte qu'on te partage, en une phrase. */
fun sharedAccountSentence(a: TeamsAccount): String {
    val owner = a.ownerName.ifBlank { "Son propriétaire" }
    return "$owner te l'a ouvert : ${shareWords(a.level).lowercase()}. Tu le lis dans Teams ; seul son propriétaire le règle."
}

// ── Les services MCP (ADR 0192) ─────────────────────────────────────────

fun stateWords(state: String): Pair<Tone, String> = when (state) {
    "connecte" -> Tone.OK to "connecté"
    "jamais" -> Tone.NEUTRAL to "jamais joint"
    "erreur" -> Tone.DANGER to "erreur"
    "panne" -> Tone.DANGER to "en panne"
    "incomplet" -> Tone.WARN to "incomplet"
    "inactif" -> Tone.NEUTRAL to "inactif"
    else -> Tone.NEUTRAL to state
}

/** Un état qui dit une panne : son détail se montre. */
fun serviceTrouble(state: String): Boolean = state == "erreur" || state == "panne" || state == "incomplet"

/** Ses outils servis (il lit ou il agit), sur combien, et combien attendent qu'on les regarde (jamais choisis, changés). */
data class Served(val served: Int, val total: Int, val review: Int)

fun servedOf(tools: List<ServiceTool>): Served = Served(
    served = tools.count { it.choice == ToolChoices.READ || it.choice == ToolChoices.ACT },
    total = tools.size,
    review = tools.count { it.choice.isEmpty() || it.waiting },
)

val CHOICES: List<Pair<String, String>> = listOf(
    ToolChoices.OFF to "Coupé",
    ToolChoices.READ to "Il lit",
    ToolChoices.ACT to "Il agit",
)

fun choiceWords(choice: String): String = CHOICES.firstOrNull { it.first == choice }?.second ?: choice

/** L'état d'un outil : nouveau, changé, coupé, servi. */
fun toolState(t: ServiceTool): Pair<Tone, String> = when {
    t.new -> Tone.INFO to "nouveau"
    t.changed -> Tone.WARN to "changé"
    t.choice == ToolChoices.OFF -> Tone.NEUTRAL to "coupé"
    else -> Tone.OK to "servi"
}

/** Le choix qu'un outil montre : aucun s'il attend (nouveau, changé) — le choisir, même comme avant, le décide. */
fun shownChoice(t: ServiceTool): String = if (t.waiting) "" else t.choice

/** Les choix d'outils qui partent : ceux qui ne sont plus ceux que l'outil montrait. */
fun toolChoiceChanges(tools: List<ServiceTool>, picked: Map<String, String>): Map<String, String> =
    tools.mapNotNull { t ->
        val p = picked[t.remote] ?: return@mapNotNull null
        if (p in ToolChoices.ALL && p != shownChoice(t)) t.remote to p else null
    }.toMap()

/**
 * Ce qui part d'un service réglé : ce qui a changé ; des en-têtes seulement s'ils sont tapés (vides : gardés) ;
 * [clearHeaders] : les retirer (ADR 0236), sauf si d'autres sont tapés à leur place.
 */
fun serviceChanges(
    before: Service,
    purpose: String,
    whenToUse: String,
    url: String,
    enabled: Boolean,
    headers: String,
    clearHeaders: Boolean = false,
): JsonObject {
    val out = linkedMapOf<String, JsonElement>()
    if (purpose != before.purpose) out["purpose"] = JsonPrimitive(purpose)
    if (whenToUse != before.whenToUse) out["when_to_use"] = JsonPrimitive(whenToUse)
    if (url.trim() != before.url) out["url"] = JsonPrimitive(url.trim())
    if (enabled != before.enabled) out["enabled"] = JsonPrimitive(enabled)
    if (headers.isNotBlank()) out["secret_headers"] = JsonPrimitive(headers)
    else if (clearHeaders && before.headers) out["clear_headers"] = JsonPrimitive(true)
    return JsonObject(out)
}

/** Où une adresse mène : son schéma, son hôte, son port (celui du schéma s'il n'en dit pas). Illisible : elle-même. */
fun urlOrigin(url: String): String = try {
    val u = URI(url.trim())
    val scheme = u.scheme?.lowercase().orEmpty()
    val host = (u.host ?: u.rawAuthority?.substringAfterLast('@')?.substringBefore(':')).orEmpty().lowercase()
    val port = if (u.port >= 0) u.port else DEFAULT_PORTS[scheme] ?: -1
    "$scheme://$host:$port"
} catch (_: URISyntaxException) {
    url.trim().lowercase()
}

private val DEFAULT_PORTS = mapOf("https" to 443, "http" to 80)

/** Ce que dit le champ des en-têtes quand l'adresse mène ailleurs (les mots du serveur, `app/me/mcp.py`). */
const val HEADERS_TO_RETYPE = "à redonner : l'adresse a changé (ou à retirer)"

/**
 * Les en-têtes gardés d'un service à redonner avant d'envoyer [changes] (ADR 0236) : son adresse mène ailleurs — un
 * autre hôte, schéma ou port — et ni de nouveaux en-têtes ni leur retrait ne partent ; le serveur refuserait (400). Un
 * autre chemin sur le même serveur, ou un service sans en-têtes gardés, ne redemande rien.
 */
fun headersToRetype(before: Service, changes: JsonObject): Map<String, String> {
    if (!before.headers || "url" !in changes || "secret_headers" in changes || "clear_headers" in changes) return emptyMap()
    return if (urlOrigin(changes.text("url").orEmpty()) == urlOrigin(before.url)) emptyMap() else mapOf("secret_headers" to HEADERS_TO_RETYPE)
}

/** Les bornes de l'API pour brancher un service (en caractères) : au-delà, elle refuse. */
object McpLimits {
    const val NAME = 24
    const val PURPOSE = 1024
    const val URL = 500
    const val HEADERS = 8000
}

private val SERVICE_NAME = Regex("^[a-z][a-z0-9_]{0,23}$")

/** Le nom d'un service : il entre dans le nom de ses outils (`mcp_<nom>_<outil>`). */
fun serviceNameProblem(name: String): String = when {
    name.isEmpty() -> "Un nom court."
    SERVICE_NAME.matches(name) -> ""
    else -> "Des minuscules, chiffres et _, en commençant par une lettre (24 au plus)."
}

fun urlProblem(url: String): String = when {
    url.isBlank() -> "Son adresse."
    Regex("""^https://\S+$""", RegexOption.IGNORE_CASE).matches(url.trim()) -> ""
    else -> "Une adresse https://… (l'adresse MCP « streamable HTTP » du service)."
}

/** Qui une ligne désigne : « toi » pour la tienne — l'API le dit (`mine`), jamais un nom comparé. */
fun whoWords(a: AccessLine): String = if (a.mine) "toi" else a.who.ifBlank { "tout le monde" }

/** Avec qui il est partagé : ses lignes qui ne sont pas la tienne. */
fun sharedWith(s: Service): String = s.access.filter { it.who.isNotBlank() && !it.mine }.joinToString(", ") { it.who }

/** La ligne par défaut d'un service : fermée (personne d'autre), ou ce qu'elle ouvre. */
fun defaultWords(d: AccessLine?): String =
    if (d == null || (d.read == "non" && d.act == "non")) "fermé : personne d'autre"
    else "il lit : ${d.readWords} · il agit : ${d.actWords} · ${d.keepWords}"

/** Ce que son niveau lui ouvre d'un service qu'on lui partage, en une phrase. */
fun receivedSentence(r: ReceivedService): String {
    val owner = r.ownerName.ifBlank { "Son propriétaire" }
    val what = if (r.level == Levels.USE) {
        "Mika s'en sert pour toi : ses outils qui lisent, et ceux qui agissent."
    } else {
        "Mika s'en sert pour toi, seulement ses outils qui lisent."
    }
    return "$owner te l'a ouvert : ${shareWords(r.level).lowercase()}. $what Seul son propriétaire le règle."
}

/** Pour toi, ce qu'elle fait d'un outil servi d'un service partagé : ce que dit ta ligne. */
fun forYou(r: ReceivedService, choice: String): String =
    (if (choice == ToolChoices.ACT) r.line.actWords else r.line.readWords).ifBlank { "non" }

// ── Tes téléphones ──────────────────────────────────────────────────────

/** Ce qu'un téléphone reçoit application fermée : ses notifications (Firebase, ADR 0077), ou rien. */
fun pushWords(push: Boolean): String = if (push) "même application fermée" else "sans notifications"

/**
 * Une ligne de la liste : le téléphone, si c'est celui-ci ([mine]), et s'il pourrait l'être sans qu'on le sache
 * ([unsure] : une session ouverte avant que l'app garde l'identifiant de son jeton, et un autre téléphone du même nom
 * que celui-ci). « Révoquer » ne s'offre que sur un autre téléphone sûr ([revocable]) : sur un « peut-être celui-ci »,
 * on se révoquerait soi-même pendant que l'autre continue.
 */
data class PhoneRow(val phone: PhoneDevice, val mine: Boolean, val unsure: Boolean = false) {
    val revocable: Boolean get() = !phone.revoked && !mine && !unsure
}

/** Tes téléphones dans l'ordre de la page : celui-ci d'abord, puis les autres du plus récemment servi, les révoqués à
 *  la fin. [tokenId] : l'identifiant du jeton de cette session (`null` : une session d'avant, reconnue par son nom). */
fun phoneRows(phones: List<PhoneDevice>, deviceLabel: String, tokenId: Long?): List<PhoneRow> {
    val mine = thisPhone(phones, deviceLabel, tokenId)
    fun unsure(p: PhoneDevice) = tokenId == null && p != mine && !p.revoked && p.label.trim() == deviceLabel.trim()
    return phones.sortedWith(compareBy<PhoneDevice>({ it != mine }, { it.revoked }, { -it.lastUsed }, { -it.id }))
        .map { PhoneRow(it, it == mine, unsure(it)) }
}

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
