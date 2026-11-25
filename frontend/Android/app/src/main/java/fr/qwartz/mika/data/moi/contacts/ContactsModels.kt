package fr.qwartz.mika.data.moi.contacts

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * Les formes de Contacts dans l'API par personne (`backendv2/docs/protocole-moi.md` § 12, code `app/domains/contacts/api.py`,
 * ADR 0298) : ceux que Mika connaît pour toi — vus dans tes comptes Teams et tes boîtes, sur ton téléphone, ou dont tu
 * lui as parlé — et leurs organisations. Chaque champ a son défaut : `MikaJson` ignore ce qu'il ne connaît pas (la
 * photo de l'ADR 0300, que l'app ne montre pas), et un champ absent ne casse rien. Les instants sont en millisecondes.
 * Le serveur ne dit que ce que tes comptes en montrent : jamais de qui d'autre c'est le contact, jamais la valeur d'une
 * clé du téléphone ni d'un nom raconté.
 */

/** Les sortes d'un contact. */
object ContactKinds {
    const val PERSON = "person"
    const val ORG = "org"
}

/** D'où elle le connaît : Teams (tous tes comptes ensemble), une boîte (sous son nom), le téléphone par appli
 *  (`whatsapp`, `sms`, sinon `phone`), ce que tu lui as raconté (`told`) ; combien de fois (0 : un profil seul). */
@Serializable
data class ContactSource(
    val source: String = "",
    /** La boîte (`mail`). */
    val account: String = "",
    val label: String = "",
    val count: Int = 0,
)

/** Une fiche nommée (son organisation). */
@Serializable
data class ContactRef(val id: Int = 0, val name: String = "")

/** Un identifiant d'une ligne de la liste (quatre au plus) : sa sorte (`email`, `teams`, `phone`, `domain`…), sa valeur. */
@Serializable
data class ContactIdent(val kind: String = "", val value: String = "")

/** Un contact de la liste. */
@Serializable
data class ContactLine(
    val id: Int = 0,
    val kind: String = ContactKinds.PERSON,
    val name: String = "",
    val title: String = "",
    val department: String = "",
    val organisation: ContactRef? = null,
    /** Sa fiche est reliée à une personne qui a un compte. */
    val linked: Boolean = false,
    /** Cette personne a déjà écrit à Mika (« parle aussi à Mika ») ; sinon elle n'a qu'un compte. */
    val talks: Boolean = false,
    /** Une organisation : ses personnes parmi tes contacts. */
    val members: Int = 0,
    val last: Long = 0,
    val sources: List<ContactSource> = emptyList(),
    /** Quatre au plus, jamais une clé du téléphone ni un nom raconté. */
    val identifiers: List<ContactIdent> = emptyList(),
) {
    val org: Boolean get() = kind == ContactKinds.ORG
}

/** Chaque sorte, sans la recherche (les choix de l'écran). */
@Serializable
data class ContactsCounts(val all: Int = 0, val person: Int = 0, val org: Int = 0)

/** `GET /contacts` : une page, le dernier vu d'abord. */
@Serializable
data class ContactsPage(
    val total: Int = 0,
    val page: Int = 1,
    val size: Int = 50,
    val counts: ContactsCounts = ContactsCounts(),
    val items: List<ContactLine> = emptyList(),
)

/** Ce qui l'identifie, sur sa fiche. */
@Serializable
data class ContactIdentifier(
    /** `teams`, `email`, `phone`, `domain`, `company`, `tenant`, `phone_app`. */
    val kind: String = "",
    /** « E-mail », « Identifiant Teams », « Contact WhatsApp »… */
    val label: String = "",
    /** Vide pour un contact du téléphone : sa clé ne se dit pas ([name] : le nom que lui donne ton carnet). */
    val value: String = "",
    val name: String = "",
    /** D'où elle le tient : « Teams », « son profil Teams », le nom d'une boîte, « ton téléphone »… */
    val where: List<String> = emptyList(),
    /** Une adresse sans personne derrière (rangée à son organisation). */
    val generic: Boolean = false,
)

/** Ce que Mika en sait : ce que l'annuaire tient (`title`, `department`, `organisation`), puis ce qu'elle a compris de
 *  ses derniers messages (`note`). */
