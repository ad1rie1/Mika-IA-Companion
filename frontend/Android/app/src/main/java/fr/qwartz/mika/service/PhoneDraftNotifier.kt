package fr.qwartz.mika.service

import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.core.app.NotificationCompat
import androidx.core.app.PendingIntentCompat
import androidx.core.app.RemoteInput
import fr.qwartz.mika.MainActivity
import fr.qwartz.mika.R
import fr.qwartz.mika.core.Logger
import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.db.Kv
import fr.qwartz.mika.data.phone.PhoneApp
import fr.qwartz.mika.data.phone.PhoneDraft
import fr.qwartz.mika.data.phone.PhoneDraftBook
import fr.qwartz.mika.data.phone.PhoneDrafts
import fr.qwartz.mika.data.phone.PhoneKv
import fr.qwartz.mika.data.phone.PhoneOutbox
import fr.qwartz.mika.data.phone.ReplyRegistry
import fr.qwartz.mika.data.phone.SettleReason
import fr.qwartz.mika.data.phone.Settlement
import fr.qwartz.mika.ui.DeepLinks
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Les réponses que Mika propose pour WhatsApp ou Messages (ADR 0120) : c'est ici que la personne autorise. Une
 * notification par proposition — « Répondre à Léa (WhatsApp) ? », le texte entier — avec « Envoyer », « Écrire autre
 * chose » et « Ignorer » : **le geste vaut accord**, et il se fait aussi en 4G (le texte est dans la notification).
 *
 * « Envoyer » passe par l'action « Répondre » de la notification de l'appli, gardée en mémoire par conversation
 * ([ReplyRegistry]) ; si elle n'existe plus, le texte est copié et une notification ouvre l'appli pour le coller. Le sort
 * repart au serveur par la file des messages ([PhoneOutbox.settle]). La proposition en attente est gardée sur disque le
 * temps de son échéance, pour que le geste marche après la mort du processus.
 */
