package fr.qwartz.mika.data.moi.mail

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.ago
import fr.qwartz.mika.data.moi.firstName
import fr.qwartz.mika.data.moi.ofName
import fr.qwartz.mika.data.moi.settings.changes
import fr.qwartz.mika.data.moi.settings.unseenOf
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject

/*
 * Les règles pures de Paramètres › Boîtes mail, portées du client web sans les réinventer
 * (`frontendv2/src/screens/mail/words.ts` et `settings.ts`) : l'état d'une boîte, comment elle y écrit, une boîte
 * qu'on te partage, ses fournisseurs et leurs préréglages, une boîte nouvelle, ses dossiers, ce qu'un formulaire en
 * envoie, ses bornes, les secrets à redonner, les noms de ses champs. Les codes sont ceux du moteur
 * (`adapters/mail/config.py`, `app/domains/mail/account_settings.py`). Tout se teste sur la JVM.
 */

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
    MICROSOFT("Microsoft", "Outlook.com, Hotmail, Live : tu te connectes chez Microsoft, par un code"),
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

// ── Ses formulaires ─────────────────────────────────────────────────────

private fun json(values: BoxValues): JsonObject = MikaJson.encodeToJsonElement(BoxValues.serializer(), values).jsonObject

/** Ce qui part au serveur d'une boîte réglée : ce qui a changé, et un secret seulement s'il est tapé (vide : gardé). */
fun boxChanges(before: BoxValues, after: BoxValues, password: String = "", smtpPassword: String = ""): JsonObject {
    val out = changes(json(before), json(after)).toMutableMap()
    if (password.isNotEmpty()) out["password"] = JsonPrimitive(password)
    if (smtpPassword.isNotEmpty()) out["smtp_password"] = JsonPrimitive(smtpPassword)
    return JsonObject(out)
}

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

/** La connexion de chaque secret : quand l'une de ces valeurs change, le secret gardé se redonne
 *  (`app/domains/mail/account_settings.py`, `IMAP_CONNECTION` et `SMTP_CONNECTION`). */
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

/** Les noms des champs d'une boîte, tels que le formulaire les montre. */
val BOX_LABELS: Map<String, String> = mapOf(
    "label" to "Nom court", "address" to "Adresse", "enabled" to "Active", "auth" to "Connexion",
    "imap_host" to "Serveur IMAP", "imap_port" to "Port IMAP", "imap_ssl" to "SSL", "user" to "Utilisateur",
    "password" to "Mot de passe", "folders" to "Dossiers relevés", "sync_all" to "Synchroniser tous les dossiers",
    "keep_all" to "Tout garder en local",
    "since_days" to "Fenêtre de relève", "triage_instructions" to "Consignes de tri",
    "oauth_client_id" to "Application Microsoft", "oauth_tenant" to "Annuaire Microsoft",
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
