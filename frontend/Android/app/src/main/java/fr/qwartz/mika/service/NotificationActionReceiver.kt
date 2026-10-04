package fr.qwartz.mika.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.RemoteInput
import fr.qwartz.mika.data.auth.Session
import fr.qwartz.mika.graph
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

/**
 * Les actions de la notification de Mika : « Répondre » (RemoteInput), « Marquer comme lu », et la
 * notification balayée. Le travail se fait hors du fil principal (`goAsync`), une fois l'app prête :
 * le processus vient peut-être d'être créé pour ce seul geste.
 */
class NotificationActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action ?: return
        if (action !in ACTIONS) return
        val reply = if (action == ACTION_REPLY) {
            RemoteInput.getResultsFromIntent(intent)?.getCharSequence(KEY_REPLY)?.toString()?.trim()
        } else {
            null
        }
        val graph = context.graph
        val pending = goAsync()
        graph.scope.launch {
            try {
                graph.ready.await()
                // Une notification restée d'une session close ne parle plus à personne.
                if (graph.auth.session.value !is Session.LoggedIn) {
                    graph.notifier.wipe()
                    return@launch
                }
                when (action) {
                    ACTION_REPLY -> if (!reply.isNullOrEmpty()) graph.replies.reply(reply)
                    ACTION_MARK_READ -> graph.notifier.markRead()
                    ACTION_DISMISS -> graph.notifier.onDismissed()
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                graph.logger.e(TAG, "action de notification en échec", e)
            } finally {
                pending.finish()
            }
        }
    }

    companion object {
        private const val TAG = "NotifAction"
        const val ACTION_REPLY = "fr.qwartz.mika.action.REPLY"
        const val ACTION_MARK_READ = "fr.qwartz.mika.action.MARK_READ"
        const val ACTION_DISMISS = "fr.qwartz.mika.action.DISMISS"
        const val KEY_REPLY = "reply"
        private val ACTIONS = setOf(ACTION_REPLY, ACTION_MARK_READ, ACTION_DISMISS)
    }
}
