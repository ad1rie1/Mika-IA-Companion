package fr.qwartz.mika.ui.agenda

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.agenda.Accounts
import fr.qwartz.mika.data.moi.agenda.AgendaCalendar
import fr.qwartz.mika.data.moi.agenda.AgendaItem
import fr.qwartz.mika.data.moi.agenda.AgendaKinds
import fr.qwartz.mika.data.moi.agenda.AgendaView
import fr.qwartz.mika.data.moi.agenda.Calendars
import fr.qwartz.mika.data.moi.agenda.Occ
import fr.qwartz.mika.data.moi.agenda.Period
import fr.qwartz.mika.data.moi.agenda.Proposal
import fr.qwartz.mika.data.moi.agenda.addDays
import fr.qwartz.mika.data.moi.agenda.addMonths
import fr.qwartz.mika.data.moi.agenda.bounds
import fr.qwartz.mika.data.moi.agenda.localOf
import fr.qwartz.mika.data.moi.agenda.monthDays
import fr.qwartz.mika.data.moi.agenda.monthStart
import fr.qwartz.mika.data.moi.agenda.pendingAdds
import fr.qwartz.mika.data.moi.agenda.periodOccs
import fr.qwartz.mika.data.moi.agenda.readKeys
import fr.qwartz.mika.data.moi.agenda.shownHere
import fr.qwartz.mika.data.moi.agenda.step
import fr.qwartz.mika.data.moi.agenda.withShownNames
import fr.qwartz.mika.data.net.Topics
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

/**
 * L'Agenda (`Route.Agenda`) : ses agendas, la vue (la dernière choisie, Planning d'abord) et le jour qu'elle montre, la
 * période lue, ce qui attend ta décision (« À décider » : ce que Mika propose d'ajouter, tes invitations), ses comptes
 * en panne, et ce que l'app retient (les agendas décochés). Tout se relit au retour sur l'écran et quand le direct dit
 * `agenda` (ADR 0308), sans repasser en chargement ; un geste à la fois, son sort dit en toast.
 */
class AgendaViewModel(private val deps: AgendaDeps) : ViewModel() {
    private val api = deps.api
    private val notices = Channel<String>(Channel.BUFFERED)

    /** Le sort des gestes, une fois chacun. */
    val said: Flow<String> = notices.receiveAsFlow()

    var calendars by mutableStateOf<Load<Calendars>>(Load.Loading)
        private set
    var view by mutableStateOf(deps.prefs.view())
        private set
    /** Le jour que la vue montre (vide : aujourd'hui, une fois le fuseau du serveur lu). */
    var date by mutableStateOf("")
        private set
    var period by mutableStateOf<Load<Period>>(Load.Loading)
        private set
    /** Le mini-mois déplié sous le titre : son mois (`null` : replié), et ce qu'il montre. */
    var mini by mutableStateOf<String?>(null)
        private set
    var miniPeriod by mutableStateOf<Period?>(null)
        private set
    var invitations by mutableStateOf<List<AgendaItem>>(emptyList())
        private set
    var proposals by mutableStateOf<List<Proposal>>(emptyList())
        private set
    var accounts by mutableStateOf<Accounts?>(null)
        private set
    /** « À décider » déplié ; `null` : comme la vue le veut (déplié en Planning, replié sur une ligne au-dessus des
     *  grilles). */
    var decideOpen by mutableStateOf<Boolean?>(null)
        private set
    var refreshing by mutableStateOf(false)
        private set
    /** Un geste en cours : les autres attendent. */
    var acting by mutableStateOf(false)
        private set

    val off get() = deps.prefs.off

    private var started = false
    private var periodJob: Job? = null
    private var miniJob: Job? = null
    private var generation = 0

    private fun say(text: String) {
        if (text.isNotBlank()) notices.trySend(text)
    }

    /** Ses agendas, chacun sous le nom qu'on lui montre. */
    val list: List<AgendaCalendar> get() = withShownNames(calendars.valueOrNull?.calendars.orEmpty())

    val zone: String get() = calendars.valueOrNull?.zone?.ifBlank { null } ?: "UTC"

    /** Aujourd'hui et la minute de maintenant, à l'heure du serveur. */
    fun now(ms: Long = deps.now()): Pair<String, Int> = localOf(ms, zone).let { it.day to it.minute }

    val today: String get() = now().first

    val shownDate: String get() = date.ifEmpty { today }

    // ── lire ──

    fun resume() {
        if (!started) {
            started = true
            load(quiet = false)
        } else {
            load(quiet = true)
        }
    }

    /** Le direct : l'agenda a changé — tout ce que l'écran montre se relit, sans bruit. */
    suspend fun onLive(signal: LiveSignal) {
        if (started && signal.touches(Topics.AGENDA)) load(quiet = true).join()
    }

    fun pull() {
        refreshing = true
        viewModelScope.launch {
            load(quiet = false).join()
            refreshing = false
        }
    }

    fun retry() {
        calendars = Load.Loading
        load(quiet = false)
    }

