package fr.qwartz.mika.service

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import fr.qwartz.mika.core.Logger
import fr.qwartz.mika.data.auth.Session
import fr.qwartz.mika.data.settings.SettingsStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Le vrai [ServiceController] : démarre ou arrête [MikaConnectionService] d'après la session et les
 * réglages ([ServiceController.shouldRun]).
 *
 * Android ne laisse démarrer un service au premier plan que depuis l'app visible, un démarrage du
 * téléphone, une mise à jour ou un geste sur une notification ; c'est donc [watch] qui le démarre
 * quand l'app est à l'écran (connexion, réglage changé), et [syncNow] qui le fait au boot. Arrêter,
 * en revanche, est toujours permis.
 */
class AndroidServiceController(
    private val context: Context,
    private val scope: CoroutineScope,
    private val settings: SettingsStore,
    private val session: StateFlow<Session>,
    private val logger: Logger = Logger.NONE,
) : ServiceController {

    /** Suivre la session, le réglage et la visibilité de l'app ; à appeler une fois. */
    fun watch(visible: StateFlow<Boolean>) {
        scope.launch {
            combine(session, settings.settings, visible) { s, st, v -> Triple(s is Session.LoggedIn, st.background, v) }
                .distinctUntilChanged()
                .collect { (loggedIn, background, isVisible) ->
                    if (session.value is Session.Loading) return@collect
                    val run = ServiceController.shouldRun(loggedIn, background, startOnBoot = false, ServiceController.Reason.APP)
                    if (!run) {
                        stop()
                    } else if (isVisible) {
                        withContext(Dispatchers.Main) { start(MikaConnectionService.ACTION_START) }
                    }
                }
        }
    }

    override fun sync(reason: ServiceController.Reason) {
        scope.launch { syncNow(reason) }
    }

    override suspend fun syncNow(reason: ServiceController.Reason) {
        val s = session.first { it !is Session.Loading }
        val st = settings.current()
        if (ServiceController.shouldRun(s is Session.LoggedIn, st.background, st.startOnBoot, reason)) {
            withContext(Dispatchers.Main) { start(MikaConnectionService.ACTION_START) }
        } else if (reason == ServiceController.Reason.APP) {
            stop()
        }
    }

    override fun stop() {
        context.stopService(Intent(context, MikaConnectionService::class.java))
    }

    override fun startOneShot(): Boolean = start(MikaConnectionService.ACTION_ONE_SHOT)

    override fun endOneShot() {
        scope.launch {
            // L'arrière-plan a pu être activé entre-temps : ce service-là reste.
            if (!settings.current().background) stop()
        }
    }

    private fun start(action: String): Boolean = try {
        ContextCompat.startForegroundService(context, Intent(context, MikaConnectionService::class.java).setAction(action))
        true
    } catch (e: IllegalStateException) {
        // ForegroundServiceStartNotAllowedException (Android 12+) : pas de démarrage depuis l'arrière-plan.
        logger.w(TAG, "service non démarré", e)
        false
    } catch (e: SecurityException) {
        logger.w(TAG, "service non démarré", e)
        false
    }

    private companion object {
        const val TAG = "ServiceCtl"
    }
}
