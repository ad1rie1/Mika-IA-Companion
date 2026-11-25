package fr.qwartz.mika.ui.agenda

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.agenda.Accounts
import fr.qwartz.mika.data.moi.agenda.AgendaAccount
import fr.qwartz.mika.data.moi.agenda.AgendaCalendar
import fr.qwartz.mika.data.moi.agenda.AgendaDone
import fr.qwartz.mika.data.moi.agenda.AgendaKinds
import fr.qwartz.mika.data.moi.agenda.AgendaSignin
import fr.qwartz.mika.data.moi.agenda.TriedCalendar
import fr.qwartz.mika.data.moi.agenda.rightsSummary
import fr.qwartz.mika.data.moi.agenda.withShownNames
import fr.qwartz.mika.data.net.Topics
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.SettingsPages
import fr.qwartz.mika.ui.components.settingsPage
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

/**
 * Où en est un parcours « Brancher un agenda » : sa sorte, le compte créé pour lui (Google, Microsoft), son étape, ce que
 * le serveur a rendu (l'adresse de Google et s'il revient seul, le code de Microsoft, les agendas trouvés en CalDAV),
 * sa panne en mots.
 */
data class Plug(
    val kind: String,
    val account: String = "",
    val step: Int = 1,
    val url: String = "",
    val direct: Boolean = false,
    val code: String = "",
    val until: Long = 0,
    val tried: List<TriedCalendar> = emptyList(),
    val error: String = "",
    /** CalDAV essayé : ce qui a été essayé, pour le brancher tel quel. */
    val server: String = "",
    val username: String = "",
    val password: String = "",
    val synced: Boolean = false,
)

/** Où aller après un geste de Paramètres › Agendas. */
sealed interface AgendaMove {
    data object Back : AgendaMove
    data class To(val route: Route) : AgendaMove
}

/**
 * Paramètres › Agendas (ADR 0309, la maquette validée `agenda-parametres.js`) : ses comptes, ce qu'on lui partage et
 * l'agenda de Mika, la page d'un compte et d'un agenda, « Brancher un agenda » par sorte. Un modèle pour toutes ces
 * pages, pour la session : relu au retour sur une page et quand le direct dit `agenda` (une connexion Microsoft finie
 * y fait avancer le parcours) ; un geste à la fois, son sort en toast.
 */
class AgendaSettingsViewModel(private val deps: AgendaDeps) : ViewModel() {
    private val api = deps.api
    private val notices = Channel<String>(Channel.BUFFERED)
    private val moves = Channel<AgendaMove>(Channel.BUFFERED)

    val said: Flow<String> = notices.receiveAsFlow()
    val moved: Flow<AgendaMove> = moves.receiveAsFlow()

    var accounts by mutableStateOf<Load<Accounts>>(Load.Loading)
        private set
    var calendars by mutableStateOf<List<AgendaCalendar>>(emptyList())
        private set
    /** Le fuseau du serveur : l'Agenda s'y lit. */
    var zone by mutableStateOf("")
        private set
    /** Ce que Mika fait de chacun de ses agendas, en une ligne (son tableau). */
    var summaries by mutableStateOf<Map<String, String>>(emptyMap())
        private set
    var acting by mutableStateOf(false)
        private set
    /** Les refus d'un formulaire, par champ. */
    var fields by mutableStateOf<Map<String, String>>(emptyMap())
        private set
    var plug by mutableStateOf<Plug?>(null)
        private set

    private var me = ""
    private var started = false
    private var job: Job? = null

    private fun say(text: String) {
        if (text.isNotBlank()) notices.trySend(text)
    }

    fun account(key: String): AgendaAccount? = accounts.valueOrNull?.accounts?.firstOrNull { it.key == key }

    fun calendar(key: String): AgendaCalendar? = calendars.firstOrNull { it.key == key }

    fun resume(person: String) {
        me = person
        val quiet = started
        started = true
        load(quiet)
    }

    suspend fun onLive(signal: LiveSignal) {
        if (started && signal.touches(Topics.AGENDA)) load(quiet = true).join()
    }

    fun retry() {
        accounts = Load.Loading
        load(quiet = false)
    }

    private fun load(quiet: Boolean): Job {
        job?.cancel()
        return viewModelScope.launch {
            val cals = async { api.calendars() }
            val got = api.accounts()
            (cals.await() as? MoiApi.Result.Ok)?.let { c ->
                calendars = withShownNames(c.value.calendars)
                zone = c.value.zone
                val owned = calendars.filter { it.owned && it.can.rights && !it.hidden }
                summaries = owned.map { k -> async { k.key to ((api.rights(k.key) as? MoiApi.Result.Ok)?.value?.let { rightsSummary(it, me, k.shares, k.writable) }.orEmpty()) } }
                    .associate { it.await() }
            }
            when (got) {
                is MoiApi.Result.Ok -> {
                    accounts = Load.Ready(got.value)
                    advance()
                }
                is MoiApi.Result.Failed -> if (accounts is Load.Ready) {
                    if (!quiet) say(got.error.said)
                } else {
                    accounts = Load.Failed(got.error)
                }
            }
        }.also { job = it }
    }

