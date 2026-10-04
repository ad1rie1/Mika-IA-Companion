package fr.qwartz.mika.data.approvals

import fr.qwartz.mika.core.Clock
import fr.qwartz.mika.data.net.ApprovalDecision
import fr.qwartz.mika.data.net.ServerFrame
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

/**
 * Les cartes d'accord de la personne, en mémoire seulement : elles ne valent que pour la socket qui
 * les a reçues (une nouvelle socket repart de zéro, la déconnexion les oublie). Les règles sont dans
 * [Approvals] ; ici, l'état observable et les messages d'un instant (le sort d'une décision).
 *
 * Écrit depuis le contexte sérialisé de l'app (`ConnectionManager`).
 */
class ApprovalsRepository(private val clock: Clock) {
    private val _state = MutableStateFlow(ApprovalsState())
    val state: StateFlow<ApprovalsState> = _state.asStateFlow()

    /** Ce qu'il faut dire une fois (« Refusé : rien ne partira. ») ; perdu si personne n'écoute. */
    private val _messages = MutableSharedFlow<String>(extraBufferCapacity = 8, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val messages: SharedFlow<String> = _messages.asSharedFlow()

    /** Une socket vient de s'ouvrir : le serveur n'enverra la liste que si elle n'est pas vide. */
    fun onOpened() {
        _state.value = Approvals.opened()
    }

    fun onApprovals(frame: ServerFrame.Approvals) {
        _state.value = Approvals.received(frame.items)
    }

    fun onResult(frame: ServerFrame.ApprovalResult) {
        _state.update { Approvals.resolved(it, frame.id) }
        say(Approvals.resultMessage(frame.status))
    }

    fun onSent(id: Long, decision: ApprovalDecision) {
        _state.update { Approvals.sent(it, id, decision, clock.elapsedMs()) }
    }

    fun say(message: String) {
        _messages.tryEmit(message)
    }

    /** Fin de session : plus rien n'attend son accord sur ce téléphone. */
    fun reset() {
        _state.value = ApprovalsState()
    }
}
