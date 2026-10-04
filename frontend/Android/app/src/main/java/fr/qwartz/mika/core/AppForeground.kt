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
 * annoncée à Mika et des notifications.
 */
class AppForeground : DefaultLifecycleObserver {
    private val _visible = MutableStateFlow(false)
    val visible: StateFlow<Boolean> = _visible.asStateFlow()

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