class PhoneDraftNotifier(
    private val context: Context,
    private val kv: PhoneKv,
    private val replies: ReplyRegistry<Notification.Action>,
    private val outbox: PhoneOutbox,
    /** « Lui montrer mes messages » : coupé, aucune proposition ne se montre. */
    private val enabled: suspend () -> Boolean,
    private val clock: () -> Long,
    private val logger: Logger = Logger.NONE,
) {
    private val lock = Mutex()

    /** Une proposition arrivée par Firebase : montrée, sauf expirée, déjà vue, ou la lecture coupée. */
    suspend fun onDraft(draft: PhoneDraft) = lock.withLock {
        if (!enabled()) {
            logger.i(TAG, "proposition écartée : « Lui montrer mes messages » est coupé")
            return@withLock
        }
        val now = clock()
        when (val admission = PhoneDrafts.admit(load(), draft, now)) {
            is PhoneDrafts.Admission.Show -> {
                save(admission.book)
                post(draft, now, alert = true)
            }
            PhoneDrafts.Admission.Expired -> logger.i(TAG, "proposition déjà expirée à son arrivée : pas montrée")
            PhoneDrafts.Admission.Seen -> Unit
        }
    }

    /**
     * « Envoyer » ([typed] `null` : le texte proposé) ou « Écrire autre chose » ([typed] : ce que la personne a tapé), par
     * l'action « Répondre » de la conversation ; sans elle, ou refusée par l'appli, le texte est copié.
     */
    suspend fun send(id: Long, typed: String?) = lock.withLock {
        val now = clock()
        val book = load()
        val draft = PhoneDrafts.pending(book, id, now)
        if (draft == null) {
            // Expirée, déjà réglée (un double toucher), ou effacée : la notification n'a plus rien à proposer.
            cancel(id)
            save(PhoneDrafts.prune(book, now))
            return@withLock
        }
        if (typed != null && typed.isBlank()) {
            // Un champ validé vide : rien ne part, mais la notification se repose (sinon son indicateur tourne).
            post(draft, now, alert = false)
            return@withLock
        }
        val text = typed ?: draft.text
        val action = replies.get(draft.thread)
        val failure = when {
            action == null -> SettleReason.NO_ACTION
            deliver(action, text) -> null
            else -> SettleReason.SEND_ERROR
        }
        save(PhoneDrafts.settled(book, id))
        when {
            failure == null -> {
                cancel(id)
                outbox.settle(id, if (typed == null) Settlement.SENT else Settlement.OTHER)
            }
            copy(text) -> {
                postCopied(draft, text)
                outbox.settle(id, Settlement.COPIED, failure)
            }
            else -> {
                cancel(id)
                outbox.settle(id, Settlement.FAILED, failure)
            }
        }
        outbox.flushSoon()
    }

    /** « Ignorer » : rien ne part, et Mika le saura. */
    suspend fun ignore(id: Long) = lock.withLock {
        cancel(id)
        settleIgnored(id, clock())
    }

    /**
     * La notification balayée : un geste aussi, compté comme « Ignorer » tant que la proposition n'a pas expiré (une
     * notification qui disparaît à son échéance n'est pas un geste : le serveur l'expire lui-même).
     */
    suspend fun dismissed(id: Long) = lock.withLock {
        val now = clock()
        val draft = PhoneDrafts.pending(load(), id, now) ?: return@withLock
        if (draft.exp - now > DISMISS_MARGIN_MS) settleIgnored(id, now)
    }

    /** Déconnexion, interrupteur coupé : plus aucune proposition dans le volet ni sur le disque. */
    suspend fun wipe() = lock.withLock {
        kv.put(Kv.PHONE_DRAFTS, null)
        cancelAll()
    }

    /** Au démarrage : les propositions expirées quittent le disque. */
    suspend fun prune() = lock.withLock {
        val book = load()
        val pruned = PhoneDrafts.prune(book, clock())
        if (pruned != book) save(pruned)
    }

    private suspend fun settleIgnored(id: Long, now: Long) {
        val book = load()
        if (PhoneDrafts.pending(book, id, now) == null) return
        save(PhoneDrafts.settled(book, id))
        outbox.settle(id, Settlement.IGNORED)
        outbox.flushSoon()
    }

    /** Le texte dans la saisie de l'action « Répondre » de l'appli, comme si la personne l'avait tapé là. */
    private fun deliver(action: Notification.Action, text: String): Boolean {
        val target = action.actionIntent ?: return false
        val inputs = action.remoteInputs?.filter { it.allowFreeFormInput }.orEmpty()
        if (inputs.isEmpty()) return false
        val results = Bundle().apply { for (input in inputs) putCharSequence(input.resultKey, text) }
        val intent = Intent()
        android.app.RemoteInput.addResultsToIntent(inputs.toTypedArray(), intent, results)
        android.app.RemoteInput.setResultsSource(intent, android.app.RemoteInput.SOURCE_FREE_FORM_INPUT)
        return try {
            target.send(context, 0, intent)
            true
        } catch (e: PendingIntent.CanceledException) {
            logger.w(TAG, "action « Répondre » périmée : le texte sera copié", e)
            false
        }
    }

    private fun copy(text: String): Boolean {
        val clipboard = context.getSystemService(ClipboardManager::class.java) ?: return false
        return try {
            clipboard.setPrimaryClip(ClipData.newPlainText(context.getString(R.string.phone_clip_label), text))
            true
        } catch (e: SecurityException) {
            logger.w(TAG, "presse-papier refusé", e)
            false
        }
    }

    private fun post(draft: PhoneDraft, now: Long, alert: Boolean) {
        val app = appLabel(draft.app)
        val title = if (draft.to.isBlank()) {
            context.getString(R.string.phone_draft_title_nameless, app)
        } else {
            context.getString(R.string.phone_draft_title, draft.to, app)
        }
        val input = RemoteInput.Builder(NotificationActionReceiver.KEY_PHONE_REPLY)
            .setLabel(context.getString(R.string.phone_draft_other_hint))
            .build()
        val builder = NotificationCompat.Builder(context, NotificationChannels.PHONE_DRAFTS)
            .setSmallIcon(R.drawable.ic_stat_mika)
            .setContentTitle(title)
            .setContentText(draft.text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(draft.text).setBigContentTitle(title))
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            // Écran verrouillé : qu'une réponse attend, jamais son texte ni à qui.
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setPublicVersion(publicVersion(R.string.phone_draft_public))
            .setTimeoutAfter((draft.exp - now).coerceIn(1L, MAX_TIMEOUT_MS))
            .setSilent(!alert)
            .setOnlyAlertOnce(true)
            .setAutoCancel(false)
            .setContentIntent(openChat())
            .setDeleteIntent(broadcast(NotificationActionReceiver.ACTION_PHONE_DISMISS, draft.id, mutable = false))
            .addAction(
                NotificationCompat.Action.Builder(
                    R.drawable.ic_send,
                    context.getString(R.string.phone_draft_send),
                    broadcast(NotificationActionReceiver.ACTION_PHONE_SEND, draft.id, mutable = false),
                ).setShowsUserInterface(false).build(),
            )
            .addAction(
                // Mutable : le système doit pouvoir y glisser le texte tapé (RemoteInput).
                NotificationCompat.Action.Builder(
                    R.drawable.ic_send,
                    context.getString(R.string.phone_draft_other),
                    broadcast(NotificationActionReceiver.ACTION_PHONE_OTHER, draft.id, mutable = true),
                )
                    .addRemoteInput(input)
                    .setAllowGeneratedReplies(false)
                    .setSemanticAction(NotificationCompat.Action.SEMANTIC_ACTION_REPLY)
                    .setShowsUserInterface(false)
                    .build(),
            )
            .addAction(
                NotificationCompat.Action.Builder(
                    R.drawable.ic_close,
                    context.getString(R.string.phone_draft_ignore),
                    broadcast(NotificationActionReceiver.ACTION_PHONE_IGNORE, draft.id, mutable = false),
                ).setShowsUserInterface(false).build(),
            )
        if (draft.ts > 0) builder.setWhen(draft.ts).setShowWhen(true)
        MessageNotifier.show(context, PhoneDrafts.notificationId(draft.id), builder.build(), NOTIFICATION_TAG)
    }

    /** Le repli : le texte est dans le presse-papier, toucher la notification ouvre l'appli pour le coller. */
    private fun postCopied(draft: PhoneDraft, text: String) {
        val app = appLabel(draft.app)
        val launch = PhoneApp.ofCode(draft.app)?.let { context.packageManager.getLaunchIntentForPackage(it.packageName) }
        val builder = NotificationCompat.Builder(context, NotificationChannels.PHONE_DRAFTS)
            .setSmallIcon(R.drawable.ic_stat_mika)
            .setContentTitle(context.getString(R.string.phone_copied_title, app))
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setPublicVersion(publicVersion(R.string.phone_copied_public))
            .setSilent(true)
            .setAutoCancel(true)
            .setTimeoutAfter(COPIED_TIMEOUT_MS)
        if (launch != null) {
            builder.setContentIntent(
                PendingIntentCompat.getActivity(
                    context,
                    PhoneDrafts.notificationId(draft.id),
                    launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                    PendingIntent.FLAG_UPDATE_CURRENT,
                    false,
                ),
            )
        }
        MessageNotifier.show(context, PhoneDrafts.notificationId(draft.id), builder.build(), NOTIFICATION_TAG)
    }

    private fun publicVersion(text: Int): Notification = NotificationCompat.Builder(context, NotificationChannels.PHONE_DRAFTS)
        .setSmallIcon(R.drawable.ic_stat_mika)
        .setContentTitle(context.getString(R.string.mika))
        .setContentText(context.getString(text))
        .build()

    private fun appLabel(code: String): String = context.getString(
        when (PhoneApp.ofCode(code)) {
            PhoneApp.WHATSAPP -> R.string.phone_app_whatsapp
            PhoneApp.WHATSAPP_BUSINESS -> R.string.phone_app_whatsapp_business
            // Une appli inconnue n'arrive pas ici (PhoneDrafts.isValid) : « Messages » par défaut.
            PhoneApp.MESSAGES, PhoneApp.SAMSUNG_MESSAGES, null -> R.string.phone_app_messages
        },
    )

    private fun openChat() = PendingIntentCompat.getActivity(
        context,
        REQ_OPEN,
        Intent(context, MainActivity::class.java)
            .putExtra(DeepLinks.EXTRA_OPEN, DeepLinks.CHAT)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_UPDATE_CURRENT,
        false,
    )

    private fun broadcast(action: String, id: Long, mutable: Boolean) = PendingIntentCompat.getBroadcast(
        context,
        PhoneDrafts.notificationId(id),
        Intent(context, NotificationActionReceiver::class.java)
            .setAction(action)
            // Une intention par proposition : sans cette adresse, FLAG_UPDATE_CURRENT réécrirait celle d'une autre.
            .setData(Uri.fromParts(URI_SCHEME, id.toString(), null))
            .putExtra(NotificationActionReceiver.EXTRA_DRAFT_ID, id),
        PendingIntent.FLAG_UPDATE_CURRENT,
        mutable,
    )

    private fun cancel(id: Long) {
        context.getSystemService(NotificationManager::class.java)?.cancel(NOTIFICATION_TAG, PhoneDrafts.notificationId(id))
    }

    /** Toutes les notifications de propositions (et de copies), même celles dont le disque a déjà été effacé. */
    private fun cancelAll() {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        for (shown in manager.activeNotifications) {
            if (shown.tag == NOTIFICATION_TAG) manager.cancel(shown.tag, shown.id)
        }
    }

    private suspend fun load(): PhoneDraftBook = try {
        kv.get(Kv.PHONE_DRAFTS)?.let { MikaJson.decodeFromString(PhoneDraftBook.serializer(), it) } ?: PhoneDraftBook()
    } catch (_: IllegalArgumentException) {
        PhoneDraftBook()
    }

    private suspend fun save(book: PhoneDraftBook) {
        val empty = book.pending.isEmpty() && book.shown.isEmpty()
        kv.put(Kv.PHONE_DRAFTS, if (empty) null else MikaJson.encodeToString(PhoneDraftBook.serializer(), book))
    }

    companion object {
        private const val TAG = "PhoneDraft"
        /** L'étiquette de leurs notifications : les retrouver toutes, à la déconnexion. */
        const val NOTIFICATION_TAG = "phone_draft"
        private const val URI_SCHEME = "mika-phone-draft"
        private const val REQ_OPEN = 20
        /** Une notification ne vit pas plus d'un jour, quoi que dise une échéance farfelue. */
        private const val MAX_TIMEOUT_MS = 24L * 60 * 60 * 1000
        /** « Copié » reste un quart d'heure : le temps d'ouvrir l'appli et de coller. */
        private const val COPIED_TIMEOUT_MS = 15L * 60 * 1000
        /** Une notification balayée dans les dernières secondes de sa vie : c'est son échéance, pas un geste. */
        private const val DISMISS_MARGIN_MS = 5_000L
    }
}
