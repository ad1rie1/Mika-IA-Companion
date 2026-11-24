package fr.qwartz.mika.data.moi.agenda

import android.content.Context
import android.content.SharedPreferences
import androidx.core.content.edit
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Ce que l'Agenda retient sur ce téléphone, pour la personne connectée (ce que le web garde dans son navigateur) : la
 * dernière vue choisie (la vue de départ, recommandation validée), les agendas décochés — l'affichage seulement :
 * Mika s'en sert toujours ; les masquer dans Paramètres › Agendas la coupe (recommandation 8) —, et ce que le canal
 * « Agenda » a déjà notifié. Une autre session ne reprend rien : chaque clé porte la session ([session]).
 */
interface AgendaPrefs {
    val off: StateFlow<Set<String>>
    fun view(): AgendaView
    fun setView(view: AgendaView)
    fun setShown(key: String, on: Boolean)
    /** N'afficher que celui-ci parmi [all]. */
    fun showOnly(key: String, all: Collection<String>)
    fun notified(): Set<String>
    fun setNotified(keys: Set<String>)
    /** La session ouverte : ce qui suit se lit et s'écrit sous elle. */
    fun open(session: String)
    fun wipe()
}

/** En mémoire : les tests, et l'avant d'une session. */
open class MemoryAgendaPrefs : AgendaPrefs {
    private val _off = MutableStateFlow<Set<String>>(emptySet())
    override val off: StateFlow<Set<String>> = _off.asStateFlow()
    private var view = AgendaView.PLANNING
    private var seen: Set<String> = emptySet()

    override fun view(): AgendaView = view
    override fun setView(view: AgendaView) {
        this.view = view
    }

    override fun setShown(key: String, on: Boolean) {
        _off.value = if (on) _off.value - key else _off.value + key
    }

    override fun showOnly(key: String, all: Collection<String>) {
        _off.value = all.filter { it != key }.toSet()
    }

    override fun notified(): Set<String> = seen
    override fun setNotified(keys: Set<String>) {
        seen = keys
    }

    override fun open(session: String) = Unit

    override fun wipe() {
        _off.value = emptySet()
        view = AgendaView.PLANNING
        seen = emptySet()
    }
}

/** Dans les préférences privées de l'app (`agenda.xml`), effacées à la déconnexion. */
class StoredAgendaPrefs(context: Context) : AgendaPrefs {
    private val prefs: SharedPreferences = context.applicationContext.getSharedPreferences("agenda", Context.MODE_PRIVATE)
    private var session = ""
    private val _off = MutableStateFlow<Set<String>>(emptySet())
    override val off: StateFlow<Set<String>> = _off.asStateFlow()

    private fun k(name: String) = "$session|$name"

    override fun open(session: String) {
        if (session == this.session) return
        this.session = session
        _off.value = prefs.getStringSet(k(OFF), emptySet())?.toSet().orEmpty()
    }

    override fun view(): AgendaView = AgendaView.of(prefs.getString(k(VIEW), null))

    override fun setView(view: AgendaView) {
        prefs.edit { putString(k(VIEW), view.code) }
    }

    override fun setShown(key: String, on: Boolean) {
        save(if (on) _off.value - key else _off.value + key)
    }

    override fun showOnly(key: String, all: Collection<String>) {
        save(all.filter { it != key }.toSet())
    }

    private fun save(set: Set<String>) {
        _off.value = set
        prefs.edit { putStringSet(k(OFF), set) }
    }

    override fun notified(): Set<String> = prefs.getStringSet(k(SEEN), emptySet())?.toSet().orEmpty()

    override fun setNotified(keys: Set<String>) {
        prefs.edit { putStringSet(k(SEEN), keys) }
    }

    override fun wipe() {
        prefs.edit { clear() }
        _off.value = emptySet()
        session = ""
    }

    private companion object {
        const val VIEW = "vue"
        const val OFF = "decoches"
        const val SEEN = "notifies"
    }
}
