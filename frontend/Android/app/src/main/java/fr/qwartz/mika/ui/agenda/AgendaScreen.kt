package fr.qwartz.mika.ui.agenda

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.firstName
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.agenda.AgendaItem
import fr.qwartz.mika.data.moi.agenda.AgendaView
import fr.qwartz.mika.data.moi.agenda.FormModes
import fr.qwartz.mika.data.moi.agenda.Occ
import fr.qwartz.mika.data.moi.agenda.barTitle
import fr.qwartz.mika.data.moi.agenda.bounds
import fr.qwartz.mika.data.moi.agenda.decideSummary
import fr.qwartz.mika.data.moi.agenda.gridDays
import fr.qwartz.mika.data.moi.agenda.inviter
import fr.qwartz.mika.data.moi.agenda.occOfProposal
import fr.qwartz.mika.data.moi.agenda.offsetWords
import fr.qwartz.mika.data.moi.agenda.partsOf
import fr.qwartz.mika.data.moi.agenda.proposalWhen
import fr.qwartz.mika.data.moi.agenda.shortDay
import fr.qwartz.mika.data.moi.agenda.hm
import fr.qwartz.mika.data.moi.agenda.occOfItem
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.components.SettingsPages
import fr.qwartz.mika.ui.components.settingsPage
import fr.qwartz.mika.ui.shell.BarAction
import fr.qwartz.mika.ui.shell.CountPill
import fr.qwartz.mika.ui.shell.FollowLive
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MenuButton
import fr.qwartz.mika.ui.shell.MikaFace
import fr.qwartz.mika.ui.shell.MikaFaceButton
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.theme.mika

/** Les mots des étiquettes d'une occurrence, lus une fois. */
@Composable
internal fun rememberTagWords(): OccTagWords {
    val invited = stringResource(R.string.agenda_tag_invited)
    val maybe = stringResource(R.string.agenda_tag_maybe)
    val proposed = stringResource(R.string.agenda_tag_proposed)
    val promised = stringResource(R.string.agenda_tag_promised)
    val remembers = stringResource(R.string.agenda_tag_remembers)
    val added = stringResource(R.string.agenda_tag_added)
    val visio = stringResource(R.string.agenda_visio)
    return remember(invited) { OccTagWords({ who -> if (who.isBlank()) invited else "$invited · $who" }, maybe, proposed, promised, remembers, added, visio) }
}

/**
 * L'Agenda, la rubrique du tiroir après Teams (ADR 0309, la maquette validée `ecrans/agenda.js`) : la barre d'un agenda
 * de téléphone — ☰, le mois en titre (qui déplie le mini-mois), chercher, « Aujourd'hui » (l'icône au numéro du jour),
 * ⋮ (les cinq vues, « Agendas à afficher », les invitations, les paramètres), son visage —, « À décider » en tête, la
 * vue (on balaie pour changer de période), le bouton +. Tirer relit ; l'écran suit le direct (`agenda`).
 */
