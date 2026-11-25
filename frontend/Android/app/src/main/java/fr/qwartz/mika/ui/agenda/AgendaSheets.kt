package fr.qwartz.mika.ui.agenda

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.agenda.AgendaAccount
import fr.qwartz.mika.data.moi.agenda.AgendaCalendar
import fr.qwartz.mika.data.moi.agenda.AgendaGroups
import fr.qwartz.mika.data.moi.agenda.AgendaKinds
import fr.qwartz.mika.data.moi.agenda.AgendaLevels
import fr.qwartz.mika.data.moi.agenda.AgendaShare
import fr.qwartz.mika.data.moi.agenda.AgendaSignin
import fr.qwartz.mika.data.moi.agenda.LEVELS
import fr.qwartz.mika.data.moi.agenda.PALETTE
import fr.qwartz.mika.data.moi.agenda.PALETTE_WORDS
import fr.qwartz.mika.data.moi.agenda.calendarLine
import fr.qwartz.mika.data.moi.agenda.colorOf
import fr.qwartz.mika.data.moi.agenda.groupedCalendars
import fr.qwartz.mika.data.moi.agenda.levelWords
import fr.qwartz.mika.data.moi.agenda.providerShort
import fr.qwartz.mika.data.moi.agenda.rightsSummary
import fr.qwartz.mika.data.moi.firstName
import fr.qwartz.mika.data.moi.settings.Person
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.SettingsPages
import fr.qwartz.mika.ui.components.settingsPage
import fr.qwartz.mika.ui.shell.BarAction
import fr.qwartz.mika.ui.shell.ListHead
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.shell.PersonAvatar
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.shell.said
import fr.qwartz.mika.ui.theme.mika
import fr.qwartz.mika.ui.theme.states
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

/*
 * Les feuilles de l'Agenda (la maquette validée `agenda.js`) : « Agendas à afficher » (cochés, groupés ; ⋮ au bout d'une
 * ligne), un agenda (sa couleur, l'afficher seul, le partager, ce que Mika en fait, ses paramètres), et le partager.
 */

/** Un compte en panne ou à reconnecter : ses agendas ne se relisent plus. */
internal fun failing(accounts: List<AgendaAccount>): List<AgendaAccount> =
    accounts.filter { !it.system && it.enabled && (it.error.isNotBlank() || ((it.kind == AgendaKinds.GOOGLE || it.kind == AgendaKinds.MICROSOFT) && it.signin?.state != AgendaSignin.CONNECTED)) }

/** La case d'un agenda, de sa couleur : pleine et cochée, ou son contour. */
@Composable
internal fun ColorCheck(color: String, on: Boolean) {
    val c = agendaColor(color)
    Box(
        Modifier.size(22.dp).clip(RoundedCornerShape(5.dp)).then(if (on) Modifier.background(c) else Modifier.border(2.dp, c, RoundedCornerShape(5.dp))),
        contentAlignment = Alignment.Center,
    ) {
        if (on) MIcon(R.drawable.ic_m_check, null, size = 16.dp, tint = androidx.compose.ui.graphics.Color.White)
    }
}