    /** Le direct a relu les comptes : un parcours qui attendait une connexion avance (et se synchronise, une fois). */
    private fun advance() {
        val p = plug ?: return
        if (p.account.isEmpty() || p.step != 2) return
        val a = account(p.account) ?: return
        if ((p.kind == AgendaKinds.GOOGLE || p.kind == AgendaKinds.MICROSOFT) && a.signin?.state == AgendaSignin.CONNECTED) {
            plug = p.copy(step = 3, error = "", synced = true)
            if (!p.synced) viewModelScope.launch { api.sync(p.account) }
        } else if (p.kind == AgendaKinds.MICROSOFT && !a.signin?.error.isNullOrBlank()) {
            plug = p.copy(error = a.signin?.error.orEmpty())
        }
    }

    // ── un compte ──

    fun sync(account: String) = act { api.sync(account) }

    fun disconnect(account: String) = act { api.disconnect(account) }

    fun remove(account: String) = act(then = AgendaMove.Back) { api.removeAccount(account) }

    /** Régler un compte : son nom, son serveur ; un refus se dit sous ses champs. */
    fun saveAccount(a: AgendaAccount, values: Map<String, Any>) {
        if (acting) return
        acting = true
        fields = emptyMap()
        viewModelScope.launch {
            when (val got = api.saveAccount(a.kind, a.key, values)) {
                is MoiApi.Result.Ok -> say(got.value.message)
                is MoiApi.Result.Failed -> {
                    fields = got.error.fields
                    say(got.error.said)
                }
            }
            acting = false
            load(quiet = true)
        }
    }

    /** Essayer le serveur CalDAV d'un compte (son mot de passe gardé, sauf un nouveau tapé). */
    fun tryAccount(a: AgendaAccount, url: String, username: String, password: String) {
        if (acting) return
        acting = true
        viewModelScope.launch {
            when (val got = api.tryCaldav(url, username, password, a.key)) {
                is MoiApi.Result.Ok -> say(got.value.message)
                is MoiApi.Result.Failed -> say(got.error.said)
            }
            acting = false
        }
    }

    /** Un agenda de plus chez ce compte (un compte qui le sait : `abilities.calendars`). */
    fun newCalendar(account: String, name: String) = act { api.newCalendar(name, account) }

    // ── un agenda ──

    /** Régler un de ses agendas (son nom, sa couleur, masqué, « Mika te le rappelle ») : tout de suite. */
    fun saveCalendar(key: String, changes: Map<String, Any>) = act { api.saveCalendar(key, changes) }

    // ── brancher ──

    /** Commencer (ou reprendre) un parcours : pour [account], se reconnecter. */
    fun startPlug(kind: String, account: String = "") {
        val p = plug
        if (p != null && p.kind == kind && p.account == account && account.isNotEmpty()) return
        if (p != null && p.kind == kind && account.isEmpty() && p.account.isEmpty()) return
        plug = Plug(kind, account)
        fields = emptyMap()
    }

    fun stepBack(step: Int) {
        plug = plug?.copy(step = step, error = "")
    }

    /** Un agenda de ce serveur : son nom, sa couleur, « Mika te le rappelle ». */
    fun plugSystem(name: String, color: String, reminder: String) {
        if (name.isBlank()) {
            plug = plug?.copy(error = NAME_IT)
            return
        }
        gesture {
            when (val made = api.newCalendar(name.trim(), "")) {
                is MoiApi.Result.Ok -> {
                    made.value.made?.calendar?.takeIf { it.isNotEmpty() }?.let { api.saveCalendar(it, mapOf("color" to color, "reminder" to reminder)) }
                    say(made.value.message)
                    plug = null
                    moves.trySend(AgendaMove.Back)
                }
                is MoiApi.Result.Failed -> plug = plug?.copy(error = made.error.said)
            }
        }
    }

    /** Google : le compte (créé s'il le faut), puis l'adresse de consentement à ouvrir dans le navigateur. */
    fun googleStart(open: (String) -> Unit) = gesture {
        val p = plug ?: return@gesture
        val account = p.account.ifEmpty {
            when (val saved = api.saveAccount(AgendaKinds.GOOGLE, "", mapOf("label" to "Google"))) {
                is MoiApi.Result.Ok -> saved.value.account
                is MoiApi.Result.Failed -> {
                    plug = p.copy(error = saved.error.said)
                    return@gesture
                }
            }
        }
        when (val got = api.googleStart(account)) {
            is MoiApi.Result.Ok -> {
                plug = p.copy(account = account, url = got.value.url, direct = got.value.direct, step = 2, error = "")
                if (got.value.url.isNotEmpty()) open(got.value.url)
            }
            is MoiApi.Result.Failed -> plug = p.copy(account = account, error = got.error.said)
        }
    }