@Composable
fun AgendaScreen(graph: AppGraph) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: AgendaViewModel = viewModel(key = "agenda|$session") { AgendaViewModel(AgendaDeps(graph)) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    FollowLive(graph.live, AGENDA_TOPICS, vm, onShown = { vm.resume() }) { vm.onLive(it) }
    val off by vm.off.collectAsStateWithLifecycle()
    val wall = rememberNow(intervalMs = 30_000L, wallMs = graph.clock::wallMs)
    val (today, nowMinute) = vm.now(wall)
    var sheet by rememberSaveable { mutableStateOf("") }
    val words = rememberTagWords()
    val open: (Occ) -> Unit = { o -> routeOf(o)?.let(shell.navigate) }

    SectionScaffold(
        topBar = { AgendaTopBar(vm, today, invitations = vm.invitations.size, onSheet = { sheet = it }) },
        floatingActionButton = {
            FloatingActionButton(onClick = { shell.navigate(Route.AgendaForm(FormModes.NEW, day = vm.shownDate)) }) {
                MIcon(R.drawable.ic_m_plus, stringResource(R.string.agenda_new))
            }
        },
    ) { modifier ->
        LoadBox(vm.calendars, onRetry = vm::retry, modifier = modifier) { _ ->
            Column(modifier) {
                AnimatedVisibility(vm.mini != null) {
                    val list = vm.list
                    MiniMonth(
                        month = vm.mini ?: vm.shownDate,
                        occs = vm.miniOccs(off),
                        today = today,
                        selected = vm.shownDate,
                        shownCount = list.count { !it.hidden && it.key !in off } to list.count { !it.hidden },
                        onPick = vm::pick,
                        onMove = vm::miniMove,
                        onCalendars = { sheet = SHEET_CALENDARS },
                    )
                }
                Decide(vm, today, onOpen = { shell.navigate(it) })
                PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::pull, modifier = Modifier.fillMaxSize()) {
                    LoadBox(vm.period, onRetry = vm::retry) { _ ->
                        val occs = vm.occs(off)
                        val calendars = vm.list
                        when (vm.view) {
                            AgendaView.PLANNING -> {
                                val (first, after) = bounds(AgendaView.PLANNING, vm.shownDate)
                                PlanningView(occs, first, after, today, nowMinute, calendars, words, open, vm::openDay, onNext = { vm.move(1) })
                            }
                            AgendaView.MONTH -> MonthView(occs, vm.shownDate, today, nowMinute, calendars, vm::openDay, Modifier.swipe(vm::move))
                            else -> GridView(
                                gridDays(vm.view, vm.shownDate), occs, today, nowMinute, offsetWords(vm.zone, wall), calendars,
                                onOpen = open,
                                onDay = vm::openDay,
                                onSlot = { day, minute -> shell.navigate(Route.AgendaForm(FormModes.NEW, day = day, minute = minute)) },
                                modifier = Modifier.swipe(vm::move),
                            )
                        }
                    }
                }
            }
        }
    }
    when (sheet) {
        SHEET_CALENDARS -> CalendarsSheet(graph, vm, onDismiss = { sheet = "" }, onCalendar = { sheet = "$SHEET_CALENDAR$it" })
        else -> if (sheet.startsWith(SHEET_CALENDAR)) {
            val key = sheet.removePrefix(SHEET_CALENDAR)
            vm.list.firstOrNull { it.key == key }?.let { cal ->
                CalendarSheet(graph, vm, cal, onBack = { sheet = SHEET_CALENDARS }, onDismiss = { sheet = "" }, onShare = { sheet = "$SHEET_SHARE$key" })
            }
        } else if (sheet.startsWith(SHEET_SHARE)) {
            val key = sheet.removePrefix(SHEET_SHARE)
            vm.list.firstOrNull { it.key == key }?.let { cal -> ShareSheet(graph, cal, onDismiss = { sheet = "" }, onHide = { vm.setShown(key, false) }) }
        }
    }
}

internal const val SHEET_CALENDARS = "agendas"
internal const val SHEET_CALENDAR = "agenda:"
internal const val SHEET_SHARE = "partager:"

/** Ce que suivent les écrans de l'Agenda : l'agenda (`agenda`, ADR 0308). */
internal val AGENDA_TOPICS = fr.qwartz.mika.data.moi.agenda.AgendaLive.TOPICS

