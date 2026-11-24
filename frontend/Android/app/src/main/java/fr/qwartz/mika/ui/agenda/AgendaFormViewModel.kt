package fr.qwartz.mika.ui.agenda

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.SendKey
import fr.qwartz.mika.data.moi.agenda.AgendaCalendar
import fr.qwartz.mika.data.moi.agenda.AgendaDone
import fr.qwartz.mika.data.moi.agenda.AgendaItem
import fr.qwartz.mika.data.moi.agenda.Alert
import fr.qwartz.mika.data.moi.agenda.FormModes
import fr.qwartz.mika.data.moi.agenda.FormValues
import fr.qwartz.mika.data.moi.agenda.Guest
import fr.qwartz.mika.data.moi.agenda.Occ
import fr.qwartz.mika.data.moi.agenda.Proposal
import fr.qwartz.mika.data.moi.agenda.defaultCalendar
import fr.qwartz.mika.data.moi.agenda.fieldsOf
import fr.qwartz.mika.data.moi.agenda.fitAlerts
import fr.qwartz.mika.data.moi.agenda.formProblem
import fr.qwartz.mika.data.moi.agenda.initialValues
import fr.qwartz.mika.data.moi.agenda.localOf
import fr.qwartz.mika.data.moi.agenda.occOfItem
import fr.qwartz.mika.data.moi.agenda.occOfProposal
import fr.qwartz.mika.data.moi.agenda.withShownNames
import fr.qwartz.mika.data.moi.agenda.writableCalendars
import fr.qwartz.mika.data.moi.contacts.RecipientProposal
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

/** Le formulaire est prêt : ses agendas, ce qu'il écrit (ses valeurs de départ), et ce qu'il modifie. */
data class FormReady(val calendars: List<AgendaCalendar>, val start: FormValues, val item: AgendaItem? = null, val proposal: Proposal? = null, val zone: String = "UTC")

/**
 * Créer et modifier un événement (`Route.AgendaForm`, la maquette validée `agenda-edition.js`) : ses valeurs, lues une
 * fois à l'ouverture — un formulaire ne se relit jamais sous ta saisie —, les participants proposés (tes contacts, comme
 * dans Mail), et l'enregistrement : tout pour une création, seulement ce qui a changé pour une modification, la portée
 * d'une série demandée d'abord ; une clé d'envoi par contenu (un double appui ne crée qu'une fois). Fini, l'écran va à
 * la fiche de ce qu'il a écrit ([done]).
 */