    private fun load(quiet: Boolean): Job = viewModelScope.launch {
        val cals = async { api.calendars() }
        val inv = async { api.invitations() }
        val props = async { api.proposals() }
        val acc = async { api.accounts() }
        when (val got = cals.await()) {
            is MoiApi.Result.Ok -> calendars = Load.Ready(got.value)
            is MoiApi.Result.Failed -> if (calendars is Load.Ready) {
                if (!quiet) say(got.error.said)
            } else {
                calendars = Load.Failed(got.error)
            }
        }
        (inv.await() as? MoiApi.Result.Ok)?.let { invitations = it.value.items }
        (props.await() as? MoiApi.Result.Ok)?.let { proposals = it.value.items }
        (acc.await() as? MoiApi.Result.Ok)?.let { accounts = it.value }
        if (calendars is Load.Ready) {
            readPeriod(quiet).join()
            if (mini != null) readMini()
        }
    }

    /** La période que la vue montre, sur les agendas qu'on lit ; une lecture dépassée ne pose rien. */
    private fun readPeriod(quiet: Boolean): Job {
        periodJob?.cancel()
        val gen = ++generation
        val (first, after) = bounds(view, shownDate)
        val keys = readKeys(list)
        if (!quiet && period !is Load.Ready) period = Load.Loading
        return viewModelScope.launch {
            val got = api.period(first, addDays(after, -1), keys)
            if (gen != generation) return@launch
            when (got) {
                is MoiApi.Result.Ok -> period = Load.Ready(got.value)
                is MoiApi.Result.Failed -> if (period is Load.Ready) {
                    if (!quiet) say(got.error.said)
                } else {
                    period = Load.Failed(got.error)
                }
            }
        }.also { periodJob = it }
    }

    /** Le mois déplié : ses six semaines (un point sous les jours qui ont quelque chose). */
    private fun readMini() {
        val m = mini ?: return
        miniJob?.cancel()
        val days = monthDays(m)
        miniJob = viewModelScope.launch {
            (api.period(days.first(), days.last(), readKeys(list)) as? MoiApi.Result.Ok)?.let { if (mini == m) miniPeriod = it.value }
        }
    }

    // ── ce que la vue montre ──

    /** Un agenda s'affiche-t-il ici (ni décoché, ni masqué dans Paramètres) ? */
    fun shown(key: String, off: Set<String>): Boolean = shownHere(key, list, off)

    fun occs(off: Set<String>): List<Occ> = period.valueOrNull?.let { periodOccs(it, zone) { k -> shown(k, off) } }.orEmpty()

    fun miniOccs(off: Set<String>): List<Occ> = miniPeriod?.let { periodOccs(it, zone) { k -> shown(k, off) } }.orEmpty()

    /** Ce que Mika propose d'ajouter et dont tu décides. */
    val adds: List<Proposal> get() = pendingAdds(proposals)

    /** « À décider » déplié : ce qu'on a choisi, sinon en Planning seulement. */
    val decideUnfolded: Boolean get() = decideOpen ?: (view == AgendaView.PLANNING)

    fun toggleDecide() {
        decideOpen = !decideUnfolded
    }

    // ── se déplacer ──

    fun choose(v: AgendaView) {
        if (v == view) return
        view = v
        deps.prefs.setView(v)
        readPeriod(quiet = false)
    }

    /** Balayer, « Les quatre semaines suivantes » : un pas plus loin ou plus tôt. */
    fun move(by: Int) {
        date = step(view, shownDate, by, today)
        readPeriod(quiet = false)
    }

    fun goToday() {
        date = today
        mini = null
        readPeriod(quiet = false)
    }

    /** Un jour touché dans le mini-mois : la vue y va, le mois se replie. */
    fun pick(day: String) {
        date = day
        mini = null
        readPeriod(quiet = false)
    }

    /** Un jour touché dans le Mois ou une tête de colonne : la vue Jour de ce jour. */
    fun openDay(day: String) {
        date = day
        if (view != AgendaView.DAY) {
            view = AgendaView.DAY
            deps.prefs.setView(AgendaView.DAY)
        }
        readPeriod(quiet = false)
    }

    fun toggleMini() {
        if (mini != null) {
            mini = null
        } else {
            mini = monthStart(shownDate)
            miniPeriod = null
            readMini()
        }
    }

    fun miniMove(by: Int) {
        val m = mini ?: return
        mini = addMonths(m, by)
        miniPeriod = null
        readMini()
    }

    // ── cocher, régler ──

    fun setShown(key: String, on: Boolean) = deps.prefs.setShown(key, on)

    fun showOnly(key: String) = deps.prefs.showOnly(key, list.map { it.key } + AgendaKinds.MIKA)

    fun setColor(key: String, color: String) = act { api.saveCalendar(key, mapOf("color" to color)) }

    // ── décider ──

    /** Ajouter ce que Mika propose, tel qu'il a été lu (l'empreinte de son aperçu). */
    fun accept(p: Proposal) = act(badges = true) { api.accept(p.id, p.preview?.digest.orEmpty()) }

    fun refuse(p: Proposal) = act(badges = true) { api.refuse(p.id) }

    private fun act(badges: Boolean = false, call: suspend () -> MoiApi.Result<fr.qwartz.mika.data.moi.agenda.AgendaDone>) {
        if (acting) return
        acting = true
        viewModelScope.launch {
            when (val got = call()) {
                is MoiApi.Result.Ok -> say(got.value.message)
                is MoiApi.Result.Failed -> say(got.error.said)
            }
            acting = false
            if (badges) deps.refreshBadges()
            load(quiet = true)
        }
    }
}
