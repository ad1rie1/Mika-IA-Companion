package fr.qwartz.mika.ui.agenda

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.agenda.AgendaCalendar
import fr.qwartz.mika.data.moi.agenda.AgendaDone
import fr.qwartz.mika.data.moi.agenda.AgendaRights
import fr.qwartz.mika.data.moi.agenda.RightsColumns
import fr.qwartz.mika.data.moi.agenda.RightsPills
import fr.qwartz.mika.data.moi.agenda.colorOf
import fr.qwartz.mika.data.moi.agenda.levelWords
import fr.qwartz.mika.data.moi.agenda.providerShort
import fr.qwartz.mika.data.moi.agenda.rightsPills
import fr.qwartz.mika.data.moi.agenda.rightsRules
import fr.qwartz.mika.data.moi.agenda.rightsSummary
import fr.qwartz.mika.data.moi.agenda.ruleWho
import fr.qwartz.mika.data.moi.agenda.sharedPerson
import fr.qwartz.mika.data.moi.agenda.withShownNames
import fr.qwartz.mika.data.net.Topics
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.BarAction
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.FollowLive
import fr.qwartz.mika.ui.shell.ListHead
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MikaFace
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.PersonAvatar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

/*
 * Outils › Droits, chaque agenda à soi (la maquette validée `agenda-droits.js`) : sur un téléphone, une carte par ligne
 * du tableau plutôt qu'un tableau large — qui, par où, quand en tête ; dessous, ses quatre colonnes (Lire ; Ajouter,
 * modifier, supprimer ; Répondre aux invitations ; Ce qu'elle en garde), chacune réglée dans une feuille par son
 * propriétaire. La ligne d'un partage se retire avec lui. Ni « Ajouter une ligne » : qui, par où et quand se règlent dans
 * la console (l'API ne sert que les cases).
 */

/** Le tableau d'un agenda : le lire, régler une case, retirer un partage, revenir au tableau de départ. */
class CalendarRightsViewModel(private val deps: AgendaDeps) : ViewModel() {
    private val notices = Channel<String>(Channel.BUFFERED)
    val said: Flow<String> = notices.receiveAsFlow()

    var calendar by mutableStateOf<AgendaCalendar?>(null)
        private set
    var rights by mutableStateOf<Load<AgendaRights>>(Load.Loading)
        private set
    var acting by mutableStateOf(false)
        private set
    private var key = ""
    private var started = false

    fun open(calendar: String) {
        if (calendar == key) return
        key = calendar
        started = false
        rights = Load.Loading
    }

    fun resume() {
        val quiet = started
        started = true
        load(quiet)
    }

    suspend fun onLive(signal: LiveSignal) {
        if (started && signal.touches(Topics.AGENDA)) load(quiet = true).join()
    }

    fun retry() = load(quiet = false)

    private fun load(quiet: Boolean): Job = viewModelScope.launch {
        val cals = async { deps.api.calendars() }
        val got = deps.api.rights(key)
        (cals.await() as? MoiApi.Result.Ok)?.let { c -> calendar = withShownNames(c.value.calendars).firstOrNull { it.key == key } }
        when (got) {
            is MoiApi.Result.Ok -> rights = Load.Ready(got.value)
            is MoiApi.Result.Failed -> if (rights is Load.Ready) {
                if (!quiet) notices.trySend(got.error.said)
            } else {
                rights = Load.Failed(got.error)
            }
        }
    }

    /** Une case changée : le tableau entier repart (ses lignes, son défaut), puis se relit. */
    fun set(index: Int, col: String, value: String) {
        val t = rights.valueOrNull ?: return
        val lines = t.lines.mapIndexed { i, l -> if (i == index) RightsColumns.set(l, col, value) else l }
        act { deps.api.saveRights(key, lines, t.default) }
    }

    fun withdraw(person: String) = act { deps.api.share(key, person, "") }

    fun reset() = act { deps.api.resetRights(key) }

    private fun act(call: suspend () -> MoiApi.Result<AgendaDone>) {
        if (acting) return
        acting = true
        viewModelScope.launch {
            when (val got = call()) {
                is MoiApi.Result.Ok -> notices.trySend(got.value.message)
                is MoiApi.Result.Failed -> notices.trySend(got.error.said)
            }
            acting = false
            load(quiet = true)
        }
    }
}

