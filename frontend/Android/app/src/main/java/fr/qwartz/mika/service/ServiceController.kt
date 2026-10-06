package fr.qwartz.mika.service

/**
 * Démarrer ou arrêter le service au premier plan (`MikaConnectionService`, type `remoteMessaging`)
 * selon la session et le réglage « Rester connectée en arrière-plan ». Appelé à l'ouverture de l'app
 * et d'une session, au changement du réglage, au démarrage du téléphone et après une mise à jour.
 * Toutes les méthodes peuvent être appelées depuis n'importe quel fil.
 */
interface ServiceController {
    /** Pourquoi on accorde le service : au démarrage du téléphone, « Démarrer avec le téléphone » décide aussi. */
    enum class Reason { APP, BOOT, UPDATE }

    /** Accorder le service à l'état présent, sans attendre. */
    fun sync(reason: Reason = Reason.APP)

    /** La même chose, en attendant la décision (un récepteur de diffusion qui doit finir proprement). */
    suspend fun syncNow(reason: Reason = Reason.APP) = sync(reason)

    /** La session se ferme : arrêter le service et sa notification. */
    fun stop()

    /**
     * Une réponse part d'une notification alors que l'arrière-plan est coupé : un service le temps de
     * son accusé (60 s au plus), pour que le processus vive jusque-là. `false` s'il n'a pas pu démarrer.
     */
    fun startOneShot(): Boolean = false

    /**
     * La réponse est accusée : le service d'un coup s'arrête (pas celui de l'arrière-plan). Il
     * s'arrête lui-même, sur commande : jamais avant son `startForeground`.
     */
    fun endOneShot() {}

    companion object {
        /**
         * Le service tourne-t-il ? Une session et l'arrière-plan voulu ; au démarrage du téléphone, il
         * faut en plus « Démarrer avec le téléphone ». Après une mise à jour de l'app, il reprend s'il
         * tournait (l'arrière-plan suffit).
         */
        fun shouldRun(loggedIn: Boolean, background: Boolean, startOnBoot: Boolean, reason: Reason): Boolean =
            loggedIn && background && (reason != Reason.BOOT || startOnBoot)

        /** Sans service : la connexion ne vit que tant que l'écran (ou une réponse) la demande. */
        val ScreenOnly: ServiceController = object : ServiceController {
            override fun sync(reason: Reason) = Unit
            override fun stop() = Unit
        }
    }
}
