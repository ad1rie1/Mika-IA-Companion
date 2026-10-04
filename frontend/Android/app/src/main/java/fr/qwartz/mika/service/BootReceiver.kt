package fr.qwartz.mika.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import fr.qwartz.mika.graph
import kotlinx.coroutines.launch

/**
 * Au démarrage du téléphone (ou après une mise à jour de l'app), remettre le service d'aplomb.
 * [ServiceController.shouldRun] décide : au boot, il faut « Démarrer avec le téléphone » ; après une
 * mise à jour, l'arrière-plan suffit (il tournait avant). La décision attend la session restaurée.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val reason = when (intent.action) {
            Intent.ACTION_BOOT_COMPLETED -> ServiceController.Reason.BOOT
            Intent.ACTION_MY_PACKAGE_REPLACED -> ServiceController.Reason.UPDATE
            else -> return
        }
        val graph = context.graph
        val pending = goAsync()
        graph.scope.launch {
            try {
                graph.serviceController.syncNow(reason)
            } finally {
                pending.finish()
            }
        }
    }
}
