package fr.qwartz.mika.service

import android.app.Notification
import android.content.ComponentName
import android.content.Context
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.Person
import fr.qwartz.mika.data.phone.ActionShape
import fr.qwartz.mika.data.phone.PhoneApp
import fr.qwartz.mika.data.phone.PhoneOutbox
import fr.qwartz.mika.data.phone.PhoneReading
import fr.qwartz.mika.data.phone.PostedMessage
import fr.qwartz.mika.data.phone.PostedNotification
import fr.qwartz.mika.data.phone.PostedPerson
import fr.qwartz.mika.data.phone.PostedStyle
import fr.qwartz.mika.graph
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

/**
 * Le lecteur des notifications du téléphone (« Lui montrer mes messages », ADR 0120) : celles de WhatsApp et de Messages,
 * seulement les applis cochées, lues dans leur `MessagingStyle`. Tout le reste est écarté au premier regard (le paquet),
 * avant le moindre travail. La logique est dans `data/phone` ([PhoneReading], la file) ; ici, la colle Android : décrire
 * la notification, garder son action « Répondre » (en mémoire seulement), passer la main au graphe.
 *
 * Android le branche tant que l'accès aux notifications est accordé. Réglage coupé, il demande à être débranché
 * ([requestUnbind]) : pas de réveil pour chaque notification du téléphone ; rallumé, le graphe le rebranche ([rebind]).
 * Rien n'est ouvert pour autant : l'envoi est un appel HTTP par lot (ADR 0077).
 */
class PhoneListenerService : NotificationListenerService() {
    private var watch: Job? = null

    override fun onListenerConnected() {
        val graph = applicationContext.graph
        watch?.cancel()
        watch = graph.scope.launch {
            graph.ready.await()
            graph.settings.settings.map { it.phoneShare }.distinctUntilChanged().collect { on ->
                if (on) {
                    // Ce que le volet montre déjà : les messages, et surtout les actions « Répondre » (perdues avec
                    // l'ancien processus). Puis l'envoi, sans attendre la fin d'une attente d'après un échec.
                    readActive()
                    graph.phone.flush(PhoneOutbox.Trigger.LISTENER)
                } else {
                    unbind()
                }
            }
        }
    }

    override fun onListenerDisconnected() {
        watch?.cancel()
        watch = null
    }

    override fun onDestroy() {
        watch?.cancel()
        watch = null
        super.onDestroy()
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        if (sbn == null || sbn.packageName !in PhoneApp.PACKAGES) return
        val posted = PhoneNotifications.describe(sbn)
        val reply = PhoneNotifications.replyAction(sbn.notification)
        val graph = applicationContext.graph
        graph.scope.launch {
            graph.ready.await()
            graph.onPhoneNotification(posted, reply)
        }
    }

    private suspend fun readActive() {
        val graph = applicationContext.graph
        val active = try {
            activeNotifications
        } catch (e: SecurityException) {
            // Débranché entre-temps : la prochaine connexion relira.
            graph.logger.w(TAG, "notifications actives illisibles", e)
            null
        }
        for (sbn in active.orEmpty()) {
            if (sbn.packageName !in PhoneApp.PACKAGES) continue
            graph.onPhoneNotification(PhoneNotifications.describe(sbn), PhoneNotifications.replyAction(sbn.notification))
        }
    }

    private fun unbind() {
        try {
            requestUnbind()
        } catch (e: SecurityException) {
            // Déjà débranché : rien à faire.
            applicationContext.graph.logger.w(TAG, "débranchement refusé", e)
        }
    }

    companion object {
        private const val TAG = "PhoneListener"

        /** L'accès aux notifications est-il accordé à l'app (réglages d'Android › Accès aux notifications) ? */
        fun granted(context: Context): Boolean =
            NotificationManagerCompat.getEnabledListenerPackages(context).contains(context.packageName)

        /** Le réglage rallumé : qu'Android rebranche le lecteur qu'il avait débranché à notre demande. */
        fun rebind(context: Context) {
            if (!granted(context)) return
            try {
                NotificationListenerService.requestRebind(ComponentName(context, PhoneListenerService::class.java))
            } catch (_: SecurityException) {
                // Accès retiré entre-temps : les réglages le diront.
            }
        }
    }
}

/** Décrire une notification pour le tri ([PhoneReading]), et retrouver son action « Répondre ». */
internal object PhoneNotifications {
    fun describe(sbn: StatusBarNotification): PostedNotification {
        val n = sbn.notification
        val style = NotificationCompat.MessagingStyle.extractMessagingStyleFromNotification(n)
        return PostedNotification(
            packageName = sbn.packageName,
            groupSummary = n.flags and Notification.FLAG_GROUP_SUMMARY != 0,
            shortcutId = n.shortcutId,
            tag = sbn.tag,
            postTime = sbn.postTime,
            style = style?.let { s ->
                PostedStyle(
                    user = person(s.user),
                    conversationTitle = s.conversationTitle?.toString(),
                    group = s.isGroupConversation,
                    messages = s.messages.map { m -> PostedMessage(m.text?.toString().orEmpty(), m.timestamp, m.person?.let(::person)) },
                )
            },
        )
    }

    /** L'action à saisie libre de la notification, de préférence déclarée « Répondre » ; `null` s'il n'y en a pas. */
    fun replyAction(n: Notification): Notification.Action? {
        val actions = n.actions ?: return null
        val shapes = actions.map { a -> ActionShape(a.semanticAction, a.remoteInputs?.count { it.allowFreeFormInput } ?: 0) }
        return PhoneReading.pickReply(shapes)?.let { actions[it] }
    }

    private fun person(p: Person): PostedPerson = PostedPerson(p.key, p.uri, p.name?.toString())
}