    /** Google : l'adresse de la page qui n'a pas pu s'ouvrir, collée. */
    fun googleFinish(text: String) = gesture {
        val p = plug ?: return@gesture
        if (text.isBlank()) {
            plug = p.copy(error = PASTE_IT)
            return@gesture
        }
        when (val got = api.googleFinish(p.account, text.trim())) {
            is MoiApi.Result.Ok -> {
                say(got.value.message)
                plug = p.copy(step = 3, error = "", synced = true)
                load(quiet = true)
            }
            is MoiApi.Result.Failed -> plug = p.copy(error = got.error.fields["text"] ?: got.error.said)
        }
    }

    /** Microsoft : le compte (son adresse), puis un code à entrer chez Microsoft ; la fin de l'attente est poussée. */
    fun microsoftStart(address: String) = gesture {
        val p = plug ?: return@gesture
        val account = p.account.ifEmpty {
            val label = address.substringBefore('@').ifBlank { "Outlook" }
            when (val saved = api.saveAccount(AgendaKinds.MICROSOFT, "", mapOf("label" to label, "address" to address.trim()))) {
                is MoiApi.Result.Ok -> saved.value.account
                is MoiApi.Result.Failed -> {
                    plug = p.copy(error = saved.error.said)
                    return@gesture
                }
            }
        }
        when (val got = api.microsoftStart(account)) {
            is MoiApi.Result.Ok -> plug = p.copy(
                account = account, code = got.value.code, url = got.value.url, until = got.value.until,
                step = if (got.value.state == AgendaSignin.CONNECTED) 3 else 2, error = got.value.error,
            )
            is MoiApi.Result.Failed -> plug = p.copy(account = account, error = got.error.said)
        }
        load(quiet = true)
    }

    /** CalDAV : essayer le serveur ; ses agendas trouvés. */
    fun caldavTry(url: String, username: String, password: String) = gesture {
        val p = plug ?: return@gesture
        when (val got = api.tryCaldav(url.trim(), username.trim(), password)) {
            is MoiApi.Result.Ok -> plug = if (got.value.ok) {
                p.copy(step = 2, tried = got.value.calendars, server = url.trim(), username = username.trim(), password = password, error = "")
            } else {
                p.copy(error = got.value.message)
            }
            is MoiApi.Result.Failed -> plug = p.copy(error = got.error.said)
        }
    }

    /** CalDAV : le brancher tel qu'il a été essayé ; sa page s'ouvre. */
    fun caldavPlug(label: String) = gesture {
        val p = plug ?: return@gesture
        val values = mapOf("label" to label.ifBlank { "CalDAV" }, "url" to p.server, "username" to p.username, "password" to p.password)
        when (val got = api.saveAccount(AgendaKinds.CALDAV, "", values, fr.qwartz.mika.data.moi.MoiApi.newKey())) {
            is MoiApi.Result.Ok -> {
                say(got.value.message)
                plug = null
                moves.trySend(AgendaMove.To(settingsPage(SettingsPages.AGENDA_ACCOUNT, got.value.account)))
            }
            is MoiApi.Result.Failed -> plug = p.copy(error = got.error.said)
        }
    }

    /** Un abonnement iCal : son adresse et son nom ; il se relit aussitôt, sa page s'ouvre. */
    fun icalPlug(url: String, label: String) = gesture {
        val p = plug ?: return@gesture
        when (val got = api.saveAccount(AgendaKinds.ICAL, "", mapOf("label" to label.ifBlank { "Abonnement" }, "url" to url.trim()))) {
            is MoiApi.Result.Ok -> {
                say(got.value.message)
                plug = null
                moves.trySend(AgendaMove.To(settingsPage(SettingsPages.AGENDA_ACCOUNT, got.value.account)))
            }
            is MoiApi.Result.Failed -> plug = p.copy(error = got.error.fields["url"] ?: got.error.said)
        }
    }

    /** Fini : la page du compte branché. */
    fun plugDone() {
        val p = plug ?: return
        plug = null
        moves.trySend(if (p.account.isNotEmpty()) AgendaMove.To(settingsPage(SettingsPages.AGENDA_ACCOUNT, p.account)) else AgendaMove.Back)
    }

    private fun gesture(block: suspend () -> Unit) {
        if (acting) return
        acting = true
        viewModelScope.launch {
            try {
                block()
            } finally {
                acting = false
            }
        }
    }

    private fun act(then: AgendaMove? = null, call: suspend () -> MoiApi.Result<AgendaDone>) {
        if (acting) return
        acting = true
        viewModelScope.launch {
            when (val got = call()) {
                is MoiApi.Result.Ok -> {
                    say(got.value.message)
                    then?.let { moves.trySend(it) }
                }
                is MoiApi.Result.Failed -> say(got.error.said)
            }
            acting = false
            load(quiet = true)
        }
    }

    private companion object {
        const val NAME_IT = "Donne-lui un nom."
        const val PASTE_IT = "Colle l'adresse de la page qui n'a pas pu s'ouvrir."
    }
}
