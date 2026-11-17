package fr.qwartz.mika.ui.shell

import androidx.compose.runtime.compositionLocalOf
import fr.qwartz.mika.data.approvals.Approvals
import fr.qwartz.mika.data.approvals.ApprovalsState

/**
 * Ce qui t'attend dans la conversation quand tu n'y es pas (la pastille de ☰ et de « Chat » dans le tiroir) : un
 * accord qu'elle demande — ni expiré, ni déjà décidé (sa réponse en route) —, ou une parole d'elle depuis ton dernier
 * lu. Sans elle, une tâche du mode pro restait bloquée sur un accord pendant qu'on lisait Mail (ADR 0165).
 */
object ChatCue {
    fun waiting(lastFromMika: Long, lastReadId: Long, approvals: ApprovalsState, nowWallMs: Long, nowElapsedMs: Long): Boolean =
        lastFromMika > lastReadId || open(approvals, nowWallMs, nowElapsedMs) > 0

    /** Combien d'accords attendent vraiment ta décision : ni expirés, ni déjà décidés (leur réponse en route). Outils ›
     *  Accords compte les mêmes que la pastille. */
    fun open(approvals: ApprovalsState, nowWallMs: Long, nowElapsedMs: Long): Int = approvals.cards.count { card ->
        !Approvals.isExpired(card.expiresAt, nowWallMs) && !Approvals.isPending(approvals.pending[card.id], nowElapsedMs)
    }
}

/** La pastille de la conversation, posée par le cadre seulement quand elle n'est pas à l'écran. */
val LocalChatCue = compositionLocalOf { false }
