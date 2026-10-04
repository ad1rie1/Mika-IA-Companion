package fr.qwartz.mika.data.approvals

import fr.qwartz.mika.data.net.ApprovalCard
import fr.qwartz.mika.data.net.ApprovalDecision
import fr.qwartz.mika.data.net.MikaProtocol
import kotlin.math.min

/**
 * Ce que l'app tient des cartes d'accord (ADR 0064) : la dernière liste reçue sur la socket en cours,
 * et les décisions parties qui n'ont pas encore de réponse.
 */
data class ApprovalsState(
    val cards: List<ApprovalCard> = emptyList(),
    val pending: Map<Long, PendingDecision> = emptyMap(),
)

/** Une décision partie ; `sentAtElapsedMs` sur l'horloge des durées. */
data class PendingDecision(val decision: ApprovalDecision, val sentAtElapsedMs: Long)

/** Une carte telle que l'écran la dessine : tout est déjà décidé ici, l'écran ne fait qu'afficher. */
data class ApprovalView(
    val id: Long,
    val title: String,
    /** Ce qui partira, tel quel. */
    val text: String,
    /** L'empreinte de la carte telle qu'elle est montrée : celle que la décision renvoie. */
    val digest: String,
    /** La phrase qui dit pourquoi ça ne peut pas partir, ou `null`. */
    val blocked: String?,
    /** « expire dans 4 min », « expirée », ou `null` sans échéance. */
    val expiry: String?,
    val expired: Boolean,
    /** La décision partie, en attente de sa réponse. */
    val pending: ApprovalDecision?,
    val canAccept: Boolean,
    val canRefuse: Boolean,
    /** Ce qui se passe, ou pourquoi « Accepter » est éteint ; `null` quand tout est possible. */
    val hint: String?,
)

/**
 * Les règles des cartes d'accord, pures : la liste reçue remplace tout, une socket qui s'ouvre repart
 * d'une liste vide (le serveur n'envoie la liste à l'ouverture que si elle n'est pas vide), une décision
 * attend sa réponse au plus [PENDING_TIMEOUT_MS], et seul le bouton accepte — jamais un « oui » tapé.
 */
object Approvals {
    /** Sans réponse au bout de ce délai, les boutons reviennent (la liste suivante tranchera). */
    const val PENDING_TIMEOUT_MS = 30_000L
    /** Le compte à rebours se recalcule au plus tard toutes les 30 s, et à chaque échéance. */
    const val TICK_MS = 30_000L
    const val MIN_TICK_MS = 1_000L

    const val FALLBACK_TITLE = "Une demande d'accord"
    const val NOT_SENT = "Hors ligne : ta décision n'est pas partie."

    // ── L'état ───────────────────────────────────────────────────────────────────────────

    /** Une socket vient de s'ouvrir : ce que disait la précédente ne vaut plus. */
    fun opened(): ApprovalsState = ApprovalsState()

    /** La liste entière, telle quelle ; les décisions en attente tombent avec l'ancienne liste. */
    fun received(cards: List<ApprovalCard>): ApprovalsState = ApprovalsState(cards)

    /** Le sort d'une décision est connu : elle n'attend plus (la liste qui suit dira le reste). */
    fun resolved(state: ApprovalsState, id: Long): ApprovalsState =
        if (id in state.pending) state.copy(pending = state.pending - id) else state

    /** Une décision est partie pour une carte affichée. */
    fun sent(state: ApprovalsState, id: Long, decision: ApprovalDecision, nowElapsedMs: Long): ApprovalsState =
        if (state.cards.none { it.id == id }) {
            state
        } else {
            state.copy(pending = state.pending + (id to PendingDecision(decision, nowElapsedMs)))
        }

    fun isPending(pending: PendingDecision?, nowElapsedMs: Long): Boolean =
        pending != null && nowElapsedMs - pending.sentAtElapsedMs < PENDING_TIMEOUT_MS

    fun isExpired(expiresAt: Long?, nowWallMs: Long): Boolean = expiresAt != null && nowWallMs >= expiresAt

    // ── Ce que l'écran montre ────────────────────────────────────────────────────────────

    fun views(state: ApprovalsState, online: Boolean, nowWallMs: Long, nowElapsedMs: Long): List<ApprovalView> =
        state.cards.map { view(it, state.pending[it.id], online, nowWallMs, nowElapsedMs) }

