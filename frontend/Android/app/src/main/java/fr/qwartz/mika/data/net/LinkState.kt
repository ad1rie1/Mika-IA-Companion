package fr.qwartz.mika.data.net

/** L'état du lien avec le serveur, tel que l'écran et la notification de service le disent. */
sealed interface LinkState {
    /** Personne ne demande la connexion (app en arrière-plan sans service, ou pas de session). */
    data object Idle : LinkState
    data object Connecting : LinkState
    data object Online : LinkState
    /** Coupée ; prochain essai à cet instant (horloge `elapsedMs`). */
    data class Offline(val retryAtElapsedMs: Long) : LinkState
    /** Pas de réseau : aucun essai n'est dépensé avant son retour. */
    data object NoNetwork : LinkState
    /** 4401 ou poignée de main en 401 : la session doit changer avant qu'un essai diffère. */
    data object SessionExpired : LinkState
    /** 1008 ou poignée de main en 403 : le serveur refuse la connexion. */
    data class Refused(val code: Int) : LinkState
}