class AgendaFormViewModel(
    private val deps: AgendaDeps,
    private val lookup: suspend (String, Set<String>) -> List<RecipientProposal> = { _, _ -> emptyList() },
) : ViewModel() {
    private val api = deps.api
    private val notices = Channel<String>(Channel.BUFFERED)
    private val finished = Channel<Route?>(Channel.CONFLATED)

    val said: Flow<String> = notices.receiveAsFlow()
    /** Enregistré : la route où aller (la fiche écrite), ou `null` : revenir. */
    val done: Flow<Route?> = finished.receiveAsFlow()

    var ready by mutableStateOf<Load<FormReady>>(Load.Loading)
        private set
    var values by mutableStateOf(FormValues())
        private set
    var saving by mutableStateOf(false)
        private set
    /** Une série : la portée est à demander avant d'enregistrer. */
    var askScope by mutableStateOf(false)
        private set
    /** Ce qui ne peut pas partir tel quel (la fin avant le début), sous les dates. */
    var problem by mutableStateOf<String?>(null)
        private set

    var typed by mutableStateOf("")
        private set
    var suggestions by mutableStateOf<List<RecipientProposal>>(emptyList())
        private set
    private var suggestJob: Job? = null

    private var route: Route.AgendaForm? = null
    private val sendKey = SendKey()

    val mode: String get() = route?.mode ?: FormModes.NEW

    fun open(r: Route.AgendaForm) {
        if (route == r && ready !is Load.Failed) return
        route = r
        ready = Load.Loading
        viewModelScope.launch {
            val cals = async { api.calendars() }
            val ev = if (r.mode == FormModes.EDIT || r.mode == FormModes.COPY) async { api.event(r.event, r.occurrence) } else null
            val props = if (r.mode == FormModes.PROPOSAL) async { api.proposals() } else null
            val c = cals.await()
            if (c is MoiApi.Result.Failed) {
                ready = Load.Failed(c.error)
                return@launch
            }
            val got = (c as MoiApi.Result.Ok).value
            val list = withShownNames(got.calendars)
            val zone = got.zone.ifBlank { "UTC" }
            val now = localOf(deps.now(), zone)
            var item: AgendaItem? = null
            var proposal: Proposal? = null
            var o: Occ? = null
            when (val e = ev?.await()) {
                null -> Unit
                is MoiApi.Result.Ok -> {
                    item = e.value
                    o = occOfItem(e.value, zone)
                }
                is MoiApi.Result.Failed -> {
                    ready = Load.Failed(e.error)
                    return@launch
                }
            }
            when (val p = props?.await()) {
                null -> Unit
                is MoiApi.Result.Ok -> {
                    proposal = p.value.items.firstOrNull { it.id == r.proposal }
                    o = proposal?.let { occOfProposal(it, zone) }
                    if (o == null) {
                        ready = Load.Failed(MoiError(404, GONE_PROPOSAL))
                        return@launch
                    }
                }
                is MoiApi.Result.Failed -> {
                    ready = Load.Failed(p.error)
                    return@launch
                }
            }
            val writable = writableCalendars(list)
            if (r.mode != FormModes.EDIT && writable.isEmpty()) {
                ready = Load.Failed(MoiError(409, NOWHERE))
                return@launch
            }
            val from = item?.calendar ?: proposal?.calendar.orEmpty()
            val calendar = when {
                r.mode == FormModes.NEW -> defaultCalendar(list)
                r.mode == FormModes.EDIT -> from
                writable.any { it.key == from } -> from
                else -> defaultCalendar(list)
            }
            val start = initialValues(r.mode, calendar, zone, now.day, now.minute, list, o, r.day, r.minute)
            values = start
            ready = Load.Ready(FormReady(list, start, item, proposal, zone))
        }
    }

    fun retry() {
        route?.let { r ->
            route = null
            open(r)
        }
    }

    /** Une valeur changée (ce que l'écran a fait des champs). */
    fun edit(change: (FormValues) -> FormValues) {
        values = change(values)
        problem = null
    }

    /** Un autre agenda : ses rappels du fournisseur de départ, si on ne les a pas touchés ; sinon ceux qu'on a mis,
     *  ramenés à ce qu'il sait porter (aucun dans l'agenda du système : rien d'invisible ne part). */
    fun chooseCalendar(key: String) {
        val cal = ready.valueOrNull?.calendars?.firstOrNull { it.key == key } ?: return
        val can = cal.providerReminders
        values = if (!values.remindersTouched) values.copy(calendar = key, reminders = can.defaults)
        else values.copy(calendar = key, reminders = fitAlerts(values.reminders, can), remindersTouched = can.max > 0)
    }

    fun addAlert(a: Alert) {
        values = values.copy(reminders = values.reminders + a, remindersTouched = true)
    }

    fun removeAlert(index: Int) {
        values = values.copy(reminders = values.reminders.filterIndexed { i, _ -> i != index }, remindersTouched = true)
    }

    // ── les participants ──

    fun type(text: String) {
        typed = text
        suggestJob?.cancel()
        if (text.isBlank()) {
            suggestions = emptyList()
            return
        }
        suggestJob = viewModelScope.launch {
            delay(SUGGEST_MS)
            suggestions = lookup(text, values.invite.map { it.address.lowercase() }.toSet())
        }
    }

    fun pick(p: RecipientProposal) {
        if (values.invite.none { it.address.equals(p.address, ignoreCase = true) }) values = values.copy(invite = values.invite + Guest(p.name, p.address))
        typed = ""
        suggestions = emptyList()
    }

    /** Ce qui est tapé et qui a l'air d'une adresse : pris tel quel. */
    fun takeTyped(): Boolean {
        val t = typed.trim().trimEnd(',', ';')
        if (!Regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$").matches(t)) return false
        pick(RecipientProposal("", t))
        return true
    }

    fun removeGuest(address: String) {
        values = values.copy(invite = values.invite.filter { it.address != address })
    }

    // ── enregistrer ──

    /** Enregistrer ; une modification d'une occurrence d'une série demande d'abord sa portée ([scope]). */
    fun save(scope: String? = null) {
        val r = route ?: return
        val f = ready.valueOrNull ?: return
        if (saving) return
        formProblem(values)?.let {
            problem = it
            return
        }
        val owner = f.calendars.firstOrNull { it.key == values.calendar }?.owned == true
        val fields = fieldsOf(r.mode, values, f.start, owner)
        if (r.mode == FormModes.EDIT) {
            val item = f.item ?: return
            if (fields.empty) {
                notices.trySend(NOTHING_CHANGED)
                finished.trySend(null)
                return
            }
            if (item.recurring && item.occurrence.isNotEmpty() && scope == null) {
                askScope = true
                return
            }
        }
        askScope = false
        val key = sendKey.of(listOf(r, values, scope))
        saving = true
        viewModelScope.launch {
            val got: MoiApi.Result<AgendaDone> = when (r.mode) {
                FormModes.EDIT -> api.edit(f.item!!.event, f.item.occurrence, scope ?: "un", fields, key)
                FormModes.PROPOSAL -> api.editProposal(f.proposal!!.id, values.calendar, fields, key)
                else -> api.create(values.calendar, fields, key)
            }
            saving = false
            when (got) {
                is MoiApi.Result.Ok -> {
                    sendKey.settled(networkFailure = false)
                    notices.trySend(got.value.message)
                    deps.refreshBadges()
                    val made = got.value.made?.event?.takeIf { it > 0 }
                    finished.trySend(made?.let { Route.AgendaEvent(it, "") })
                }
                is MoiApi.Result.Failed -> {
                    sendKey.settled(got.error.network)
                    notices.trySend(got.error.said)
                }
            }
        }
    }

    fun dropScope() {
        askScope = false
    }

    private companion object {
        const val SUGGEST_MS = 300L
        const val NOTHING_CHANGED = "Rien n'a changé."
        const val NOWHERE = "Aucun de tes agendas ne s'écrit d'ici : branche-en un dans Paramètres › Agendas."
        const val GONE_PROPOSAL = "Cette proposition n'attend plus : elle a été décidée, ou sa date est passée."
    }
}
