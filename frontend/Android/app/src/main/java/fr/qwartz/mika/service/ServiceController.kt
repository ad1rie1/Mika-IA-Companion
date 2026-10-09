package fr.qwartz.mika.service

/**
 * Le service au premier plan (`MikaConnectionService`, type `remoteMessaging`) ne vit plus que le temps d'envoyer
 * une réponse partie d'une notification : l'app ne garde aucune connexion quand elle est fermée, ses messages
 * arrivent par Firebase (ADR 0077). Toutes les méthodes peuvent être appelées depuis n'importe quel fil.
 */
interface ServiceController {
    /** La session se ferme : arrêter le service et sa notification. */
    fun stop()

    /**
     * Une réponse part d'une notification, app fermée : un service le temps de son accusé (60 s au plus), pour que
     * le processus vive jusque-là. `false` s'il n'a pas pu démarrer.
     */
    fun startOneShot(): Boolean = false

    /** La dernière réponse en vol est accusée : le service s'arrête lui-même, sur commande — jamais avant son `startForeground`. */
    fun endOneShot() {}

    companion object {
        /** Sans service : la connexion ne vit que tant que l'écran (ou une réponse) la demande. */
        val ScreenOnly: ServiceController = object : ServiceController {
            override fun stop() = Unit
        }
    }
}
