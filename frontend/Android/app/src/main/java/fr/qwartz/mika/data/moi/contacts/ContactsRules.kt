package fr.qwartz.mika.data.moi.contacts

import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.mail.MailContact
import kotlin.math.roundToInt

/*
 * Les règles pures de Contacts (ADR 0298), portées du client web (`frontendv2/src/screens/contacts/view.ts`) et de la
 * maquette validée (`frontend/Android/maquette/ecrans/contacts.js`) sans rien réinventer : ce qu'une ligne et une
 * fiche disent en mots, ce qui identifie un contact, d'où vient un fait, où vous vous croisez ; et, pour Écrire, les
 * destinataires proposés depuis tous tes contacts — une ligne par adresse, une adresse générique marquée. Tout se teste
 * sur la JVM.
 */

/** Les bornes de l'API (`app/me/contacts.py`). */
object ContactsLimits {
    /** `q` de `/contacts`, en caractères. */
    const val SEARCH = 200
    /** Une page de la liste. */
    const val PAGE = 50
}

/** Les choix de la liste : la sorte qu'on montre (vide : tous). */
val CONTACT_KIND_CHOICES = listOf("", ContactKinds.PERSON, ContactKinds.ORG)

/** Combien en a chaque choix (sans la recherche, comme l'API). */
fun ContactsCounts.of(kind: String): Int = when (kind) {
    ContactKinds.PERSON -> person
    ContactKinds.ORG -> org
    else -> all
}

/** Ce qu'on cherche, borné comme l'API (en caractères, pas en unités UTF-16 : un emoji compte pour un). */
fun clippedQuery(q: String): String {
    if (q.codePointCount(0, q.length) <= ContactsLimits.SEARCH) return q
    return q.substring(0, q.offsetByCodePoints(0, ContactsLimits.SEARCH))
}

/** « 1 personne », « 5 personnes ». */
fun plural(n: Int, one: String, many: String): String = "$n ${if (n > 1) many else one}"

/** Ce qu'on sait de lui en une ligne : son poste et son service. */
fun idea(title: String, department: String): String = listOf(title, department).filter { it.isNotBlank() }.joinToString(" · ")

/** Ce que dit une fiche reliée : « parle aussi à Mika » s'il lui a écrit, sinon « a un compte » (vide : pas reliée). */
fun linkedWords(linked: Boolean, talks: Boolean): String = when {
    !linked -> ""
    talks -> "parle aussi à Mika"
    else -> "a un compte"
}

/**
 * La seconde ligne d'une entrée de la liste (la maquette, `ligneIdee`) : son poste et son organisation ; une
 * organisation, combien de ses personnes sont parmi tes contacts. Sans rien de cela, un de ses identifiants, sinon s'il
 * a un compte.
 */
fun lineSub(c: ContactLine): String {
    if (c.org) return if (c.members > 0) "Organisation · ${plural(c.members, "personne", "personnes")}" else "Organisation"
    val said = listOf(c.title.ifBlank { c.department }, c.organisation?.name.orEmpty()).filter { it.isNotBlank() }.joinToString(" · ")
    return said.ifBlank { c.identifiers.firstOrNull()?.value.orEmpty() }.ifBlank { linkedWords(c.linked, c.talks) }
}

/** Ce que la tête de la fiche dit sous son nom : son poste et son service ; une organisation, ses personnes. */
fun headLine(s: ContactSheet): String = when {
    !s.org -> idea(s.title, s.department)
    s.membersTotal > 0 -> "Organisation · ${plural(s.membersTotal, "personne", "personnes")} parmi tes contacts"
    else -> "Organisation"
}

/** « dernier échange 14:09 », « dernier échange hier ». */
fun lastExchange(last: Long, now: Long): String = MoiDates.short(last, now).let { if (it.isEmpty()) "" else "dernier échange $it" }

// ── Ce qui l'identifie ──────────────────────────────────────────────────

object IdentKinds {
    const val EMAIL = "email"
    const val TEAMS = "teams"
    const val PHONE = "phone"
    const val PHONE_APP = "phone_app"
    const val DOMAIN = "domain"
    const val COMPANY = "company"
    const val TENANT = "tenant"
}

/** Sa valeur telle qu'elle se montre : un contact du téléphone, par le nom que lui donne ton carnet (sa clé ne se dit
 *  jamais). */
fun identifierShown(i: ContactIdentifier): String = i.value.ifBlank { i.name }.ifBlank { "hors de ton carnet" }

/** Sa ligne sous la valeur : sa sorte, d'où elle la tient ; une adresse générique le dit dans sa ligne (la maquette :
 *  pas en étiquette au bout, elle mangerait l'adresse). */