@Composable
fun CalendarRightsScreen(graph: AppGraph, route: Route.CalendarRights) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: CalendarRightsViewModel = viewModel(key = "agenda.rights|$session|${route.calendar}") { CalendarRightsViewModel(AgendaDeps(graph)) }
    LaunchedEffect(vm, route) { vm.open(route.calendar) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    FollowLive(graph.live, AGENDA_TOPICS, vm, onShown = { vm.resume() }) { vm.onLive(it) }
    val me by graph.me.me.collectAsStateWithLifecycle()
    val person = me?.person.orEmpty()
    var cell by rememberSaveable { mutableStateOf("") }
    var withdraw by rememberSaveable { mutableStateOf("") }
    var share by rememberSaveable { mutableStateOf(false) }
    val cal = vm.calendar
    SectionScaffold(
        topBar = {
            MikaTopBar(
                title = stringResource(R.string.agenda_rights_title, cal?.name.orEmpty()),
                nav = BarNav.BACK,
                subtitle = cal?.let { "${providerShort(it)} · ${stringResource(R.string.agenda_whose_mine)}" },
                face = false,
                actions = {
                    BarAction(R.drawable.ic_m_agenda, stringResource(R.string.agenda_open), { shell.open(Route.Agenda) })
                    if (cal?.can?.share == true) BarAction(R.drawable.ic_m_user_plus, stringResource(R.string.agenda_share), { share = true })
                },
            )
        },
    ) { modifier ->
        LoadBox(vm.rights, onRetry = vm::retry, modifier = modifier) { t ->
            Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
                if (cal != null) {
                    PinkBox(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Swatch(colorOf(cal), 22.dp)
                            Spacer(Modifier.width(12.dp))
                            Text(rightsSummary(t, person, cal.shares, cal.writable).ifBlank { cal.name }, style = MaterialTheme.typography.titleSmall)
                        }
                    }
                    for (r in rightsRules(cal, t)) {
                        Text("• $r", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 24.dp, vertical = 1.dp))
                    }
                }
                t.lines.forEachIndexed { i, line ->
                    val shared = cal?.let { sharedPerson(it, line) }.orEmpty()
                    val level = cal?.shares?.firstOrNull { it.person == shared }?.level
                    Surface(shape = RoundedCornerShape(16.dp), color = MaterialTheme.colorScheme.surfaceContainerLow, modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp)) {
                        Column {
                            Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                                Text("${i + 1}", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.width(22.dp))
                                val who = ruleWho(line, person)
                                when {
                                    who == "Mika" -> MikaFace(32.dp)
                                    else -> PersonAvatar(if (who == "Toi") me?.shown.orEmpty() else who, line.who.firstOrNull().orEmpty(), 32.dp)
                                }
                                Spacer(Modifier.width(10.dp))
                                Column(Modifier.weight(1f)) {
                                    Row(verticalAlignment = Alignment.CenterVertically) {
                                        Text(who, style = MaterialTheme.typography.titleSmall)
                                        if (level != null) {
                                            Spacer(Modifier.width(6.dp))
                                            Tag(stringResource(R.string.agenda_rights_share_tag, levelWords(level).lowercase()), Tone.INFO)
                                        }
                                    }
                                    Text(
                                        listOf(line.words?.canal ?: line.canal.joinToString(", "), line.words?.moment ?: line.moment.joinToString(", ").ifEmpty { "toujours" })
                                            .filter { it.isNotBlank() }.joinToString(" · "),
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            }
                            for ((col, label, tools) in RightsColumns.ALL) {
                                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f))
                                val readOnly = cal != null && !cal.writable && (col == RightsColumns.WRITE || col == RightsColumns.RESPOND)
                                val value = RightsColumns.valueOf(line, col)
                                val editable = cal?.can?.rights == true && !readOnly
                                Row(
                                    Modifier.fillMaxWidth().then(if (editable) Modifier.clickable { cell = "$i|$col" } else Modifier).heightIn(min = 48.dp).padding(start = 46.dp, end = 14.dp, top = 8.dp, bottom = 8.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Column(Modifier.weight(1f)) {
                                        Text(label, style = MaterialTheme.typography.bodyMedium)
                                        if (tools.isNotEmpty()) Text(tools, style = MaterialTheme.typography.labelSmall, fontFamily = FontFamily.Monospace, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                    }
                                    if (readOnly) Tag("—", Tone.NEUTRAL) else Tag(RightsColumns.words(col, value), if (col == RightsColumns.KEEP) Tone.NEUTRAL else RightsColumns.tone(value))
                                    if (editable) {
                                        Spacer(Modifier.width(4.dp))
                                        MIcon(R.drawable.ic_m_chev_down, null, size = 14.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                                    }
                                }
                            }
                            if (shared.isNotEmpty() && cal?.can?.share == true) {
                                TextButton(onClick = { withdraw = shared }, modifier = Modifier.padding(start = 36.dp)) {
                                    MIcon(R.drawable.ic_m_x, null, size = 16.dp, tint = MaterialTheme.colorScheme.error)
                                    Spacer(Modifier.width(6.dp))
                                    Text(stringResource(R.string.agenda_rights_withdraw), color = MaterialTheme.colorScheme.error)
                                }
                            }
                        }
                    }
                }
                Surface(shape = RoundedCornerShape(16.dp), color = MaterialTheme.colorScheme.surfaceContainerLow, modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp)) {
                    Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text("—", modifier = Modifier.width(22.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Column {
                            Text(stringResource(R.string.agenda_rights_default), style = MaterialTheme.typography.titleSmall)
                            Text(stringResource(if (t.default.read) R.string.agenda_rights_default_reads else R.string.agenda_rights_default_closed), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
                if (t.set && cal?.can?.rights == true) {
                    OutlinedButton(onClick = vm::reset, enabled = !vm.acting, modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
                        MIcon(R.drawable.ic_m_refresh, null, size = 18.dp)
                        Spacer(Modifier.width(8.dp))
                        Text(stringResource(R.string.agenda_rights_reset))
                    }
                }
                Text(stringResource(R.string.agenda_rights_note), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 24.dp, vertical = 12.dp))
            }
        }
    }
    val t = vm.rights.valueOrNull
    if (cell.isNotEmpty() && t != null) {
        val (i, col) = cell.split('|').let { it[0].toInt() to it[1] }
        val line = t.lines.getOrNull(i)
        if (line != null) {
            ChoiceSheet(RightsColumns.ALL.first { it.first == col }.second, RightsColumns.choices(col), RightsColumns.valueOf(line, col), onDismiss = { cell = "" }) { v ->
                cell = ""
                vm.set(i, col, v)
            }
        }
    }
    if (withdraw.isNotEmpty()) {
        val name = cal?.shares?.firstOrNull { it.person == withdraw }?.name.orEmpty()
        AlertDialog(
            onDismissRequest = { withdraw = "" },
            title = { Text(stringResource(R.string.agenda_rights_withdraw)) },
            text = { Text(stringResource(R.string.agenda_rights_withdraw_text, name, cal?.name.orEmpty())) },
            confirmButton = {
                TextButton(onClick = {
                    vm.withdraw(withdraw)
                    withdraw = ""
                }) { Text(stringResource(R.string.agenda_remove), color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { withdraw = "" }) { Text(stringResource(R.string.cancel)) } },
        )
    }
    if (share && cal != null) ShareSheet(graph, cal, onDismiss = { share = false }, onHide = {})
}

// ── Le groupe « Tes agendas » d'Outils › Droits ─────────────────────────

/** Tes agendas dont tu règles le tableau, et ce que Mika fait de chacun (seule, ton accord, non). */
class AgendaRightsListViewModel(private val deps: AgendaDeps) : ViewModel() {
    var items by mutableStateOf<List<Pair<AgendaCalendar, RightsPills?>>>(emptyList())
        private set
    var error by mutableStateOf<MoiError?>(null)
        private set

    fun read(me: String) {
        viewModelScope.launch {
            when (val got = deps.api.calendars()) {
                is MoiApi.Result.Ok -> {
                    val owned = withShownNames(got.value.calendars).filter { it.owned && it.can.rights }
                    items = owned.map { c -> async { c to (deps.api.rights(c.key) as? MoiApi.Result.Ok)?.value?.let { rightsPills(it, me) } } }.map { it.await() }
                    error = null
                }
                // un serveur sans agenda (503), ou une panne : le groupe ne se montre pas
                is MoiApi.Result.Failed -> error = got.error
            }
        }
    }
}

/** Le groupe « Tes agendas » : chacun, ses pastilles, et son tableau d'un toucher. */
@Composable
fun AgendaRightsGroup(graph: AppGraph) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: AgendaRightsListViewModel = viewModel(key = "agenda.rights.list|$session") { AgendaRightsListViewModel(AgendaDeps(graph)) }
    val me by graph.me.me.collectAsStateWithLifecycle()
    val person = me?.person.orEmpty()
    FollowLive(graph.live, AGENDA_TOPICS, vm, person, onShown = { vm.read(person) }) { vm.read(person) }
    if (vm.items.isEmpty()) return
    Column {
        ListHead(stringResource(R.string.agenda_rights_group))
        for ((c, pills) in vm.items) {
            Surface(
                onClick = { shell.navigate(Route.CalendarRights(c.key)) },
                shape = RoundedCornerShape(16.dp),
                color = MaterialTheme.colorScheme.surfaceContainerLow,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
            ) {
                Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                    Swatch(colorOf(c), 18.dp)
                    Spacer(Modifier.width(14.dp))
                    Column(Modifier.weight(1f)) {
                        Text(stringResource(R.string.agenda_rights_title, c.name), style = MaterialTheme.typography.titleSmall)
                        Text("${providerShort(c)} · ${stringResource(R.string.agenda_whose_mine)}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        if (pills != null) {
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(top = 4.dp)) {
                                if (pills.alone > 0) Tag(stringResource(R.string.agenda_rights_alone, pills.alone), Tone.OK)
                                if (pills.ask > 0) Tag(stringResource(R.string.agenda_rights_ask, pills.ask), Tone.WARN)
                                if (pills.no > 0) Tag(stringResource(R.string.agenda_rights_no, pills.no), Tone.NEUTRAL)
                            }
                        }
                    }
                    MIcon(R.drawable.ic_m_chev_right, null, size = 18.dp)
                }
            }
        }
    }
}