@Serializable
data class ContactFact(
    val kind: String = "",
    /** « Poste », « Service », « Organisation » ; vide pour un fait. */
    val label: String = "",
    val value: String = "",
    /** Une organisation : sa fiche ; un fait (`note`) : de quoi l'oublier. */
    val id: Int = 0,
    /** « son profil Teams », « son adresse e-mail » ; un fait : « ses messages dans Teams », « ses mails à Pro ». */
    val from: String = "",
    /** Un fait : sa sorte (`role`, `topic`, `relation`, `expectation`, `manner`, `bond`, `other`). */
    val sort: String = "",
    /** Un fait : sa confiance, de 0 à 1 (`null` : ce n'est pas une lecture). */
    val confidence: Double? = null,
    /** Un fait : où était le message qui le fonde (« en tête-à-tête », « un mail, objet « … » »). */
    val place: String = "",
    val at: Long = 0,
    /** Un fait : il vient d'un de tes comptes, tu peux le faire oublier. */
    val forget: Boolean = false,
) {
    val note: Boolean get() = kind == FactKinds.NOTE
}

object FactKinds {
    const val NOTE = "note"
    const val ORGANISATION = "organisation"
}

/** Où vous vous croisez : une conversation Teams, une boîte, une conversation du téléphone (`source`). */
@Serializable
data class ContactPlace(
    val source: String = "",
    /** Teams : la clé de `teams/thread` ; téléphone : `<appli>|<fil>`. */
    val conversation: String = "",
    val account: String = "",
    /** Teams : son nom ; téléphone : un groupe (vide pour un tête-à-tête). */
    val title: String = "",
    /** Teams : `dm`, `group`, `channel`, `meeting`. */
    val kind: String = "",
    val count: Int = 0,
    val last: Long = 0,
    val box: String = "",
    @SerialName("box_name") val boxName: String = "",
    /** Une boîte : son dernier mail reçu de lui (vide s'il n'y en a pas). */
    val ref: String = "",
    val subject: String = "",
    val app: String = "",
    @SerialName("app_name") val appName: String = "",
    val group: Boolean = false,
)

object PlaceSources {
    const val TEAMS = "teams"
    const val MAIL = "mail"
    const val PHONE = "phone"
}

/** Une personne d'une organisation, parmi tes contacts. */
@Serializable
data class ContactMember(
    val id: Int = 0,
    val name: String = "",
    val title: String = "",
    val department: String = "",
    val last: Long = 0,
    val linked: Boolean = false,
    val talks: Boolean = false,
)

/** À qui écrire, si une de tes boîtes envoie : sa première adresse (pas une adresse générique). */
@Serializable
data class ContactWrite(val address: String = "", val name: String = "")

/** Peux-tu l'oublier d'ici, et sinon pourquoi (les mots du serveur). */
@Serializable
data class ContactForget(val allowed: Boolean = false, val reason: String = "")

/** `GET /contacts/fiche` : sa fiche. */
@Serializable
data class ContactSheet(
    val id: Int = 0,
    val kind: String = ContactKinds.PERSON,
    val name: String = "",
    val title: String = "",
    val department: String = "",
    val organisation: ContactRef? = null,
    val linked: Boolean = false,
    val talks: Boolean = false,
    val sources: List<ContactSource> = emptyList(),
    val first: Long = 0,
    val last: Long = 0,
    val identifiers: List<ContactIdentifier> = emptyList(),
    val facts: List<ContactFact> = emptyList(),
    val places: List<ContactPlace> = emptyList(),
    val members: List<ContactMember> = emptyList(),
    @SerialName("members_total") val membersTotal: Int = 0,
    val write: ContactWrite? = null,
    /** Sa conversation Teams (le tête-à-tête, sinon la plus récente), vide sinon. */
    val teams: String = "",
    /** Sa conversation de ton téléphone (`<appli>|<fil>`), vide sinon. */
    val message: String = "",
    /** `mine` : tout vient de tes comptes ; `shared` : aussi d'un compte qu'on te partage ou d'un compte à Mika. */
    val privacy: String = PRIVACY_SHARED,
    val forget: ContactForget = ContactForget(),
) {
    val org: Boolean get() = kind == ContactKinds.ORG

    companion object {
        const val PRIVACY_MINE = "mine"
        const val PRIVACY_SHARED = "shared"
    }
}

/** Ce qu'un oubli a donné (`{"ok", "message"}`, et pour un fait `deduped`, `id`). */
@Serializable
data class ContactsDone(val ok: Boolean = false, val message: String = "", val deduped: Boolean = false, val id: Int = 0)
