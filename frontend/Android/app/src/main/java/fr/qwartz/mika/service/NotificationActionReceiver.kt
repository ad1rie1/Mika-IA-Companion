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
 * Les actions des notifications de l'app. Celle de Mika : « Répondre » (RemoteInput), « Marquer comme lu », et la
 * notification balayée. Celles de ses réponses proposées pour WhatsApp ou Messages (ADR 0120) : « Envoyer », « Écrire
 * autre chose » (RemoteInput), « Ignorer », et la notification balayée — le geste de la personne vaut accord. Le travail
 * se fait hors du fil principal (`goAsync`), une fois l'app prête : le processus vient peut-être d'être créé pour ce
 * seul geste.
 */
class NotificationActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action ?: return
        if (action !in ACTIONS) return
        val typed = when (action) {
            ACTION_REPLY -> RemoteInput.getResultsFromIntent(intent)?.getCharSequence(KEY_REPLY)?.toString()?.trim()
            // Une saisie vide reste une saisie (la notification se repose) : seul « Envoyer » n'en a pas.
            ACTION_PHONE_OTHER ->
                RemoteInput.getResultsFromIntent(intent)?.getCharSequence(KEY_PHONE_REPLY)?.toString()?.trim().orEmpty()
            else -> null
        }
        val draftId = intent.getLongExtra(EXTRA_DRAFT_ID, 0L)
        val graph = context.graph
        val pending = goAsync()
        graph.scope.launch {
            try {
                graph.ready.await()
                // Une notification restée d'une session close ne parle plus à personne.
                if (graph.auth.session.value !is Session.LoggedIn) {
                    if (action in PHONE_ACTIONS) graph.phoneDrafts.wipe() else graph.notifier.wipe()
                    return@launch
                }
                when (action) {
                    ACTION_REPLY -> if (!typed.isNullOrEmpty()) graph.replies.reply(typed)
                    ACTION_MARK_READ -> graph.notifier.markRead()
                    ACTION_DISMISS -> graph.notifier.onDismissed()
                    ACTION_PHONE_SEND -> graph.phoneDrafts.send(draftId, typed = null)
                    ACTION_PHONE_OTHER -> graph.phoneDrafts.send(draftId, typed = typed.orEmpty())
                    ACTION_PHONE_IGNORE -> graph.phoneDrafts.ignore(draftId)
                    ACTION_PHONE_DISMISS -> graph.phoneDrafts.dismissed(draftId)
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

        /** Les gestes sur une réponse proposée (ADR 0120) ; l'identifiant de la proposition est dans [EXTRA_DRAFT_ID]. */
        const val ACTION_PHONE_SEND = "fr.qwartz.mika.action.PHONE_SEND"
        const val ACTION_PHONE_OTHER = "fr.qwartz.mika.action.PHONE_OTHER"
        const val ACTION_PHONE_IGNORE = "fr.qwartz.mika.action.PHONE_IGNORE"
        const val ACTION_PHONE_DISMISS = "fr.qwartz.mika.action.PHONE_DISMISS"
        const val EXTRA_DRAFT_ID = "fr.qwartz.mika.extra.DRAFT_ID"
        const val KEY_PHONE_REPLY = "phone_reply"

        private val PHONE_ACTIONS = setOf(ACTION_PHONE_SEND, ACTION_PHONE_OTHER, ACTION_PHONE_IGNORE, ACTION_PHONE_DISMISS)
        private val ACTIONS = setOf(ACTION_REPLY, ACTION_MARK_READ, ACTION_DISMISS) + PHONE_ACTIONS
    }
}