/**
 * La barre : ☰, le mois (le toucher déplie le mini-mois), chercher, « Aujourd'hui » (son numéro dans l'icône), ⋮ et son
 * menu (les cinq vues, la vue ouverte cochée ; « Agendas à afficher », les invitations, les paramètres), son visage.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AgendaTopBar(vm: AgendaViewModel, today: String, invitations: Int, onSheet: (String) -> Unit) {
    val shell = LocalShell.current
    var menu by remember { mutableStateOf(false) }
    val title = barTitle(vm.view, vm.shownDate, today, vm.mini)
    val unfold = stringResource(if (vm.mini != null) R.string.agenda_month_fold else R.string.agenda_month_unfold)
    TopAppBar(
        navigationIcon = { MenuButton(shell.openDrawer) },
        title = {
            Row(
                Modifier
                    .clickable(onClickLabel = unfold) { vm.toggleMini() }
                    .padding(vertical = 4.dp, horizontal = 2.dp)
                    .semantics { stateDescription = unfold },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(title, style = MaterialTheme.typography.titleLarge, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.semantics { heading() })
                Spacer(Modifier.width(4.dp))
                MIcon(if (vm.mini != null) R.drawable.ic_m_chev_up else R.drawable.ic_m_chev_down, null, size = 18.dp)
            }
        },
        actions = {
            BarAction(R.drawable.ic_m_search, stringResource(R.string.agenda_search), { shell.navigate(Route.AgendaSearch) })
            val todayLabel = stringResource(R.string.agenda_go_today)
            IconButton(onClick = { vm.goToday() }, modifier = Modifier.semantics { contentDescription = todayLabel }) {
                Box(contentAlignment = Alignment.Center) {
                    MIcon(R.drawable.ic_m_today, null)
                    Text(partsOf(today).d.toString(), fontSize = 9.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 4.dp))
                }
            }
            Box {
                BarAction(R.drawable.ic_m_more, stringResource(R.string.agenda_menu), { menu = true })
                DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                    for ((v, label, icon) in VIEWS) {
                        val on = v == vm.view
                        DropdownMenuItem(
                            text = { Text(stringResource(label), fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal) },
                            leadingIcon = { MIcon(icon, null, size = 20.dp) },
                            trailingIcon = if (on) ({ MIcon(R.drawable.ic_m_check, null, size = 18.dp) }) else null,
                            onClick = {
                                menu = false
                                vm.choose(v)
                            },
                        )
                    }
                    HorizontalDivider()
                    DropdownMenuItem(
                        text = { Text(stringResource(R.string.agenda_calendars_sheet)) },
                        leadingIcon = { MIcon(R.drawable.ic_m_eye, null, size = 20.dp) },
                        onClick = {
                            menu = false
                            onSheet(SHEET_CALENDARS)
                        },
                    )
                    DropdownMenuItem(
                        text = { Text(if (invitations > 0) stringResource(R.string.agenda_invitations_n, invitations) else stringResource(R.string.agenda_invitations)) },
                        leadingIcon = { MIcon(R.drawable.ic_m_inbox, null, size = 20.dp) },
                        onClick = {
                            menu = false
                            shell.navigate(Route.AgendaInvitations)
                        },
                    )
                    DropdownMenuItem(
                        text = { Text(stringResource(R.string.agenda_settings)) },
                        leadingIcon = { MIcon(R.drawable.ic_m_settings, null, size = 20.dp) },
                        onClick = {
                            menu = false
                            shell.navigate(settingsPage(SettingsPages.AGENDAS))
                        },
                    )
                }
            }
            MikaFaceButton()
        },
        colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
    )
}

private val VIEWS = listOf(
    Triple(AgendaView.PLANNING, R.string.agenda_view_planning, R.drawable.ic_m_view_list),
    Triple(AgendaView.DAY, R.string.agenda_view_day, R.drawable.ic_m_view_day),
    Triple(AgendaView.THREE, R.string.agenda_view_three, R.drawable.ic_m_view_3),
    Triple(AgendaView.WEEK, R.string.agenda_view_week, R.drawable.ic_m_view_week),
    Triple(AgendaView.MONTH, R.string.agenda_view_month, R.drawable.ic_m_view_month),
)

/**
 * « À décider » en tête des vues : replié, une ligne (comme celle des accords du chat) ; déplié — d'office en Planning —,
 * ce que Mika propose d'ajouter (Refuser · Modifier · Ajouter) puis les invitations : une ligne vers leur page quand la
 * proposition est là, sinon chacune vers sa fiche.
 */