/**
 * « Agendas à afficher » : les cases de leur couleur, groupées (Mes agendas · Partagés avec moi · Abonnements ·
 * L'agenda de Mika) ; ⋮ au bout d'une ligne ; un compte à reconnecter ; « Brancher un agenda », « Paramètres des
 * agendas ». Décocher ne change que l'affichage : Mika s'en sert toujours.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun CalendarsSheet(graph: AppGraph, vm: AgendaViewModel, onDismiss: () -> Unit, onCalendar: (String) -> Unit) {
    val shell = LocalShell.current
    val off by vm.off.collectAsStateWithLifecycle()
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.verticalScroll(rememberScrollState()).navigationBarsPadding().padding(bottom = 12.dp)) {
            Text(stringResource(R.string.agenda_calendars_sheet), style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(start = 24.dp, bottom = 4.dp))
            for ((title, cals) in groupedCalendars(vm.list)) {
                ListHead(title)
                for (c in cals) {
                    val on = c.key !in off
                    Row(Modifier.fillMaxWidth().padding(end = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Row(
                            Modifier
                                .weight(1f)
                                .toggleable(value = on, role = Role.Checkbox) { vm.setShown(c.key, it) }
                                .padding(start = 24.dp, top = 8.dp, bottom = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            ColorCheck(colorOf(c), on)
                            Spacer(Modifier.width(16.dp))
                            Column {
                                Text(c.name, style = MaterialTheme.typography.bodyLarge, color = if (c.group == AgendaGroups.MIKA) mika.accent else MaterialTheme.colorScheme.onSurface)
                                Text(calendarLine(c), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                        BarAction(R.drawable.ic_m_more, stringResource(R.string.agenda_calendar_more, c.name), { onCalendar(c.key) })
                    }
                }
            }
            for (a in failing(vm.accounts?.accounts.orEmpty())) {
                val signin = (a.kind == AgendaKinds.GOOGLE || a.kind == AgendaKinds.MICROSOFT) && a.signin?.state != AgendaSignin.CONNECTED
                Surface(
                    onClick = {
                        onDismiss()
                        shell.navigate(settingsPage(SettingsPages.AGENDA_ACCOUNT, a.key))
                    },
                    shape = RoundedCornerShape(14.dp),
                    color = states.warnContainer,
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
                ) {
                    Row(Modifier.padding(horizontal = 14.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                        MIcon(R.drawable.ic_m_alert, null, size = 18.dp, tint = states.warn)
                        Spacer(Modifier.width(10.dp))
                        Text(
                            stringResource(if (signin) R.string.agenda_account_reconnect else R.string.agenda_account_failing, a.label),
                            style = MaterialTheme.typography.bodyMedium,
                            color = states.warn,
                            modifier = Modifier.weight(1f),
                        )
                        MIcon(R.drawable.ic_m_chev_right, null, size = 16.dp, tint = states.warn)
                    }
                }
            }
            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            SheetRow(R.drawable.ic_m_plus, stringResource(R.string.agenda_plug), stringResource(R.string.agenda_plug_line)) {
                onDismiss()
                shell.navigate(settingsPage(SettingsPages.AGENDA_PLUG))
            }
            SheetRow(R.drawable.ic_m_settings, stringResource(R.string.agenda_settings), "") {
                onDismiss()
                shell.navigate(settingsPage(SettingsPages.AGENDAS))
            }
            Text(
                stringResource(R.string.agenda_calendars_note),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp),
            )
        }
    }
}

/** Une ligne de feuille : son icône, son nom, une ligne sous lui. */
@Composable
internal fun SheetRow(icon: Int, title: String, sub: String, tint: androidx.compose.ui.graphics.Color? = null, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).heightIn(min = 52.dp).padding(horizontal = 24.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        MIcon(icon, null, tint = tint ?: MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.width(20.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            if (sub.isNotBlank()) Text(sub, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 3, overflow = TextOverflow.Ellipsis)
        }
    }
}

