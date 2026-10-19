package fr.qwartz.mika.share

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.data.files.ComposerDraft
import fr.qwartz.mika.graph
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * La copie et le dépôt d'un partage, tenus hors de [ShareActivity] : une rotation, un pliable qu'on
 * déplie ou un changement de thème recréent l'activité sans annuler le travail en cours, que la
 * nouvelle instance attend pour ouvrir la conversation.
 */
class ShareViewModel(application: Application) : AndroidViewModel(application) {
    private val _deposited = MutableStateFlow(false)
    val deposited: StateFlow<Boolean> = _deposited.asStateFlow()
    private var started = false

    /** Une seule fois par partage : une instance recréée retrouve le travail déjà lancé. */
    fun start(request: ShareRequest) {
        if (started) return
        started = true
        val graph = getApplication<Application>().graph
        viewModelScope.launch {
            val staged = graph.stager.stage(request.streams.map(Uri::parse), already = emptyList())
            graph.shareInbox.deposit(
                ComposerDraft(request.text.orEmpty(), staged.files, request.notices + staged.notices),
            )
            _deposited.value = true
        }
    }
}
