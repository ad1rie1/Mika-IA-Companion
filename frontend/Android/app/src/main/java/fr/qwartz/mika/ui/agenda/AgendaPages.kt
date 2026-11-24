package fr.qwartz.mika.ui.agenda

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.agenda.ANSWERS
import fr.qwartz.mika.data.moi.agenda.AgendaCalendar
import fr.qwartz.mika.data.moi.agenda.AgendaDone
import fr.qwartz.mika.data.moi.agenda.AgendaItem
import fr.qwartz.mika.data.moi.agenda.AnswerNote
import fr.qwartz.mika.data.moi.agenda.MC
import fr.qwartz.mika.data.moi.agenda.Occ
import fr.qwartz.mika.data.moi.agenda.Proposal
import fr.qwartz.mika.data.moi.agenda.answerNote
import fr.qwartz.mika.data.moi.agenda.colorOf
import fr.qwartz.mika.data.moi.agenda.dayNumber
import fr.qwartz.mika.data.moi.agenda.inviter
import fr.qwartz.mika.data.moi.agenda.localOf
import fr.qwartz.mika.data.moi.agenda.occOfHer
import fr.qwartz.mika.data.moi.agenda.occOfItem
import fr.qwartz.mika.data.moi.agenda.partsOf
import fr.qwartz.mika.data.moi.agenda.preparedWords
import fr.qwartz.mika.data.moi.agenda.readKeys
import fr.qwartz.mika.data.moi.agenda.sortOccs
import fr.qwartz.mika.data.moi.agenda.whenWords
import fr.qwartz.mika.data.moi.agenda.withShownNames
import fr.qwartz.mika.data.net.Topics
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.FollowLive
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MikaFace
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.Notice
import fr.qwartz.mika.ui.shell.PersonAvatar
import fr.qwartz.mika.ui.shell.SearchBar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.shell.said
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

/*
 * Deux pages de l'Agenda (la maquette validée `agenda.js`) : les invitations qui attendent ta réponse — chacune avec la
 * réponse que Mika a préparée et tes trois boutons —, et chercher dans tes agendas.
 */

// ── Les invitations ─────────────────────────────────────────────────────

class InvitationsViewModel(private val deps: AgendaDeps) : ViewModel() {
    private val notices = Channel<String>(Channel.BUFFERED)
    val said: Flow<String> = notices.receiveAsFlow()

    var items by mutableStateOf<Load<List<AgendaItem>>>(Load.Loading)
        private set
    var calendars by mutableStateOf<List<AgendaCalendar>>(emptyList())
        private set
    var zone by mutableStateOf("UTC")
        private set
    var acting by mutableStateOf(false)
        private set
    var refreshing by mutableStateOf(false)
        private set
    private var started = false

    fun resume() {
        val quiet = started
        started = true
        load(quiet)
    }

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

    fun retry() = load(quiet = false)

    private fun load(quiet: Boolean): Job = viewModelScope.launch {
        val cals = async { deps.api.calendars() }
        val got = deps.api.invitations()
        (cals.await() as? MoiApi.Result.Ok)?.let {
            calendars = withShownNames(it.value.calendars)
            zone = it.value.zone.ifBlank { "UTC" }
        }
        when (got) {
            is MoiApi.Result.Ok -> items = Load.Ready(got.value.items)
            is MoiApi.Result.Failed -> if (items is Load.Ready) {
                if (!quiet) notices.trySend(got.error.said)
            } else {
                items = Load.Failed(got.error)
            }
        }
    }

    fun respond(i: AgendaItem, answer: String) = act { deps.api.respond(i.event, i.occurrence, answer, "", "tous") }

    fun send(p: Proposal) = act { deps.api.accept(p.id, p.preview?.digest.orEmpty()) }

    fun drop(p: Proposal) = act { deps.api.refuse(p.id) }

    private fun act(call: suspend () -> MoiApi.Result<AgendaDone>) {
        if (acting) return
        acting = true
        viewModelScope.launch {
            when (val got = call()) {
                is MoiApi.Result.Ok -> notices.trySend(got.value.message)
                is MoiApi.Result.Failed -> notices.trySend(got.error.said)
            }
            acting = false
            deps.refreshBadges()
            load(quiet = true)
        }
    }
}

