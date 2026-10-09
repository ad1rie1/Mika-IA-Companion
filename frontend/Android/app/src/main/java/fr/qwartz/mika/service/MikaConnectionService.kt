package fr.qwartz.mika.service

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.PendingIntentCompat
import fr.qwartz.mika.MainActivity
import fr.qwartz.mika.R
import fr.qwartz.mika.data.net.LinkState
import fr.qwartz.mika.graph
import fr.qwartz.mika.ui.DeepLinks
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

/**
 * Le service au premier plan qui garde le processus en vie le temps qu'une réponse partie d'une notification soit
 * accusée (« d'un coup », [ONE_SHOT_MS] au plus) : la réponse tient elle-même sa connexion
 * ([ConnectionManager.Holder.REPLY]), lui garde le processus. Type `remoteMessaging`.
 *
 * Il n'y a plus de connexion en arrière-plan (ADR 0077) : app fermée, rien n'est ouvert, les messages de Mika
 * arrivent par Firebase. Hors de portée du serveur, la réponse attend dans la file d'envoi la prochaine ouverture.
 */
class MikaConnectionService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var oneShotTimer: Job? = null
    private var foreground = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        // Immédiatement : Android laisse quelques secondes entre le démarrage et la notification.
        foreground = enterForeground()
        if (!foreground) {
            stopSelf()
            return
        }
        scope.launch {
            graph.connection.link
                .map(::textFor)
                .distinctUntilChanged()
                .collect { MessageNotifier.show(this@MikaConnectionService, NotificationChannels.ID_CONNECTION, build(it)) }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!foreground) {
            stopSelf(startId)
            return START_NOT_STICKY
        }
        when (intent?.action) {
            ACTION_ONE_SHOT -> armOneShot()
            // La réponse est accusée. Traité ici, donc après `onCreate` et son `startForeground` : un
            // `stopService` venu de dehors pouvait les devancer, et Android abat alors le processus.
            // `startId` : un « d'un coup » demandé entre-temps garde le service.
            ACTION_END_ONE_SHOT -> stopSelf(startId)
            // Une relance par le système, ou une commande d'une version d'avant : rien à tenir.
            else -> stopSelf(startId)
        }
        // Tué, il ne revient pas : la réponse attend la prochaine ouverture dans la file d'envoi.
        return START_NOT_STICKY
    }

    /** Le service s'arrête de lui-même au bout de [ONE_SHOT_MS], accusé ou pas. */
    private fun armOneShot() {
        oneShotTimer?.cancel()
        oneShotTimer = scope.launch {
            delay(ONE_SHOT_MS)
            stopSelf()
        }
    }

    /** API 35 : un type de service a dépassé sa durée permise (pas le cas de `remoteMessaging`, par prudence). */
    override fun onTimeout(startId: Int, fgsType: Int) {
        stopSelf()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun enterForeground(): Boolean {
        val notification = build(textFor(graph.connection.link.value))
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                startForeground(
                    NotificationChannels.ID_CONNECTION,
                    notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING,
                )
            } else {
                // Avant Android 14, le type déclaré au manifeste suffit.
                startForeground(NotificationChannels.ID_CONNECTION, notification)
            }
            true
        } catch (e: IllegalStateException) {
            // ForegroundServiceStartNotAllowedException (Android 12+) : démarré quand ce n'était pas permis.
            graph.logger.w(TAG, "service au premier plan refusé", e)
            false
        } catch (e: SecurityException) {
            graph.logger.w(TAG, "service au premier plan refusé", e)
            false
        }
    }

    private fun textFor(link: LinkState): Int = when (link) {
        LinkState.Online -> R.string.connection_online
        LinkState.Connecting, is LinkState.Offline -> R.string.connection_reconnecting
        else -> R.string.connection_offline
    }

    private fun build(text: Int): Notification {
        val open = PendingIntentCompat.getActivity(
            this,
            REQ_OPEN,
            Intent(this, MainActivity::class.java)
                .putExtra(DeepLinks.EXTRA_OPEN, DeepLinks.CHAT)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT,
            false,
        )
        return NotificationCompat.Builder(this, NotificationChannels.CONNECTION)
            .setSmallIcon(R.drawable.ic_stat_mika)
            .setContentTitle(getString(R.string.reply_sending))
            .setContentText(getString(text))
            .setOngoing(true)
            .setSilent(true)
            .setShowWhen(false)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setContentIntent(open)
            .build()
    }

    companion object {
        private const val TAG = "Service"
        const val ACTION_ONE_SHOT = "fr.qwartz.mika.service.ONE_SHOT"
        const val ACTION_END_ONE_SHOT = "fr.qwartz.mika.service.END_ONE_SHOT"
        private const val REQ_OPEN = 20
        private const val ONE_SHOT_MS = 60_000L
    }
}
