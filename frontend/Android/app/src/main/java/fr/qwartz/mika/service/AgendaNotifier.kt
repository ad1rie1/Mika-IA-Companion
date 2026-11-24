package fr.qwartz.mika.service

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.app.NotificationCompat
import androidx.core.app.PendingIntentCompat
import fr.qwartz.mika.MainActivity
import fr.qwartz.mika.R
import fr.qwartz.mika.core.Clock
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.agenda.AgendaApi
import fr.qwartz.mika.data.moi.agenda.AgendaNote
import fr.qwartz.mika.data.moi.agenda.AgendaPrefs
import fr.qwartz.mika.data.moi.agenda.agendaNotes
import fr.qwartz.mika.data.moi.agenda.localOf
import fr.qwartz.mika.ui.DeepLinks
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Le canal « Agenda » (ADR 0309, recommandation 11 de la conception : un seul canal, pas de « Rappels » à part — le
 * rappel d'un rendez-vous est un message de Mika, déjà notifié) : une invitation qui attend ta réponse, un ajout que
 * Mika propose dont tu décides. L'app ne se connecte qu'ouverte (ADR 0077) et le serveur n'envoie rien de l'agenda par
 * Firebase : elle notifie ce qui arrive pendant qu'elle est ouverte ailleurs que dans l'Agenda — dans l'Agenda, la vue
 * se relit en direct et rien ne se notifie. Chaque chose une fois (`AgendaPrefs.notified`) ; la première lecture d'une
 * session ne notifie rien de ce qui attendait déjà ; ce qui n'attend plus (répondu, décidé) retire sa notification.
 * La toucher ouvre la fiche, où l'on décide : le volet n'a pas de bouton qui accepte (comme les cartes d'accord du chat).
 */
class AgendaNotifier(
    private val context: Context,
    private val api: () -> AgendaApi,
    private val prefs: AgendaPrefs,
    private val clock: Clock,
) {
    private val lock = Mutex()

    /** Un écran de l'Agenda est au sommet : ce qui arrive se voit, rien ne se notifie. */
    @Volatile var shown: Boolean = false

    /** Relire ce qui attend, et notifier ce qui est neuf. */
    suspend fun check() = lock.withLock {
        val a = api()
        val inv = (a.invitations() as? MoiApi.Result.Ok)?.value ?: return@withLock
        val props = (a.proposals() as? MoiApi.Result.Ok)?.value ?: return@withLock
        val cals = (a.calendars() as? MoiApi.Result.Ok)?.value ?: return@withLock
        val today = localOf(clock.wallMs(), cals.zone).day
        val notes = agendaNotes(inv.items, props.items, cals.calendars, cals.zone, today)
        val seen = prefs.notified()
        val keys = notes.map { it.key }.toSet()
        for (gone in seen - keys - FIRST) cancel(gone)
        if (FIRST in seen && !shown) {
            for (n in notes) if (n.key !in seen) post(n)
        }
        prefs.setNotified(keys + FIRST)
    }

    private fun post(n: AgendaNote) {
        val open = PendingIntentCompat.getActivity(
            context,
            idOf(n.key),
            Intent(context, MainActivity::class.java)
                .setData(Uri.fromParts(URI_SCHEME, n.key, null))
                .putExtra(DeepLinks.EXTRA_OPEN, n.target.encode())
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT,
            false,
        )
        val notification = NotificationCompat.Builder(context, NotificationChannels.AGENDA)
            .setSmallIcon(R.drawable.ic_stat_mika)
            .setContentTitle(n.title)
            .setContentText(n.text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(n.text).setBigContentTitle(n.title))
            .setCategory(NotificationCompat.CATEGORY_EVENT)
            // Écran verrouillé : que quelque chose attend dans l'Agenda, jamais quoi ni de qui.
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setPublicVersion(
                NotificationCompat.Builder(context, NotificationChannels.AGENDA)
                    .setSmallIcon(R.drawable.ic_stat_mika)
                    .setContentTitle(context.getString(R.string.mika))
                    .setContentText(context.getString(R.string.agenda_notify_public))
                    .build(),
            )
            .setAutoCancel(true)
            .setContentIntent(open)
            .build()
        MessageNotifier.show(context, idOf(n.key), notification, TAG)
    }

    private fun cancel(key: String) {
        context.getSystemService(NotificationManager::class.java)?.cancel(TAG, idOf(key))
    }

    /** À la déconnexion : ses notifications partent, et ce qu'il avait notifié. */
    fun wipe() {
        val manager = context.getSystemService(NotificationManager::class.java)
        if (manager != null) for (s in manager.activeNotifications) if (s.tag == TAG) manager.cancel(s.tag, s.id)
        prefs.wipe()
    }

    private companion object {
        const val TAG = "agenda"
        const val URI_SCHEME = "mika-agenda"
        /** Marque une session déjà lue une fois : ce qui attendait avant ne se notifie pas. */
        const val FIRST = "*"

        fun idOf(key: String): Int = key.hashCode()
    }
}
