package fr.qwartz.mika.service

import android.Manifest
import android.app.Notification
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.PendingIntentCompat
import androidx.core.app.Person
import androidx.core.app.RemoteInput
import androidx.core.content.ContextCompat
import androidx.core.content.LocusIdCompat
import fr.qwartz.mika.MainActivity
import fr.qwartz.mika.R
import fr.qwartz.mika.core.Logger
import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.chat.ChatEvent
import fr.qwartz.mika.data.db.ChatStore
import fr.qwartz.mika.data.db.Kv
import fr.qwartz.mika.share.Shortcuts
import fr.qwartz.mika.ui.DeepLinks
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.builtins.ListSerializer

/**
 * Les notifications des messages de Mika. Les décisions sont dans [NotificationPolicy] (pur) ; ici on
 * lit l'état (premier plan, lu, notifié), on écrit le « dernier notifié », et on affiche une seule
 * notification de conversation (`MessagingStyle`, raccourci `mika`) avec « Répondre » et « Marquer
 * comme lu ». Ses lignes sont gardées en base : un processus tué ne vide pas la notification au
 * message suivant.
 */
class MessageNotifier(
    private val context: Context,
    private val store: ChatStore,
    private val foreground: StateFlow<Boolean>,
    /** Le curseur du fil : « lu » jusque-là. */
    private val cursor: () -> Long,
    private val clock: () -> Long,
    private val logger: Logger = Logger.NONE,
) {
    private val lock = Mutex()

    fun start(scope: CoroutineScope, events: Flow<ChatEvent>) {
        scope.launch {
            events.collect { event ->
                if (event !is ChatEvent.MikaSpoke) return@collect
                try {
                    onSpoke(event)
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    logger.e(TAG, "notification non décidée", e)
                }
            }
        }
    }

    suspend fun onSpoke(event: ChatEvent.MikaSpoke) = lock.withLock {
        // Une autre vie du serveur : la notification parlait d'un fil qui n'est plus.
        if (event.anotherLife) {
            writeLines(emptyList())
            cancel()
        }
        val lastRead = kvLong(Kv.LAST_READ_ID)
        val lastNotified = kvLong(Kv.LAST_NOTIFIED_ID)
        val ctx = NotificationPolicy.Context(foreground.value, lastRead, lastNotified, event.cursorBefore)
        // Les identifiants de nos bulles ne sont lus que s'il y a une corrélation à vérifier.
        val own = if (event.live && event.replyToClientMsgId != null) store.ownClientMsgIds() else emptySet()
        val plan = NotificationPolicy.plan(event, ctx) { it in own }
        if (plan.lastNotifiedId > lastNotified) store.kvPut(Kv.LAST_NOTIFIED_ID, plan.lastNotifiedId.toString())
        if (plan.notify.isEmpty()) return@withLock
        val lines = NotificationPolicy.merge(readLines(), plan.notify, lastRead)
        writeLines(lines)
        post(lines, alertOnce = plan.alertOnce, reply = null)
    }

    /** « Marquer comme lu » : tout ce qui est arrivé est lu, la notification part. */
    suspend fun markRead() = lock.withLock {
        markReadLocked()
        cancel()
    }

    /** La conversation s'ouvre : la notification n'a plus rien à dire. */
    suspend fun onChatOpened() = lock.withLock {
        if (readLines().isNotEmpty()) writeLines(emptyList())
        cancel()
    }

    /** Glissée hors de l'écran : ses lignes sont oubliées (le fil, lui, reste non lu). */
    suspend fun onDismissed() = lock.withLock { writeLines(emptyList()) }

    /**
     * Une réponse est partie depuis la notification : elle s'y ajoute (sans quoi Android garde un
     * indicateur d'envoi qui tourne), et ce qui précédait est lu — on vient d'y répondre.
     */
    suspend fun onReplied(text: String) = lock.withLock {
        val lines = readLines()
        markReadLocked()
        post(lines, alertOnce = true, reply = text)
    }

    /** Déconnexion : plus rien de cette conversation dans le volet. */
    fun wipe() {
        NotificationManagerCompat.from(context).cancel(NotificationChannels.ID_MESSAGES)
    }

    private suspend fun markReadLocked() {
        val c = cursor()
        if (c > kvLong(Kv.LAST_READ_ID)) store.kvPut(Kv.LAST_READ_ID, c.toString())
        writeLines(emptyList())
    }

    private fun cancel() = NotificationManagerCompat.from(context).cancel(NotificationChannels.ID_MESSAGES)

    private fun post(lines: List<NotificationPolicy.Line>, alertOnce: Boolean, reply: String?) {
        val visible = lines.takeLast(NotificationPolicy.MAX_LINES)
        val more = lines.size - visible.size
        val mika = Shortcuts.mika(context)
        val style = NotificationCompat.MessagingStyle(Shortcuts.me(context))
        for (line in visible) style.addMessage(line.text, line.ts, mika)
        if (reply != null) style.addMessage(reply, clock(), null as Person?)

        val builder = NotificationCompat.Builder(context, NotificationChannels.MESSAGES)
            .setSmallIcon(R.drawable.ic_stat_mika)
            .setStyle(style)
            .setShortcutId(Shortcuts.ID)
            .setLocusId(LocusIdCompat(Shortcuts.ID))
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setPublicVersion(publicVersion())
            .setContentIntent(openChat())
            .setDeleteIntent(broadcast(NotificationActionReceiver.ACTION_DISMISS, REQ_DISMISS, mutable = false))
            .setAutoCancel(true)
            .setOnlyAlertOnce(alertOnce)
            .setNumber(lines.size)
            .addAction(replyAction())
            .addAction(
                NotificationCompat.Action.Builder(
                    R.drawable.ic_done_all,
                    context.getString(R.string.action_mark_read),
                    broadcast(NotificationActionReceiver.ACTION_MARK_READ, REQ_MARK_READ, mutable = false),
                )
                    .setSemanticAction(NotificationCompat.Action.SEMANTIC_ACTION_MARK_AS_READ)
                    .setShowsUserInterface(false)
                    .build(),
            )
        if (more > 0) builder.setSubText(context.resources.getQuantityString(R.plurals.notification_more, more, more))
        show(context, NotificationChannels.ID_MESSAGES, builder.build())
    }

    private fun replyAction(): NotificationCompat.Action {
        val input = RemoteInput.Builder(NotificationActionReceiver.KEY_REPLY)
            .setLabel(context.getString(R.string.notification_reply_hint))
            .build()
        // Mutable : le système doit pouvoir y glisser le texte tapé (RemoteInput).
        return NotificationCompat.Action.Builder(
            R.drawable.ic_send,
            context.getString(R.string.action_reply),
            broadcast(NotificationActionReceiver.ACTION_REPLY, REQ_REPLY, mutable = true),
        )
            .addRemoteInput(input)
            .setAllowGeneratedReplies(true)
            .setSemanticAction(NotificationCompat.Action.SEMANTIC_ACTION_REPLY)
            .setShowsUserInterface(false)
            .build()
    }

    private fun publicVersion(): Notification = NotificationCompat.Builder(context, NotificationChannels.MESSAGES)
        .setSmallIcon(R.drawable.ic_stat_mika)
        .setContentTitle(context.getString(R.string.mika))
        .setContentText(context.getString(R.string.notification_public))
        .build()

    private fun openChat() = PendingIntentCompat.getActivity(
        context,
        REQ_OPEN,
        Intent(context, MainActivity::class.java)
            .putExtra(DeepLinks.EXTRA_OPEN, DeepLinks.CHAT)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP),
        android.app.PendingIntent.FLAG_UPDATE_CURRENT,
        false,
    )

    private fun broadcast(action: String, code: Int, mutable: Boolean) = PendingIntentCompat.getBroadcast(
        context,
        code,
        Intent(context, NotificationActionReceiver::class.java).setAction(action),
        android.app.PendingIntent.FLAG_UPDATE_CURRENT,
        mutable,
    )

    private suspend fun kvLong(key: String): Long = store.kvGet(key)?.toLongOrNull() ?: 0L

    private suspend fun readLines(): List<NotificationPolicy.Line> = try {
        store.kvGet(Kv.NOTIFIED_LINES)?.let { MikaJson.decodeFromString(LINES, it) }.orEmpty()
    } catch (_: IllegalArgumentException) {
        emptyList()
    }

    private suspend fun writeLines(lines: List<NotificationPolicy.Line>) {
        store.kvPut(Kv.NOTIFIED_LINES, if (lines.isEmpty()) null else MikaJson.encodeToString(LINES, lines))
    }

    companion object {
        private const val TAG = "Notifier"
        private const val REQ_OPEN = 10
        private const val REQ_DISMISS = 11
        private const val REQ_MARK_READ = 12
        private const val REQ_REPLY = 13
        private val LINES = ListSerializer(NotificationPolicy.Line.serializer())

        /**
         * Afficher, seulement si on en a le droit (Android 13 : la permission ; sinon les réglages de
         * l'app). Refusé, on ne dit rien : la conversation garde tout.
         */
        fun show(context: Context, id: Int, notification: Notification) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
                PackageManager.PERMISSION_GRANTED
            ) {
                return
            }
            try {
                NotificationManagerCompat.from(context).notify(id, notification)
            } catch (_: SecurityException) {
                // Permission retirée entre la vérification et l'envoi.
            }
        }
    }
}
