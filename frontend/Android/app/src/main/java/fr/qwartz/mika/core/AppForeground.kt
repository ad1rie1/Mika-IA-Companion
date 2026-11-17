package fr.qwartz.mika.core

import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * L'app est-elle au premier plan ? (`ProcessLifecycleOwner` : ON_START / ON_STOP de l'ensemble des
 * activités, avec le petit délai qui ignore une rotation.) C'est ce qui décide de la présence
 * annoncée à Mika. Les notifications, elles, suivent [chatOnScreen] : avec le tiroir (ADR 0235), l'app
 * ouverte peut montrer Mail, Teams ou la Carte pendant des minutes.
 */
class AppForeground : DefaultLifecycleObserver {
    private val _visible = MutableStateFlow(false)
    val visible: StateFlow<Boolean> = _visible.asStateFlow()

    /** Le sommet de la pile du cadre est la conversation (ce que `MikaRoot` dit à chaque écran ; hors session, non). */
    @Volatile private var chatOnTop = false

    /**
     * La conversation est à l'écran : l'app au premier plan **et** la conversation au sommet de la pile. « Ce qu'elle
     * fait », une image, la recherche ou les fichiers par-dessus le chat n'en sont pas : ses bulles n'y sont pas, et
     * rien ne s'y marque lu.
     */
    val chatOnScreen: Boolean get() = _visible.value && chatOnTop

    /** Le cadre dit ce qui est au sommet de sa pile : [chat] vrai quand c'est la conversation. */
    fun onTop(chat: Boolean) {
        chatOnTop = chat
    }

    fun install() {
        ProcessLifecycleOwner.get().lifecycle.addObserver(this)
    }

    override fun onStart(owner: LifecycleOwner) {
        _visible.value = true
    }

    override fun onStop(owner: LifecycleOwner) {
        _visible.value = false
    }
}
