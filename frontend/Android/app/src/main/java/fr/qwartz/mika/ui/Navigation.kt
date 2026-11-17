package fr.qwartz.mika.ui

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.moi.carte.Place
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer

/**
 * Les écrans d'une session ouverte. La connexion n'en fait pas partie : c'est la session qui la montre.
 *
 * Les rubriques du tiroir (ADR 0235) sont [isTopLevel] : le chat, Mail, Teams, Carte, Téléphone, Outils, Paramètres.
 * Les autres s'ouvrent par-dessus l'écran qui les montre (un mail, un fil, un voyage, une page de réglages).
 */
@Serializable
sealed interface Route {
    @Serializable @SerialName("chat")
    data object Chat : Route

    /** « Ce qu'elle fait » : son visage l'ouvre, sur chaque écran. */
    @Serializable @SerialName("mind")
    data object Mind : Route

    /** Paramètres : ton compte et ses accès, puis ce téléphone. */
    @Serializable @SerialName("settings")
    data object Settings : Route

    /** Une page de Paramètres ([page] : `compte`, `boites`, `notifications`…), et ce qu'elle règle ([key]). */
    @Serializable @SerialName("settings_page")
    data class SettingsPage(val page: String, val key: String = "") : Route

    /** Une image de Mika en plein écran : de quoi la recharger et l'enregistrer. */
    @Serializable @SerialName("viewer")
    data class Viewer(
        val fileId: String,
        val name: String,
        val url: String,
        val mime: String? = null,
        val size: Long? = null,
    ) : Route

    // ── Mail ────────────────────────────────────────────────────────────
    @Serializable @SerialName("mail")
    data object Mail : Route

    /** Un mail, par sa référence (`boîte:Message-ID`). */
    @Serializable @SerialName("mail_message")
    data class MailMessage(val ref: String) : Route

    /** Ses brouillons, toutes boîtes. */
    @Serializable @SerialName("mail_drafts")
    data object MailDrafts : Route

    /** Un de ses brouillons : exactement ce qui partira. */
    @Serializable @SerialName("mail_draft")
    data class MailDraft(val id: String) : Route

    /** Écrire : [mode] `new`, `reply`, `reply_all`, `forward` ou `edit` (retoucher son brouillon [draft]). */
    @Serializable @SerialName("mail_compose")
    data class MailCompose(val mode: String = "new", val ref: String = "", val draft: String = "") : Route

    // ── Teams ───────────────────────────────────────────────────────────
    @Serializable @SerialName("teams")
    data object Teams : Route

    /** Une conversation, par sa clé (`<compte>~<identifiant>`). */
    @Serializable @SerialName("teams_thread")
    data class TeamsThread(val key: String) : Route

    /** Ses réponses dans tes comptes Teams. */
    @Serializable @SerialName("teams_replies")
    data object TeamsReplies : Route

    // ── Carte ───────────────────────────────────────────────────────────
    /**
     * [tab] : `explorer`, `itineraire`, `voyages` ; [look] : ce qu'elle a cherché ou montré (`regards/<seq>`) ; [to] :
     * l'arrivée qu'« Itinéraire jusqu'ici » demande à Itinéraire (un lieu d'Explorer), que l'onglet prend une fois.
     */
    @Serializable @SerialName("carte")
    data class Carte(val tab: String = "explorer", val look: String = "", val to: Place? = null) : Route

    @Serializable @SerialName("trip")
    data class Trip(val id: String) : Route

    // ── Téléphone ───────────────────────────────────────────────────────
    /** [tab] : `messages` ou `position`. */
    @Serializable @SerialName("phone")
    data class Phone(val tab: String = "messages") : Route

    /** Une conversation lue sur le téléphone (`<appli>|<fil>`). */
    @Serializable @SerialName("phone_thread")
    data class PhoneThread(val key: String) : Route

    // ── Outils, recherche, fichiers ─────────────────────────────────────
    /** [tab] : `droits`, `services`, `accords`. */
    @Serializable @SerialName("tools")
    data class Tools(val tab: String = "droits") : Route

    /** Rechercher : [scope] `all`, ou `chat` (depuis la loupe du chat : la conversation d'abord). */
    @Serializable @SerialName("search")
    data class Search(val scope: String = "all") : Route

    @Serializable @SerialName("files")
    data object Files : Route
}

/** Une rubrique du tiroir : on y arrive depuis le chat, et « retour » y ramène. */
val Route.isTopLevel: Boolean
    get() = this == Route.Chat || this == Route.Mail || this == Route.Teams || this is Route.Carte ||
        this is Route.Phone || this is Route.Tools || this == Route.Settings