fun identifierSub(i: ContactIdentifier): String = listOf(
    if (i.generic) "Adresse générique" else i.label,
    i.where.filter { it.isNotBlank() }.joinToString(", "),
    if (i.generic) "sans personne derrière" else "",
).filter { it.isNotBlank() }.joinToString(" · ")

/** On peut lui écrire à cette adresse d'ici : une adresse d'une personne (pas générique), et le serveur dit qu'une de
 *  tes boîtes envoie (`write`). */
fun writableAt(s: ContactSheet, i: ContactIdentifier): Boolean =
    s.write != null && i.kind == IdentKinds.EMAIL && !i.generic && i.value.isNotBlank()

/** Ce qu'un appui long copie : sa valeur (rien pour un contact du téléphone, dont la clé ne se dit pas). */
fun copied(i: ContactIdentifier): String = i.value

// ── Ce que Mika en sait ─────────────────────────────────────────────────

/** Ce que l'annuaire tient (poste, service, organisation), avant ce qu'elle a compris de ses messages. */
fun profileFacts(s: ContactSheet): List<ContactFact> = s.facts.filter { !it.note }

/** Ce qu'elle a compris de ses derniers messages (une personne seulement). */
fun noteFacts(s: ContactSheet): List<ContactFact> = s.facts.filter { it.note }

/** D'où vient un fait, et sa confiance : « d'après ses messages dans Teams · en tête-à-tête · sûre à 80 % ». */
fun noteSource(f: ContactFact): String = listOf(
    if (f.from.isNotBlank()) "d'après ${f.from}" else "",
    f.place,
    f.confidence?.let { "sûre à ${(it * 100).roundToInt()} %" }.orEmpty(),
).filter { it.isNotBlank() }.joinToString(" · ")

/** Ce qu'en dit la fiche d'un fait de son profil : « d'après son profil Teams ». */
fun profileFrom(f: ContactFact): String = if (f.from.isNotBlank()) "d'après ${f.from}" else ""

/** D'où vient ce que Mika en sait, en une phrase. */
fun privacyNote(name: String, privacy: String): String = if (privacy == ContactSheet.PRIVACY_MINE) {
    "Ce que Mika sait de $name vient de tes comptes et de ce que tu lui as dit : elle n'en parle qu'à toi."
} else {
    "Ce que Mika sait de $name vient aussi d'un compte qu'on te partage ou d'un des siens : d'autres que toi peuvent le lire."
}

/** Ce que demande la confirmation de l'oubli d'un contact. */
fun forgetQuestion(name: String): String =
    "Mika oubliera $name : sa fiche, et ce que Teams, le courrier, ton téléphone et sa mémoire en gardaient. Les messages restent dans leurs boîtes."

/** Ce que demande la confirmation de l'oubli d'un fait. */
fun forgetFactQuestion(value: String): String = "Mika oubliera ce qu'elle avait compris : « $value »"

// ── Où vous vous croisez ────────────────────────────────────────────────

/** L'icône d'une ligne : Teams, un mail, une messagerie du téléphone (WhatsApp) ou ses SMS. */
enum class PlaceIcon { TEAMS, MAIL, CHAT, PHONE }

/** Une ligne de « Où vous vous croisez » : son icône, son titre, son détail. */
data class PlaceLine(val icon: PlaceIcon, val title: String, val detail: String)

private val TEAMS_KINDS = mapOf("dm" to "tête-à-tête", "group" to "groupe", "channel" to "canal", "meeting" to "réunion")
private val CHAT_APPS = setOf("whatsapp", "whatsapp_business")

/** « tête-à-tête · 41 messages · 13:41 », « Pro · 23 mails · 13:40 », « groupe WhatsApp · 3 messages · 13:47 ». */
fun placeLine(p: ContactPlace, name: String, now: Long): PlaceLine {
    val at = MoiDates.short(p.last, now)
    return when (p.source) {
        PlaceSources.TEAMS -> PlaceLine(
            PlaceIcon.TEAMS,
            p.title.ifBlank { if (p.kind == "dm") name else "Conversation Teams" },
            listOf(TEAMS_KINDS[p.kind] ?: "conversation", plural(p.count, "message", "messages"), at).filter { it.isNotBlank() }.joinToString(" · "),
        )
        PlaceSources.MAIL -> PlaceLine(
            PlaceIcon.MAIL,
            p.subject.ifBlank { plural(p.count, "mail", "mails") },
            listOf(p.boxName, if (p.subject.isNotBlank() && p.count > 0) plural(p.count, "mail", "mails") else "", at)
                .filter { it.isNotBlank() }.joinToString(" · "),
        )
        else -> PlaceLine(
            if (p.app in CHAT_APPS) PlaceIcon.CHAT else PlaceIcon.PHONE,
            p.title.ifBlank { name },
            listOf(if (p.group) "groupe ${p.appName}".trim() else p.appName, plural(p.count, "message", "messages"), at)
                .filter { it.isNotBlank() }.joinToString(" · "),
        )
    }
}

