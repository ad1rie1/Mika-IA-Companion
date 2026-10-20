package fr.qwartz.mika.data.phone

import kotlinx.serialization.Serializable

/**
 * Une réponse que Mika propose d'envoyer à la place de la personne (ADR 0120), arrivée scellée par Firebase
 * (`{"t": "phone_draft", …}`). C'est le téléphone qui demande l'autorisation : le geste de la personne vaut accord.
 */
@Serializable
data class PhoneDraft(
    /** L'identifiant de la proposition chez le serveur : c'est lui que le sort rappelle. */
    val id: Long = 0,
    /** Le code de l'appli ([PhoneApp.code]). */
    val app: String = "",
    /** La conversation ([PhoneKeys.thread]) : son action « Répondre » est gardée sous cette clé. */
    val thread: String = "",
    /** À qui elle répond (le nom affiché) ; vide si le serveur ne le sait pas. */
    val to: String = "",
    val text: String = "",
    /** Au-delà (ms, heure murale), la proposition a expiré : la notification disparaît. */
    val exp: Long = 0,
    /** Quand le serveur l'a proposée (ms). */
    val ts: Long = 0,
)

/** Les propositions en attente d'un geste, et celles déjà montrées (gardées sur disque le temps de leur `exp`). */
@Serializable
data class PhoneDraftBook(
    val pending: List<PhoneDraft> = emptyList(),
    /** Les identifiants déjà montrés : Firebase peut redire un message, il ne se remontre pas. */
    val shown: List<Long> = emptyList(),
)

/** Les règles des propositions, pures (ADR 0120) : ce qui se montre, ce qui attend un geste, ce qui a expiré. */
object PhoneDrafts {
    const val MAX_SHOWN = 200
    const val MAX_PENDING = 50

    sealed interface Admission {
        /** À montrer ; [book] la garde en attente. */
        data class Show(val book: PhoneDraftBook) : Admission
        /** Déjà expirée à son arrivée (Firebase l'a gardée trop longtemps) : jamais montrée. */
        data object Expired : Admission
        /** Déjà montrée (même identifiant). */
        data object Seen : Admission
    }

    /** Une proposition lisible : un identifiant, une appli connue, une conversation, un texte, une échéance. */
    fun isValid(draft: PhoneDraft): Boolean =
        draft.id > 0 && PhoneApp.ofCode(draft.app) != null && PhoneKeys.isKey(draft.thread) &&
            draft.text.isNotBlank() && draft.exp > 0

    fun admit(book: PhoneDraftBook, draft: PhoneDraft, now: Long): Admission {
        if (draft.id in book.shown || book.pending.any { it.id == draft.id }) return Admission.Seen
        if (draft.exp <= now) return Admission.Expired
        val pending = (prune(book, now).pending + draft).takeLast(MAX_PENDING)
        val shown = (book.shown + draft.id).takeLast(MAX_SHOWN)
        return Admission.Show(PhoneDraftBook(pending, shown))
    }

    /** La proposition qui attend encore un geste ; `null` si elle n'existe pas, est réglée ou a expiré. */
    fun pending(book: PhoneDraftBook, id: Long, now: Long): PhoneDraft? =
        book.pending.firstOrNull { it.id == id && it.exp > now }

    /** Réglée (envoyée, copiée, ignorée) : elle n'attend plus. Elle reste « montrée ». */
    fun settled(book: PhoneDraftBook, id: Long): PhoneDraftBook =
        book.copy(pending = book.pending.filterNot { it.id == id })

    /** Les expirées partent : le serveur les a closes de son côté (`phone.expire`). */
    fun prune(book: PhoneDraftBook, now: Long): PhoneDraftBook =
        book.copy(pending = book.pending.filter { it.exp > now })

    /**
     * L'identifiant de la notification d'une proposition : dérivé du sien, au-dessus de ceux de l'app (1, 2) — une
     * notification par proposition, que ses gestes retrouvent.
     */
    fun notificationId(id: Long): Int = (NOTIFICATION_BASE + Math.floorMod(id, NOTIFICATION_SPAN)).toInt()

    private const val NOTIFICATION_BASE = 1_000L
    private const val NOTIFICATION_SPAN = 1_000_000_000L
}