/**
 * La pile d'écrans — une petite pile plutôt que navigation-compose. Immuable : chaque geste rend une nouvelle pile, que
 * Compose observe et que `rememberSaveable` garde (en JSON) au-delà d'une rotation ou d'une mort du processus.
 *
 * Règles : la conversation est toujours au fond ; une rubrique du tiroir s'ouvre juste au-dessus d'elle ([open]) ;
 * revenir à un écran déjà ouvert dépile jusqu'à lui (jamais deux fois le même écran) ; une image remplace l'image
 * ouverte ; changer d'onglet dans une rubrique ([replaceTop]) ne s'empile pas.
 */
data class BackStack(val routes: List<Route> = listOf(Route.Chat)) {
    init {
        require(routes.firstOrNull() == Route.Chat) { "la conversation est toujours au fond de la pile" }
    }

    val top: Route get() = routes.last()
    val canPop: Boolean get() = routes.size > 1

    /** La rubrique ouverte : la dernière rubrique du tiroir de la pile (le chat au pire). */
    val section: Route get() = routes.last { it.isTopLevel }

    /**
     * La conversation est au sommet : ses bulles sont à l'écran (et s'y marquent lues). « Ce qu'elle fait », une image,
     * la recherche ou les fichiers ouverts par-dessus ne la montrent pas : une réponse qui arrive là se notifie.
     */
    val showsChat: Boolean get() = top == Route.Chat

    fun push(route: Route): BackStack {
        if (route == top) return this
        if (route == Route.Chat) return BackStack()
        val existing = if (route is Route.Viewer) {
            routes.indexOfLast { it is Route.Viewer }
        } else {
            routes.indexOf(route)
        }
        if (existing > 0) return BackStack(routes.subList(0, existing) + route)
        return BackStack(routes + route)
    }

    /** Une rubrique du tiroir : seule au-dessus du chat ; un autre écran s'empile ([push]). */
    fun open(route: Route): BackStack = when {
        route == Route.Chat -> BackStack()
        route.isTopLevel -> BackStack(listOf(Route.Chat, route))
        else -> push(route)
    }

    /** Le même écran sous une autre forme (un autre onglet) : il remplace le sommet sans s'empiler. */
    fun replaceTop(route: Route): BackStack =
        if (!canPop || route == Route.Chat) open(route) else BackStack(routes.dropLast(1) + route)

    /** Un cran en arrière ; `null` à la racine (le geste « retour » sort alors de l'app). */
    fun pop(): BackStack? = if (canPop) BackStack(routes.dropLast(1)) else null

    fun encode(): String = MikaJson.encodeToString(ROUTES, routes)

    companion object {
        private val ROUTES = ListSerializer(Route.serializer())

        /** Relire une pile gardée ; illisible ou incohérente → la conversation seule. */
        fun decode(raw: String?): BackStack {
            if (raw.isNullOrBlank()) return BackStack()
            return try {
                val routes = MikaJson.decodeFromString(ROUTES, raw)
                if (routes.firstOrNull() == Route.Chat) BackStack(routes) else BackStack()
            } catch (_: IllegalArgumentException) {
                BackStack()
            }
        }

        /** Ce qu'ouvre une notification : la conversation, ou un écran par-dessus. */
        fun forDeepLink(target: String?): BackStack = when (target) {
            DeepLinks.SETTINGS -> BackStack(listOf(Route.Chat, Route.Settings))
            DeepLinks.MIND -> BackStack(listOf(Route.Chat, Route.Mind))
            DeepLinks.MAIL_DRAFTS -> BackStack(listOf(Route.Chat, Route.Mail, Route.MailDrafts))
            DeepLinks.TEAMS_REPLIES -> BackStack(listOf(Route.Chat, Route.Teams, Route.TeamsReplies))
            DeepLinks.PHONE -> BackStack(listOf(Route.Chat, Route.Phone()))
            else -> BackStack()
        }
    }
}

/** Les cibles qu'une notification ou un raccourci passe à `MainActivity`. */
object DeepLinks {
    const val EXTRA_OPEN = "fr.qwartz.mika.OPEN"
    const val CHAT = "chat"
    const val SETTINGS = "settings"
    const val MIND = "mind"
    const val MAIL_DRAFTS = "mail_drafts"
    const val TEAMS_REPLIES = "teams_replies"
    const val PHONE = "phone"
}