// ── Écrire : les destinataires proposés ─────────────────────────────────

/** Ce qu'une proposition dit à droite : d'où vient l'adresse (une boîte et combien de mails, ou son profil Teams). */
data class ProposalHint(val teams: Boolean, val top: String, val bottom: String)

/**
 * Un destinataire proposé quand on écrit : une ligne par adresse. [contact] : sa fiche (0 : un correspondant du
 * courrier, quand l'annuaire n'est pas là) ; [org] : celle d'une organisation (son carré) ; [generic] : une adresse
 * sans personne derrière, marquée ; [about] : son organisation ou son poste, à côté de son nom.
 */
data class RecipientProposal(
    val name: String,
    val address: String,
    val contact: Int = 0,
    val org: Boolean = false,
    val generic: Boolean = false,
    val about: String = "",
    val hint: ProposalHint? = null,
) {
    /** Son nom, sinon son adresse. */
    val shown: String get() = name.ifBlank { address }
}

/** Au plus tant de destinataires proposés sous un champ. */
const val PROPOSED = 6

/**
 * D'où vient l'adresse d'un contact, d'après ce que dit sa ligne : une personne à une seule adresse, la boîte où elle
 * la voit le plus et combien de mails ; plusieurs adresses ou une organisation, ses boîtes, sans compte (la liste ne dit
 * pas lequel de ses mails vient de quelle adresse) ; sans boîte, son profil Teams.
 */
fun proposalHint(c: ContactLine): ProposalHint? {
    val boxes = c.sources.filter { it.source == PlaceSources.MAIL && it.label.isNotBlank() }
    val emails = c.identifiers.count { it.kind == IdentKinds.EMAIL }
    return when {
        boxes.isNotEmpty() && !c.org && emails == 1 -> boxes.first().let {
            ProposalHint(teams = false, top = it.label, bottom = if (it.count > 0) plural(it.count, "mail", "mails") else "")
        }
        boxes.isNotEmpty() -> ProposalHint(teams = false, top = boxes.take(2).joinToString(", ") { it.label }, bottom = "")
        c.sources.any { it.source == PlaceSources.TEAMS } -> ProposalHint(teams = true, top = "Teams", bottom = "son profil")
        else -> null
    }
}

/**
 * Les destinataires proposés depuis tes contacts (`GET /contacts?q=`, la maquette `proposer`) : une ligne par adresse
 * e-mail, dans l'ordre du serveur (le dernier vu d'abord), les adresses génériques après les personnes ; ce qui est déjà
 * en puce ([chosen], en minuscules) n'est plus proposé. Une adresse d'une organisation est générique : l'annuaire range
 * à son organisation, et jamais à une personne, une adresse sans personne derrière (ADR 0298 ; la fiche le dit,
 * `generic`).
 */
fun proposals(lines: List<ContactLine>, chosen: Set<String>, max: Int = PROPOSED): List<RecipientProposal> {
    val seen = HashSet(chosen)
    val out = mutableListOf<RecipientProposal>()
    for (c in lines) {
        val hint = proposalHint(c)
        for (i in c.identifiers) {
            if (i.kind != IdentKinds.EMAIL || '@' !in i.value || !seen.add(i.value.lowercase())) continue
            out += RecipientProposal(
                name = c.name,
                address = i.value,
                contact = c.id,
                org = c.org,
                generic = c.org,
                about = if (c.org) "" else c.organisation?.name?.ifBlank { null } ?: c.title,
                hint = hint,
            )
        }
    }
    return out.sortedBy { it.generic }.take(max)
}

/** Quand l'annuaire n'est pas là (pas branché, un serveur d'avant) : ses correspondants du courrier, comme avant. */
fun proposalsFromMail(list: List<MailContact>, chosen: Set<String>, max: Int = PROPOSED): List<RecipientProposal> {
    val seen = HashSet(chosen)
    return list.filter { it.address.isNotBlank() && seen.add(it.address.lowercase()) }.take(max).map {
        val n = it.received + it.sent
        RecipientProposal(name = it.name, address = it.address, hint = if (n > 0) ProposalHint(teams = false, top = "", bottom = plural(n, "mail", "mails")) else null)
    }
}
