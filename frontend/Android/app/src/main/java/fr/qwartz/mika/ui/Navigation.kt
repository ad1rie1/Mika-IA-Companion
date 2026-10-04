package fr.qwartz.mika.ui

import fr.qwartz.mika.core.MikaJson
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer

/** Les écrans d'une session ouverte. La connexion n'en fait pas partie : c'est la session qui la montre. */
@Serializable
sealed interface Route {
    @Serializable @SerialName("chat")
    data object Chat : Route

    @Serializable @SerialName("mind")
    data object Mind : Route

    @Serializable @SerialName("settings")
    data object Settings : Route

    /** Une image de Mika en plein écran : de quoi la recharger et l'enregistrer. */
    @Serializable @SerialName("viewer")
    data class Viewer(
        val fileId: String,
        val name: String,
        val url: String,
        val mime: String? = null,
        val size: Long? = null,
    ) : Route
}

/**
 * La pile d'écrans — une petite pile plutôt que navigation-compose : quatre écrans, une seule
 * conversation. Immuable : chaque geste rend une nouvelle pile, que Compose observe et que
 * `rememberSaveable` garde (en JSON) au-delà d'une rotation ou d'une mort du processus.
 *
 * Règles : la conversation est toujours au fond ; revenir à un écran déjà ouvert dépile jusqu'à lui
 * (jamais deux fois le même écran) ; une image remplace l'image ouverte.
 */
data class BackStack(val routes: List<Route> = listOf(Route.Chat)) {
    init {
        require(routes.firstOrNull() == Route.Chat) { "la conversation est toujours au fond de la pile" }
    }

    val top: Route get() = routes.last()
    val canPop: Boolean get() = routes.size > 1

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

        /** Ce qu'ouvre une notification : la conversation, ou les paramètres par-dessus. */
        fun forDeepLink(target: String?): BackStack = when (target) {
            DeepLinks.SETTINGS -> BackStack(listOf(Route.Chat, Route.Settings))
            DeepLinks.MIND -> BackStack(listOf(Route.Chat, Route.Mind))
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
}