@Composable
private fun Decide(vm: AgendaViewModel, today: String, onOpen: (Route) -> Unit) {
    val adds = vm.adds
    val invs = vm.invitations
    if (adds.isEmpty() && invs.isEmpty()) return
    val first = adds.firstOrNull()
    val firstOcc = first?.let { occOfProposal(it, vm.zone) }
    val n = invs.size + if (first != null) 1 else 0
    Surface(
        shape = RoundedCornerShape(18.dp),
        color = mika.soft,
        border = BorderStroke(1.dp, mika.line),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
    ) {
        if (!vm.decideUnfolded) {
            val label = stringResource(R.string.agenda_decide_unfold)
            Row(
                Modifier.fillMaxWidth().clickable(onClickLabel = label) { vm.toggleDecide() }.heightIn(min = 44.dp).padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                MIcon(R.drawable.ic_m_sparkle, null, size = 18.dp, tint = mika.accent)
                Spacer(Modifier.width(10.dp))
                Text(
                    "${stringResource(R.string.agenda_decide)} · ${decideSummary(adds, invs.size)}",
                    style = MaterialTheme.typography.bodyMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                CountPill(n + (adds.size - if (first != null) 1 else 0), pink = true)
                Spacer(Modifier.width(6.dp))
                MIcon(R.drawable.ic_m_chev_down, null, size = 18.dp)
            }
            return@Surface
        }
        Column {
            if (first != null && firstOcc != null) {
                val cal = vm.list.firstOrNull { it.key == first.calendar }
                Column(Modifier.padding(start = 12.dp, end = 4.dp, top = 10.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Row(Modifier.weight(1f).clickable { onOpen(Route.AgendaProposal(first.id)) }, verticalAlignment = Alignment.CenterVertically) {
                            MikaFace(32.dp)
                            Spacer(Modifier.width(10.dp))
                            Column(Modifier.weight(1f)) {
                                Text(stringResource(R.string.agenda_decide_proposes, firstOcc.title), style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(proposalWhen(firstOcc) + " · ", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    if (cal != null) {
                                        Swatch(fr.qwartz.mika.data.moi.agenda.colorOf(cal), 10.dp)
                                        Spacer(Modifier.width(4.dp))
                                        Text(cal.name, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    }
                                }
                            }
                        }
                        BarAction(R.drawable.ic_m_chev_up, stringResource(R.string.agenda_decide_fold), vm::toggleDecide)
                    }
                    Row(Modifier.fillMaxWidth().padding(end = 8.dp, bottom = 6.dp), horizontalArrangement = Arrangement.End, verticalAlignment = Alignment.CenterVertically) {
                        if (adds.size > 1) {
                            Text(pluralStringResource(R.plurals.agenda_decide_others, adds.size - 1, adds.size - 1), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
                        }
                        TextButton(onClick = { vm.refuse(first) }, enabled = !vm.acting) { Text(stringResource(R.string.agenda_refuse)) }
                        TextButton(onClick = { onOpen(Route.AgendaForm(FormModes.PROPOSAL, proposal = first.id)) }, enabled = !vm.acting) { Text(stringResource(R.string.agenda_modify)) }
                        Button(onClick = { vm.accept(first) }, enabled = !vm.acting && first.preview?.blocked.isNullOrEmpty()) {
                            MIcon(R.drawable.ic_m_check, null, size = 18.dp)
                            Spacer(Modifier.width(6.dp))
                            Text(stringResource(R.string.agenda_add))
                        }
                    }
                }
                if (invs.isNotEmpty()) HorizontalDivider(color = mika.line)
            }
            if (invs.isNotEmpty()) {
                if (first != null) {
                    Row(
                        Modifier.fillMaxWidth().clickable { onOpen(Route.AgendaInvitations) }.padding(horizontal = 12.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        MIcon(R.drawable.ic_m_inbox, null, size = 18.dp)
                        Spacer(Modifier.width(10.dp))
                        val names = invs.mapNotNull { firstName(inviter(it)).ifBlank { null } }.distinct().joinToString(", ")
                        val prepared = invs.any { it.prepared?.decides == true }
                        val count = pluralStringResourceText(invs.size)
                        val prep = stringResource(R.string.agenda_decide_prepared)
                        val pink = mika.accent
                        Text(
                            buildAnnotatedString {
                                withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { append(count) }
                                if (names.isNotEmpty()) append(" · $names")
                                if (prepared) withStyle(SpanStyle(color = pink)) { append(" · $prep") }
                            },
                            style = MaterialTheme.typography.bodyMedium,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f),
                        )
                        MIcon(R.drawable.ic_m_chev_right, null, size = 16.dp)
                    }
                } else {
                    Row(Modifier.fillMaxWidth().padding(start = 12.dp, top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        MIcon(R.drawable.ic_m_inbox, null, size = 18.dp)
                        Spacer(Modifier.width(10.dp))
                        Text(pluralStringResourceText(invs.size), style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                        BarAction(R.drawable.ic_m_chev_up, stringResource(R.string.agenda_decide_fold), vm::toggleDecide)
                    }
                    for (i in invs.take(3)) InvitationLine(i, vm.zone, today) { onOpen(Route.AgendaEvent(i.event, i.occurrence)) }
                    if (invs.size > 3) {
                        TextButton(onClick = { onOpen(Route.AgendaInvitations) }, modifier = Modifier.padding(start = 4.dp)) { Text(stringResource(R.string.agenda_invitations_all)) }
                    }
                }
            }
        }
    }
}

@Composable
private fun pluralStringResourceText(n: Int): String = pluralStringResource(R.plurals.agenda_invitations_count, n, n)

/** Une invitation de « À décider » : de qui, quand, et ce que Mika a préparé. */
@Composable
private fun InvitationLine(i: AgendaItem, zone: String, today: String, onClick: () -> Unit) {
    val o = occOfItem(i, zone)
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        val who = inviter(i)
        fr.qwartz.mika.ui.shell.PersonAvatar(who, i.organizer?.address.orEmpty(), 32.dp)
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(o.title, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                stringResource(R.string.agenda_invites_on, firstName(who).ifBlank { who }, "${shortDay(o.day)}${if (o.allDay) "" else ", " + hm(o.start)}"),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            val p = i.prepared?.takeIf { it.decides }
            if (p != null) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    MIcon(R.drawable.ic_m_sparkle, null, size = 12.dp, tint = mika.accent)
                    Spacer(Modifier.width(4.dp))
                    Text(stringResource(R.string.agenda_prepared_short, fr.qwartz.mika.data.moi.agenda.ANSWERS.firstOrNull { it.first == p.answer }?.second?.lowercase() ?: p.answer), style = MaterialTheme.typography.bodySmall, color = mika.accent)
                }
            }
        }
        MIcon(R.drawable.ic_m_chev_right, null, size = 16.dp)
    }
}