/** Les pastilles des couleurs ; [selected] cochée. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun Swatches(selected: String, onPick: (String) -> Unit, modifier: Modifier = Modifier) {
    FlowRow(modifier, horizontalArrangement = Arrangement.spacedBy(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        for (k in PALETTE) {
            val on = k == selected
            Box(
                Modifier
                    .size(40.dp)
                    .clip(CircleShape)
                    .background(agendaColor(k))
                    .selectable(on, role = Role.RadioButton) { onPick(k) }
                    .then(if (on) Modifier.border(3.dp, MaterialTheme.colorScheme.surface, CircleShape) else Modifier),
                contentAlignment = Alignment.Center,
            ) {
                if (on) MIcon(R.drawable.ic_m_check, PALETTE_WORDS[k], size = 20.dp, tint = androidx.compose.ui.graphics.Color.White)
            }
        }
    }
}

/** Un agenda : sa couleur, l'afficher seul, le partager, ce que Mika en fait, ses paramètres. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun CalendarSheet(graph: AppGraph, vm: AgendaViewModel, cal: AgendaCalendar, onBack: () -> Unit, onDismiss: () -> Unit, onShare: () -> Unit) {
    val shell = LocalShell.current
    val me by graph.me.me.collectAsStateWithLifecycle()
    val owner = cal.owned
    val summary by produceState("", cal.key, owner) {
        if (owner && cal.can.rights) {
            (graph.agendaApi().rights(cal.key) as? MoiApi.Result.Ok)?.let { value = rightsSummary(it.value, me?.person.orEmpty(), cal.shares, cal.writable) }
        }
    }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.verticalScroll(rememberScrollState()).navigationBarsPadding().padding(bottom = 12.dp)) {
            Row(Modifier.padding(start = 8.dp, end = 24.dp), verticalAlignment = Alignment.CenterVertically) {
                BarAction(R.drawable.ic_m_back, stringResource(R.string.agenda_calendars_back), onBack)
                Swatch(colorOf(cal), 18.dp)
                Spacer(Modifier.width(10.dp))
                Text(cal.name, style = MaterialTheme.typography.titleLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            val whose = when {
                cal.group == AgendaGroups.MIKA -> stringResource(R.string.agenda_whose_her)
                owner -> stringResource(R.string.agenda_whose_mine)
                else -> stringResource(R.string.agenda_whose_other, cal.ownerName)
            }
            Text("${providerShort(cal)} · $whose", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 24.dp))
            when {
                cal.kind == AgendaKinds.MIKA -> {
                    ListHead(stringResource(R.string.agenda_color))
                    Text(stringResource(R.string.agenda_color_hers), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 24.dp))
                }
                owner && cal.can.settings -> {
                    ListHead(stringResource(R.string.agenda_color))
                    Swatches(colorOf(cal), { vm.setColor(cal.key, it) }, Modifier.padding(horizontal = 24.dp, vertical = 4.dp))
                }
            }
            Spacer(Modifier.height(8.dp))
            SheetRow(R.drawable.ic_m_eye, stringResource(R.string.agenda_show_only), "") {
                vm.showOnly(cal.key)
                onDismiss()
            }
            if (cal.kind != AgendaKinds.MIKA) {
                SheetRow(
                    R.drawable.ic_m_user_plus,
                    stringResource(if (owner) R.string.agenda_share else R.string.agenda_share_owner_only),
                    if (cal.shares.isNotEmpty()) stringResource(R.string.agenda_shared_with, cal.shares.joinToString(" et ") { firstName(it.name).ifBlank { it.name } }) else "",
                    onClick = onShare,
                )
            }
            if (owner && cal.can.rights) {
                SheetRow(R.drawable.ic_m_shield, stringResource(R.string.agenda_what_mika_does), summary) {
                    onDismiss()
                    shell.navigate(Route.CalendarRights(cal.key))
                }
            }
            if (owner || cal.kind == AgendaKinds.MIKA) {
                SheetRow(R.drawable.ic_m_settings, stringResource(R.string.agenda_calendar_settings), "") {
                    onDismiss()
                    shell.navigate(if (owner) settingsPage(SettingsPages.AGENDA_CALENDAR, cal.key) else settingsPage(SettingsPages.AGENDAS))
                }
            }
        }
    }
}

// ── Partager un agenda ──────────────────────────────────────────────────

/**
 * Partager un agenda (`POST /api/moi/shares/set`, `kind: "agenda"`) : seul son propriétaire, à une personne qui a un
 * compte sur ce serveur — lire, lire et préparer, s'en servir. Un partage dans Mika n'est pas un partage chez Google ou
 * Microsoft. Un geste à la fois, son sort en toast ; les partages en cours suivent ce que le serveur a accepté.
 */