    fun view(card: ApprovalCard, pending: PendingDecision?, online: Boolean, nowWallMs: Long, nowElapsedMs: Long): ApprovalView {
        val expired = isExpired(card.expiresAt, nowWallMs)
        val waiting = pending?.takeIf { isPending(it, nowElapsedMs) }?.decision
        val blocked = card.blocked.takeIf { it.isNotEmpty() }
        val acceptable = blocked == null && !expired && card.digest.isNotEmpty() && card.complete
        val hint = when {
            waiting == ApprovalDecision.ACCEPT -> "Accord envoyé…"
            waiting == ApprovalDecision.REFUSE -> "Refus envoyé…"
            !online -> "Hors ligne : tu pourras décider au retour de la connexion."
            expired -> "Le délai est passé : seul le refus reste possible."
            blocked != null -> null // la raison est dite juste au-dessus
            !card.complete -> "Trop longue pour être montrée en entier ici : seul le refus est possible."
            card.digest.isEmpty() -> "Ce qui partirait n'a pas pu être relu : seul le refus est possible."
            else -> null
        }
        return ApprovalView(
            id = card.id,
            title = card.title.ifBlank { FALLBACK_TITLE },
            text = card.text,
            digest = card.digest,
            blocked = blocked?.let { "Ne peut pas partir tel quel : ${it.ifBlank { "raison non précisée" }.trim()}" },
            expiry = expiryLabel(card.expiresAt, nowWallMs),
            expired = expired,
            pending = waiting,
            canAccept = acceptable && online && waiting == null,
            canRefuse = online && waiting == null,
            hint = hint,
        )
    }

    /** Le compte à rebours, arrondi à la minute supérieure : « expire dans 4 min », « … 2 h 05 », « … 3 j ». */
    fun expiryLabel(expiresAt: Long?, nowWallMs: Long): String? {
        if (expiresAt == null) return null
        val left = expiresAt - nowWallMs
        if (left <= 0) return "expirée"
        if (left < MINUTE_MS) return "expire dans moins d'une minute"
        val minutes = (left + MINUTE_MS - 1) / MINUTE_MS
        return when {
            minutes < 60 -> "expire dans $minutes min"
            minutes < 24 * 60 -> {
                val h = minutes / 60
                val m = minutes % 60
                if (m == 0L) "expire dans $h h" else "expire dans $h h ${m.toString().padStart(2, '0')}"
            }
            else -> "expire dans ${minutes / (24 * 60)} j"
        }
    }

    /**
     * Quand recalculer : au plus tard [TICK_MS], plus tôt si une carte expire ou si une décision cesse
     * d'attendre avant ; jamais moins de [MIN_TICK_MS].
     */
    fun nextTickMs(state: ApprovalsState, nowWallMs: Long, nowElapsedMs: Long): Long {
        var next = TICK_MS
        for (card in state.cards) {
            val left = (card.expiresAt ?: continue) - nowWallMs
            if (left > 0) next = min(next, left)
        }
        for (p in state.pending.values) {
            val left = PENDING_TIMEOUT_MS - (nowElapsedMs - p.sentAtElapsedMs)
            if (left > 0) next = min(next, left)
        }
        return next.coerceAtLeast(MIN_TICK_MS)
    }

    /** Ce que dit le sort d'une décision. Un statut inconnu n'est jamais un succès. */
    fun resultMessage(status: String): String = when (status) {
        MikaProtocol.APPROVAL_APPROVED -> "Accepté : la demande part."
        MikaProtocol.APPROVAL_REJECTED -> "Refusé : rien ne partira."
        MikaProtocol.APPROVAL_UNKNOWN -> "Cette demande n'attend plus rien : déjà décidée, ou inconnue."
        MikaProtocol.APPROVAL_CHANGED -> "Ce qui partirait a changé : relis la carte avant de décider."
        MikaProtocol.APPROVAL_BLOCKED -> "Ça ne peut pas partir tel quel : rien n'est parti."
        MikaProtocol.APPROVAL_EXPIRED -> "Trop tard, la demande a expiré : rien n'est parti."
        MikaProtocol.APPROVAL_FORBIDDEN -> "Ce n'est pas à toi d'en décider : rien n'est parti."
        else -> "Décision non prise : rien n'est parti."
    }

    private const val MINUTE_MS = 60_000L
}
