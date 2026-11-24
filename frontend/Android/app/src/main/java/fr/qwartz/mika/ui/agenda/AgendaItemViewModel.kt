package fr.qwartz.mika.ui.agenda

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.agenda.AgendaCalendar
import fr.qwartz.mika.data.moi.agenda.AgendaDone
import fr.qwartz.mika.data.moi.agenda.AgendaItem
import fr.qwartz.mika.data.moi.agenda.AgendaLive
import fr.qwartz.mika.data.moi.agenda.Proposal
import fr.qwartz.mika.data.moi.agenda.localOf
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
 * La fiche d'un événement (`Route.AgendaEvent`) ou de ce que Mika propose (`Route.AgendaProposal`) : relue à chaque retour
 * sur l'écran et quand le direct nomme son agenda ; ses gestes — répondre (et la réponse qu'elle a préparée), « Mika te
 * le rappelle », supprimer, décider de ce qu'elle propose —, un à la fois, son sort en toast. Ce qui le fait quitter
 * l'écran (supprimé, décidé) le dit ([gone]).
 */
class AgendaItemViewModel(private val deps: AgendaDeps) : ViewModel() {
    private val api = deps.api
    private val notices = Channel<String>(Channel.BUFFERED)
    private val leaving = Channel<Unit>(Channel.CONFLATED)

    val said: Flow<String> = notices.receiveAsFlow()
    /** L'écran revient en arrière : ce qu'il montrait n'est plus (supprimé, décidé). */
    val gone: Flow<Unit> = leaving.receiveAsFlow()

    var calendars by mutableStateOf<List<AgendaCalendar>>(emptyList())
        private set
    var zone by mutableStateOf("UTC")
        private set
    var item by mutableStateOf<Load<AgendaItem>>(Load.Loading)
        private set
    var proposal by mutableStateOf<Load<Proposal>>(Load.Loading)
        private set
    var acting by mutableStateOf(false)
        private set

    private var event = 0
    private var occurrence = ""
    private var proposalId = 0
    private var started = false
    private var job: Job? = null

    fun now(ms: Long = deps.now()): Pair<String, Int> = localOf(ms, zone).let { it.day to it.minute }

    /** Ouvrir l'événement [event] (son occurrence), ou la proposition [proposal]. */
    fun open(event: Int, occurrence: String, proposal: Int) {
        if (started && event == this.event && occurrence == this.occurrence && proposal == proposalId) return
        this.event = event
        this.occurrence = occurrence
        proposalId = proposal
        started = false
    }

    fun resume() {
        val quiet = started
        started = true
        load(quiet)
    }

    suspend fun onLive(signal: LiveSignal) {
        if (!started || !signal.touches(Topics.AGENDA)) return
        val cal = item.valueOrNull?.calendar ?: proposal.valueOrNull?.calendar
        if (cal == null || AgendaLive.eventShows(cal, signal) || proposalId > 0) load(quiet = true).join()
    }

    fun retry() = load(quiet = false)

    private fun load(quiet: Boolean): Job {
        job?.cancel()
        return viewModelScope.launch {
            val cals = async { api.calendars() }
            if (proposalId > 0) {
                val got = api.proposals()
                (cals.await() as? MoiApi.Result.Ok)?.let {
                    calendars = withShownNames(it.value.calendars)
                    zone = it.value.zone.ifBlank { "UTC" }
                }
                when (got) {
                    is MoiApi.Result.Ok -> {
                        val p = got.value.items.firstOrNull { it.id == proposalId }
                        proposal = if (p != null) Load.Ready(p) else Load.Failed(MoiError(404, GONE_PROPOSAL))
                    }
                    is MoiApi.Result.Failed -> if (proposal is Load.Ready) {
                        if (!quiet) notices.trySend(got.error.said)
                    } else {
                        proposal = Load.Failed(got.error)
                    }
                }
            } else {
                val got = api.event(event, occurrence)
                (cals.await() as? MoiApi.Result.Ok)?.let {
                    calendars = withShownNames(it.value.calendars)
                    zone = it.value.zone.ifBlank { "UTC" }
                }
                when (got) {
                    is MoiApi.Result.Ok -> item = Load.Ready(got.value)
                    is MoiApi.Result.Failed -> when {
                        got.error.gone -> item = Load.Failed(MoiError(404, GONE_EVENT))
                        item is Load.Ready -> if (!quiet) notices.trySend(got.error.said)
                        else -> item = Load.Failed(got.error)
                    }
                }
            }
        }.also { job = it }
    }

    val calendar: AgendaCalendar?
        get() = (item.valueOrNull?.calendar ?: proposal.valueOrNull?.calendar)?.let { k -> calendars.firstOrNull { it.key == k } }

    // ── les gestes ──

    /** Répondre soi-même (la série entière) ; ce que Mika avait préparé tombe. */
    fun respond(answer: String, comment: String = "") {
        val i = item.valueOrNull ?: return
        act(badges = true) { api.respond(i.event, i.occurrence, answer, comment, "tous") }
    }

    /** « Envoyer sa réponse » : la réponse préparée, telle qu'elle a été lue (son empreinte). */
    fun sendPrepared(p: Proposal) = act(badges = true) { api.accept(p.id, p.preview?.digest.orEmpty()) }

    /** « Non merci » : elle n'enverra pas sa réponse. */
    fun dropPrepared(p: Proposal) = act(badges = true) { api.refuse(p.id) }

    fun remind(value: String) {
        val i = item.valueOrNull ?: return
        act { api.remind(i.event, value) }
    }

    /** Supprimer (une série : [scope]) ; une invitation, c'est la refuser. */
    fun delete(scope: String) {
        val i = item.valueOrNull ?: return
        act(badges = true, leave = true) { api.delete(i.event, i.occurrence, scope) }
    }

    /** Ajouter ce que Mika propose, tel qu'il a été lu. */
    fun accept() {
        val p = proposal.valueOrNull ?: return
        act(badges = true, leave = true) { api.accept(p.id, p.preview?.digest.orEmpty()) }
    }

    fun refuse() {
        val p = proposal.valueOrNull ?: return
        act(badges = true, leave = true) { api.refuse(p.id) }
    }

    private fun act(badges: Boolean = false, leave: Boolean = false, call: suspend () -> MoiApi.Result<AgendaDone>) {
        if (acting) return
        acting = true
        viewModelScope.launch {
            val got = call()
            acting = false
            when (got) {
                is MoiApi.Result.Ok -> {
                    notices.trySend(got.value.message)
                    if (badges) deps.refreshBadges()
                    if (leave) leaving.trySend(Unit) else load(quiet = true)
                }
                is MoiApi.Result.Failed -> {
                    notices.trySend(got.error.said)
                    // décidée ailleurs, disparue : l'écran se relit pour le dire
                    load(quiet = true)
                }
            }
        }
    }

    private companion object {
        const val GONE_EVENT = "Cet événement n'est plus là : supprimé, ou plus à toi."
        const val GONE_PROPOSAL = "Cette proposition n'attend plus : elle a été décidée, ou sa date est passée."
    }
}