class ShareViewModel(private val deps: AgendaDeps) : ViewModel() {
    private val notices = Channel<String>(Channel.BUFFERED)
    val said: Flow<String> = notices.receiveAsFlow()

    var people by mutableStateOf<List<Person>?>(null)
        private set
    var shares by mutableStateOf<List<AgendaShare>>(emptyList())
        private set
    var acting by mutableStateOf(false)
        private set
    private var calendar = ""

    fun open(cal: AgendaCalendar) {
        if (cal.key != calendar) {
            calendar = cal.key
            shares = cal.shares
        }
        if (people == null) {
            viewModelScope.launch { (deps.api.people() as? MoiApi.Result.Ok)?.let { people = it.value.items } }
        }
    }

    /** À qui partager : celles et ceux qui ont un compte, sauf ses propriétaires (ce qui est « à toi » est déjà à elles). */
    val candidates: List<Person> get() = people.orEmpty().filter { !it.owner }

    fun share(person: Person, level: String) = send(person.person, level) {
        shares = shares.filter { it.person != person.person } + AgendaShare(person.person, person.name, level)
    }

    fun remove(person: String) = send(person, "") { shares = shares.filter { it.person != person } }

    private fun send(person: String, level: String, done: () -> Unit) {
        if (acting || calendar.isEmpty()) return
        acting = true
        viewModelScope.launch {
            when (val got = deps.api.share(calendar, person, level)) {
                is MoiApi.Result.Ok -> {
                    done()
                    notices.trySend(got.value.message)
                }
                is MoiApi.Result.Failed -> notices.trySend(got.error.said)
            }
            acting = false
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
internal fun ShareSheet(graph: AppGraph, cal: AgendaCalendar, onDismiss: () -> Unit, onHide: () -> Unit) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: ShareViewModel = viewModel(key = "agenda.share|$session") { ShareViewModel(AgendaDeps(graph)) }
    LaunchedEffect(vm, cal.key) { vm.open(cal) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.verticalScroll(rememberScrollState()).navigationBarsPadding().padding(bottom = 16.dp)) {
            Row(Modifier.padding(horizontal = 24.dp), verticalAlignment = Alignment.CenterVertically) {
                Swatch(colorOf(cal), 18.dp)
                Spacer(Modifier.width(10.dp))
                Text(stringResource(R.string.agenda_share_title, cal.name), style = MaterialTheme.typography.titleLarge, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
            if (!cal.owned || !cal.can.share) {
                Text(
                    if (cal.kind == AgendaKinds.MIKA) stringResource(R.string.agenda_share_hers) else stringResource(R.string.agenda_share_not_owner, cal.ownerName.ifBlank { stringResource(R.string.agenda_owner) }, levelWords(cal.level).lowercase()),
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(horizontal = 24.dp, vertical = 12.dp),
                )
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), horizontalArrangement = Arrangement.End) {
                    if (cal.kind != AgendaKinds.MIKA) {
                        TextButton(onClick = {
                            onHide()
                            onDismiss()
                            shell.toast(shell.graph.context.getString(R.string.agenda_hidden_here, cal.name))
                        }) { Text(stringResource(R.string.agenda_hide_here)) }
                    }
                    TextButton(onClick = onDismiss) { Text(stringResource(R.string.agenda_understood)) }
                }
                return@Column
            }
            Text(
                "${providerShort(cal)} · ${stringResource(R.string.agenda_whose_mine)}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 24.dp, vertical = 4.dp),
            )
            val provider = when (cal.kind) {
                AgendaKinds.GOOGLE -> "Google"
                AgendaKinds.MICROSOFT -> "Microsoft"
                AgendaKinds.CALDAV -> stringResource(R.string.agenda_caldav_server)
                else -> ""
            }
            if (provider.isNotEmpty()) {
                NoteBox(stringResource(R.string.agenda_share_here_only, cal.name, provider), R.drawable.ic_m_info, Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
            }
            val candidates = vm.candidates
            var who by remember(candidates) { mutableStateOf(candidates.firstOrNull()?.person.orEmpty()) }
            var level by remember { mutableStateOf(AgendaLevels.READ) }
            ListHead(stringResource(R.string.agenda_share_with))
            when {
                vm.people == null -> Text(stringResource(R.string.agenda_loading), style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(horizontal = 24.dp))
                candidates.isEmpty() -> Text(stringResource(R.string.agenda_share_nobody), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 24.dp))
                else -> FlowRow(Modifier.padding(horizontal = 24.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    for (p in candidates) {
                        FilterChip(
                            selected = p.person == who,
                            onClick = { who = p.person },
                            label = { Text(p.name) },
                            leadingIcon = { PersonAvatar(p.name, p.person, 20.dp) },
                        )
                    }
                }
            }
            Text(stringResource(R.string.agenda_share_accounts_only), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 24.dp, vertical = 4.dp))
            ListHead(stringResource(R.string.agenda_share_can))
            for ((k, label, help) in LEVELS) {
                val on = k == level
                Row(
                    Modifier
                        .fillMaxWidth()
                        .selectable(on, role = Role.RadioButton) { level = k }
                        .background(if (on) MaterialTheme.colorScheme.secondaryContainer else androidx.compose.ui.graphics.Color.Transparent)
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.Top,
                ) {
                    RadioButton(selected = on, onClick = null, modifier = Modifier.padding(top = 2.dp))
                    Spacer(Modifier.width(12.dp))
                    Column {
                        Text(label, style = MaterialTheme.typography.bodyLarge)
                        Text(help, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            val chosen = candidates.firstOrNull { it.person == who }
            Button(
                onClick = { chosen?.let { vm.share(it, level) } },
                enabled = chosen != null && !vm.acting,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 10.dp),
            ) {
                MIcon(R.drawable.ic_m_user_plus, null, size = 18.dp)
                Spacer(Modifier.width(8.dp))
                Text(stringResource(R.string.agenda_share_with_who, firstName(chosen?.name.orEmpty()).ifBlank { chosen?.name.orEmpty() }))
            }
            ListHead(stringResource(R.string.agenda_shares_now, vm.shares.size))
            if (vm.shares.isEmpty()) {
                Text(stringResource(R.string.agenda_shares_none), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 24.dp))
            }
            for (s in vm.shares) {
                var menu by remember(s.person) { mutableStateOf(false) }
                Row(Modifier.fillMaxWidth().padding(start = 24.dp, end = 8.dp, top = 4.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                    PersonAvatar(s.name, s.person, 32.dp)
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text(s.name, style = MaterialTheme.typography.bodyLarge)
                        Text(levelWords(s.level), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Box {
                        TextButton(onClick = { menu = true }, enabled = !vm.acting) { Text(stringResource(R.string.agenda_change)) }
                        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                            for ((k, label, _) in LEVELS) {
                                DropdownMenuItem(
                                    text = { Text(label) },
                                    trailingIcon = if (k == s.level) ({ MIcon(R.drawable.ic_m_check, null, size = 18.dp) }) else null,
                                    onClick = {
                                        menu = false
                                        if (k != s.level) people(vm, s)?.let { vm.share(it, k) }
                                    },
                                )
                            }
                        }
                    }
                    BarAction(R.drawable.ic_m_x, stringResource(R.string.agenda_share_remove, s.name), { vm.remove(s.person) })
                }
            }
            Spacer(Modifier.height(4.dp))
            SheetRow(R.drawable.ic_m_shield, stringResource(R.string.agenda_what_mika_does_each), stringResource(R.string.agenda_tools_rights)) {
                onDismiss()
                shell.navigate(Route.CalendarRights(cal.key))
            }
        }
    }
}

/** La personne d'un partage en cours (son nom, même quand la liste des personnes ne la redit pas). */
private fun people(vm: ShareViewModel, s: AgendaShare): Person? =
    vm.people.orEmpty().firstOrNull { it.person == s.person } ?: Person(s.person, s.name)
