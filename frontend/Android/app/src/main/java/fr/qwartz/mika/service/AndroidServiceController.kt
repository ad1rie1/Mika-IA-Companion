package fr.qwartz.mika.service

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import fr.qwartz.mika.core.Logger

/**
 * Le vrai [ServiceController] : démarre [MikaConnectionService] le temps d'une réponse partie d'une notification
 * (un geste sur une notification permet de démarrer un service au premier plan depuis l'arrière-plan), et l'arrête.
 */
class AndroidServiceController(
    private val context: Context,
    private val logger: Logger = Logger.NONE,
) : ServiceController {

    override fun stop() {
        context.stopService(Intent(context, MikaConnectionService::class.java))
    }

    override fun startOneShot(): Boolean = try {
        ContextCompat.startForegroundService(
            context,
            Intent(context, MikaConnectionService::class.java).setAction(MikaConnectionService.ACTION_ONE_SHOT),
        )
        true
    } catch (e: IllegalStateException) {
        // ForegroundServiceStartNotAllowedException (Android 12+) : pas de démarrage depuis l'arrière-plan.
        logger.w(TAG, "service non démarré", e)
        false
    } catch (e: SecurityException) {
        logger.w(TAG, "service non démarré", e)
        false
    }

    /**
     * Une commande au service, pas un `stopService` : démarré par `startForegroundService`, il serait arrêté avant
     * son `startForeground` si l'accusé revient vite, et Android abattrait le processus. Un service déjà démarré
     * reçoit la commande même depuis l'arrière-plan. Sans attendre : l'ordre des commandes est celui des appels
     * ([ReplySender] les sérialise).
     */
    override fun endOneShot() {
        try {
            context.startService(Intent(context, MikaConnectionService::class.java).setAction(MikaConnectionService.ACTION_END_ONE_SHOT))
        } catch (e: IllegalStateException) {
            // Depuis l'arrière-plan : il s'est déjà arrêté de lui-même (60 s), il n'y a plus rien à arrêter.
            logger.d(TAG, "service d'un coup déjà arrêté")
        } catch (e: SecurityException) {
            logger.w(TAG, "fin du service d'un coup non transmise", e)
        }
    }

    private companion object {
        const val TAG = "ServiceCtl"
    }
}