/** Les invitations : une carte chacune (quand, où, de qui, la réponse que Mika a préparée), puis tes trois boutons. */
@Composable
fun AgendaInvitationsScreen(graph: AppGraph) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: InvitationsViewModel = viewModel(key = "agenda.invitations|$session") { InvitationsViewModel(AgendaDeps(graph)) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    FollowLive(graph.live, AGENDA_TOPICS, vm, onShown = { vm.resume() }) { vm.onLive(it) }
    val wall = rememberNow(wallMs = graph.clock::wallMs)
    val n = vm.items.valueOrNull?.size ?: 0
    SectionScaffold(
        topBar = {
            MikaTopBar(
                title = stringResource(R.string.agenda_invitations),
                nav = BarNav.BACK,
                subtitle = if (vm.items is Load.Ready) {
                    if (n > 0) pluralStringResource(R.plurals.agenda_invitations_waiting, n, n) else stringResource(R.string.agenda_invitations_none_waiting)
                } else {
                    null
                },
                face = false,
            )
        },
    ) { modifier ->
        PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::pull, modifier = modifier) {
            LoadBox(vm.items, onRetry = vm::retry) { list ->
                val today = localOf(wall, vm.zone).day
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    if (list.isEmpty()) {
                        item(key = "vide") { Notice(stringResource(R.string.agenda_invitations_empty), Modifier.padding(top = 24.dp)) }
                    }
                    items(list, key = { "${it.event}:${it.occurrence}" }) { i ->
                        InvitationCard(i, vm.calendars, vm.zone, today, vm.acting, onOpen = { shell.navigate(Route.AgendaEvent(i.event, i.occurrence)) }, vm)
                    }
                    item(key = "note") {
                        Text(
                            stringResource(R.string.agenda_invitations_note),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun InvitationCard(i: AgendaItem, calendars: List<AgendaCalendar>, zone: String, today: String, acting: Boolean, onOpen: () -> Unit, vm: InvitationsViewModel) {
    val o = occOfItem(i, zone)
    val cal = calendars.firstOrNull { it.key == i.calendar }
    val who = inviter(i)
    Surface(shape = RoundedCornerShape(18.dp), color = MaterialTheme.colorScheme.surfaceContainerLow, modifier = Modifier.fillMaxWidth()) {
        Column {
            Row(Modifier.fillMaxWidth().clickable(onClick = onOpen).padding(14.dp), verticalAlignment = Alignment.Top) {
                Swatch(colorOf(cal), 18.dp, Modifier.padding(top = 3.dp))
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(o.title, style = MaterialTheme.typography.titleMedium)
                    Text(
                        whenWords(o, today) + (i.location.substringBefore(" · ").takeIf { it.isNotBlank() }?.let { " · $it" } ?: ""),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    val calName = i.calendarName.ifBlank { cal?.name.orEmpty() }
                    if (calName.isNotBlank()) Text(stringResource(R.string.agenda_in_calendar, calName), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                MIcon(R.drawable.ic_m_chev_right, null, size = 18.dp)
            }
            if (who.isNotBlank()) {
                Row(Modifier.padding(horizontal = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                    PersonAvatar(who, i.organizer?.address.orEmpty(), 32.dp)
                    Spacer(Modifier.width(10.dp))
                    Text(stringResource(R.string.agenda_invites_you, who), style = MaterialTheme.typography.titleSmall)
                }
            }
            val p = i.prepared?.takeIf { it.decides }
            if (p != null) {
                PinkBox(Modifier.padding(12.dp)) {
                    Row(verticalAlignment = Alignment.Top) {
                        MikaFace(32.dp)
                        Spacer(Modifier.width(10.dp))
                        Column {
                            Text(stringResource(R.string.agenda_prepared_title), style = MaterialTheme.typography.labelLarge, color = mika.accent)
                            Text(preparedWords(p), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 4.dp))
                            if (p.why.isNotBlank()) Text(p.why, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Button(onClick = { vm.send(p) }, enabled = !acting && p.preview?.blocked.isNullOrBlank(), modifier = Modifier.padding(top = 8.dp)) {
                                MIcon(R.drawable.ic_m_send, null, size = 18.dp)
                                Spacer(Modifier.width(8.dp))
                                Text(stringResource(R.string.agenda_send_hers))
                            }
                            Row {
                                TextButton(onClick = onOpen) { Text(stringResource(R.string.agenda_edit_word)) }
                                TextButton(onClick = { vm.drop(p) }, enabled = !acting) { Text(stringResource(R.string.agenda_no_thanks)) }
                            }
                        }
                    }
                }
            }
            if (i.can.respond) {
                Row(Modifier.fillMaxWidth().padding(12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    for ((k, label) in ANSWERS) {
                        AnswerButton(k, label, on = i.response == k, enabled = !acting, modifier = Modifier.weight(1f)) { vm.respond(i, k) }
                    }
                }
            }
            when (answerNote(i)) {
                AnswerNote.SERIES -> Text(stringResource(R.string.agenda_answer_series), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(start = 12.dp, end = 12.dp, bottom = 12.dp))
                AnswerNote.WHY -> Text(i.respondWhy, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(12.dp))
                AnswerNote.NONE -> Unit
            }
        }
    }
}

// ── Chercher ────────────────────────────────────────────────────────────

/** Chercher dans tes agendas : un titre, un lieu, une description, un participant (le serveur cherche, sur la fenêtre
 *  de la synchro), à partir de deux lettres et après une pause de frappe. */
class AgendaSearchViewModel(private val deps: AgendaDeps) : ViewModel() {
    var query by mutableStateOf("")
        private set
    var found by mutableStateOf<Load<List<Occ>>?>(null)
        private set
    var more by mutableStateOf(false)
        private set
    var calendars by mutableStateOf<List<AgendaCalendar>>(emptyList())
        private set
    var zone by mutableStateOf("UTC")
        private set
    /** Aucun agenda coché : on ne cherche nulle part (une liste vide, pour le serveur, voudrait dire « partout »). */
    var unchecked by mutableStateOf(false)
        private set
    private var job: Job? = null

    fun type(text: String) {
        query = text.take(120)
        job?.cancel()
        unchecked = false
        if (query.trim().length < 2) {
            found = null
            return
        }
        job = viewModelScope.launch {
            delay(SEARCH_MS)
            if (calendars.isEmpty()) {
                (deps.api.calendars() as? MoiApi.Result.Ok)?.let {
                    calendars = withShownNames(it.value.calendars)
                    zone = it.value.zone.ifBlank { "UTC" }
                }
            }
            val off = deps.prefs.off.value
            val keys = readKeys(calendars).filter { it !in off }
            if (keys.isEmpty()) {
                unchecked = true
                found = Load.Ready(emptyList())
                more = false
                return@launch
            }
            if (found !is Load.Ready) found = Load.Loading
            when (val got = deps.api.search(query, keys)) {
                is MoiApi.Result.Ok -> {
                    found = Load.Ready(sortOccs(got.value.items.map { occOfItem(it, zone) } + got.value.her.map { occOfHer(it, zone) }))
                    more = got.value.more
                }
                is MoiApi.Result.Failed -> found = Load.Failed(got.error)
            }
        }
    }

    private companion object {
        const val SEARCH_MS = 300L
    }
}

@Composable
fun AgendaSearchScreen(graph: AppGraph) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: AgendaSearchViewModel = viewModel(key = "agenda.search|$session") { AgendaSearchViewModel(AgendaDeps(graph)) }
    val wall = rememberNow(wallMs = graph.clock::wallMs)
    val words = rememberTagWords()
    SectionScaffold(topBar = { SearchBar(vm.query, stringResource(R.string.agenda_search_hint), vm::type, onClose = shell.back) }) { modifier ->
        val now = localOf(wall, vm.zone)
        when (val f = vm.found) {
            null -> Notice(stringResource(R.string.agenda_search_lede), modifier)
            else -> LoadBox(f, onRetry = { vm.type(vm.query) }, modifier = modifier) { list ->
                if (vm.unchecked) {
                    Notice(stringResource(R.string.agenda_search_unchecked), modifier)
                } else if (list.isEmpty()) {
                    Notice(stringResource(R.string.agenda_search_none, vm.query), modifier)
                } else {
                    LazyColumn(modifier, contentPadding = PaddingValues(bottom = 24.dp)) {
                        item(key = "tete") {
                            Text(
                                pluralStringResource(R.plurals.agenda_search_results, list.size, list.size) + if (vm.more) " · " + stringResource(R.string.agenda_search_more) else "",
                                style = MaterialTheme.typography.labelLarge,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
                            )
                        }
                        items(list, key = { it.key }) { o ->
                            Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                                Column(Modifier.width(48.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                    Text(dayNumber(o.day).removeSuffix("er"), style = MaterialTheme.typography.titleMedium)
                                    val p = partsOf(o.day)
                                    Text(MC[p.m - 1] + if (p.y != partsOf(now.day).y) " ${p.y}" else "", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                                Column(Modifier.weight(1f)) {
                                    OccCard(o, vm.calendars, now.day, now.minute, words) { routeOf(o)?.let(shell.navigate) }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
