package fr.qwartz.mika.ui.projects

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.projects.AskFor
import fr.qwartz.mika.data.moi.projects.CodePages
import fr.qwartz.mika.data.moi.projects.Entry
import fr.qwartz.mika.data.moi.projects.EntryDetail
import fr.qwartz.mika.data.moi.projects.EntryHistory
import fr.qwartz.mika.data.moi.projects.Sheet
import fr.qwartz.mika.data.moi.projects.StateTone
import fr.qwartz.mika.data.moi.projects.ThreadNote
import fr.qwartz.mika.data.moi.projects.TicketFilters
import fr.qwartz.mika.data.moi.projects.TicketForm
import fr.qwartz.mika.data.moi.projects.TicketPanes
import fr.qwartz.mika.data.moi.projects.moment
import fr.qwartz.mika.data.moi.projects.objectiveTone
import fr.qwartz.mika.data.moi.projects.plural
import fr.qwartz.mika.data.moi.projects.since
import fr.qwartz.mika.data.moi.projects.stepNote
import fr.qwartz.mika.data.moi.projects.storyRows
import fr.qwartz.mika.data.moi.projects.ticketList
import fr.qwartz.mika.data.moi.projects.ticketTone
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.AskDialog
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Shell
import fr.qwartz.mika.ui.shell.rememberSessionKey
import androidx.compose.runtime.saveable.rememberSaveable

/*
 * Les tickets d'un projet (ADR 0296) : l'onglet — une recherche, ses filtres (À toi, Ouverts, Tous), « Nouveau ticket »,
 * la liste — puis un ticket en page : son en-tête et les gestes du moment (ceux que `can` ouvre, rien d'autre), ses
 * volets Description · Plan · Fil · Historique, et « Infos » (ce que le web met dans son panneau latéral : son parcours
 * en six étapes, ses propriétés, la pull request liée avec son statut, l'issue).
 */

// ── L'onglet ────────────────────────────────────────────────────────────

@Composable
internal fun TicketsTab(vm: ProjectViewModel, sheet: Sheet, now: Long, onNew: () -> Unit) {
    val shell = LocalShell.current
    LaunchedEffect(vm) { vm.openTickets() }
    val list = ticketList(sheet)
    val all = vm.tickets?.valueOrNull?.items.orEmpty()
    val shown = TicketFilters.shown(vm.ticketFilter, all)
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = vm.ticketQuery,
                onValueChange = vm::search,
                placeholder = { Text(stringResource(R.string.proj_tickets_search)) },
                leadingIcon = { MIcon(R.drawable.ic_m_search, null, size = 20.dp) },
                singleLine = true,
                modifier = Modifier.weight(1f),
            )
            if (sheet.rights.ticket) {
                Spacer(Modifier.width(10.dp))
                val label = stringResource(R.string.proj_ticket_new)
                FilledIconButton(onClick = onNew) { MIcon(R.drawable.ic_m_plus, label) }
            }
        }
        ChipRow(
            listOf(
                Chip(TicketFilters.YOURS, stringResource(R.string.proj_tickets_yours), if (vm.ticketFilter == TicketFilters.ALL) null else all.count { it.yours }),
                Chip(TicketFilters.OPEN, stringResource(R.string.proj_tickets_opened), list?.living),
                Chip(TicketFilters.ALL, stringResource(R.string.proj_filter_all), list?.total),
            ),
            selected = vm.ticketFilter,
            onPick = vm::pickTicketFilter,
            modifier = Modifier.padding(bottom = 4.dp),
        )
        when (val load = vm.tickets) {
            null, Load.Loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            is Load.Failed -> Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                RefusalNote(load.error.message)
                OutlinedButton(onClick = { vm.loadTickets() }) { Text(stringResource(R.string.retry)) }
            }
            is Load.Ready -> LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
                if (shown.isEmpty()) {
                    item(key = "none") {
                        val some = (list?.total ?: 0) > 0
                        EmptyNote(
                            R.drawable.ic_m_ticket,
                            stringResource(if (some) R.string.proj_tickets_nothing else R.string.proj_tickets_none_yet),
                            stringResource(if (some) R.string.proj_tickets_nothing_sub else R.string.proj_tickets_none_yet_sub),
                        )
                    }
                }
                itemsIndexed(shown, key = { i, t -> "t${t.number}:$i" }) { _, t -> TicketRow(t, now) { shell.navigate(Route.ProjectTicket(vm.id, t.number)) } }
                if (load.value.total > all.size) {
                    item(key = "more") {
                        Hint(stringResource(R.string.proj_tickets_refine, plural(load.value.total - all.size, "autre ticket", "autres tickets")), modifier = Modifier.padding(12.dp))
                    }
                }
            }
        }
    }
}

/** Une ligne de ticket : son numéro (un point ambre quand la main est à toi), son titre, son étape en pastille, sa priorité si elle est haute, son âge. */
@Composable
private fun TicketRow(t: Entry, now: Long, onClick: () -> Unit) {
    Column(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Row(Modifier.padding(start = 8.dp, end = 16.dp, top = 12.dp, bottom = 12.dp), verticalAlignment = Alignment.Top) {
            Box(Modifier.padding(top = 7.dp).size(6.dp).background(if (t.yours) toneOf(StateTone.YOU).bar else androidx.compose.ui.graphics.Color.Transparent, CircleShape))
            Spacer(Modifier.width(4.dp))
            Text("#${t.number}", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.width(40.dp))
            Column(Modifier.weight(1f)) {
                Text(t.title.ifBlank { t.veiledLabel }, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Gap(5.dp)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    StatePill(ticketTone(t), t.statusLabel)
                    if (t.priority == "high" || t.priority == "urgent") {
                        Spacer(Modifier.width(8.dp))
                        PriorityMark(t.priorityLabel, high = true)
                    }
                    if (t.outside) {
                        Spacer(Modifier.width(8.dp))
                        OutsideMark()
                    }
                    Spacer(Modifier.weight(1f))
                    Text(since(if (t.updatedAt > 0) t.updatedAt else t.at, now), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                }
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    }
}

/** La priorité d'un ticket : son drapeau et ses mots, en rouge quand elle est haute. */
@Composable
private fun PriorityMark(label: String, high: Boolean) {
    val color = if (high) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface
    Row(verticalAlignment = Alignment.CenterVertically) {
        MIcon(R.drawable.ic_m_flag, null, size = 14.dp, tint = color)
        Spacer(Modifier.width(4.dp))
        Text(label, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold, color = color, maxLines = 1)
    }
}

// ── Un ticket ───────────────────────────────────────────────────────────

/** Un geste du moment qui demande un mot avant de partir. */
private data class TicketAsk(val verdict: String, val title: String, val ask: AskFor) : java.io.Serializable

@Composable
fun TicketScreen(graph: AppGraph, route: Route.ProjectTicket) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val project = rememberProjectModel(graph, route.id)
    val vm: TicketViewModel = viewModel(key = "ticket|$session|${route.id}|${route.number}") { TicketViewModel(ProjectsDeps(graph), route.id, route.number) }
    LaunchedEffect(vm) { vm.gestures.said.collect { shell.toast(it) } }
    OnResume(vm, project = route.id) {
        vm.resume()
        project.resume()
    }
    // un geste abouti change la fiche (ses comptes, ce qui t'attend) : elle se relit
    LaunchedEffect(vm.revision) { if (vm.revision > 0) project.reload() }
    val now = rememberNow(wallMs = graph.clock::wallMs)
    // une fenêtre ou une feuille ouverte survit à une rotation (et ce qu'on y tape aussi)
    var asking by rememberSaveable(route.id, route.number) { mutableStateOf<TicketAsk?>(null) }
    var editing by rememberSaveable(route.id, route.number) { mutableStateOf(false) }
    // le ticket qui s'ouvre ne redit pas un refus d'avant
    FreshEntry(vm.gestures, TicketViewModel.HERE)
    val sheet = project.sheet.valueOrNull
    val e = vm.element.valueOrNull
    val asks = sheet?.todo?.any { it.kind == "ticket" && it.number == route.number && it.what == "question" } == true
    val pane = vm.pane.ifEmpty { e?.let { TicketPanes.first(it, asks) } ?: TicketPanes.DESCRIPTION }
    // aucun geste sur un ticket d'avant : il se relit au retour sur l'écran et après chaque geste
    val busy = vm.gestures.busy.isNotEmpty() || vm.stale
    SectionScaffold(
        topBar = { MikaTopBar(title = stringResource(R.string.proj_tab_tickets), nav = BarNav.BACK, subtitle = sheet?.project?.title) },
        bottomBar = {
            if (e != null && pane == TicketPanes.THREAD && e.more.can.note && e.line.veiled.isEmpty()) NoteBar(vm, asks, busy)
        },
    ) { modifier ->
        LoadBox(vm.element, vm::retry, modifier) { ticket ->
            Column(modifier) {
                TicketHead(ticket, now, busy, onSettle = { verdict, title, ask -> if (ask == AskFor.NOTHING) vm.settle(verdict) else asking = TicketAsk(verdict, title, ask) }, onEdit = { editing = true })
                val talk = ticket.more.thread.filter { it.kind != "change" }
                PaneTabs(
                    listOf(
                        Pane(TicketPanes.DESCRIPTION, stringResource(R.string.proj_pane_description)),
                        Pane(TicketPanes.PLAN, stringResource(R.string.proj_pane_plan)),
                        Pane(TicketPanes.THREAD, stringResource(R.string.proj_pane_thread), if (talk.isEmpty()) "" else talk.size.toString()),
                        Pane(TicketPanes.HISTORY, stringResource(R.string.proj_pane_history), vm.history?.valueOrNull?.items?.size?.toString().orEmpty()),
                        Pane(TicketPanes.INFOS, stringResource(R.string.proj_pane_infos)),
                    ),
                    pane,
                ) { vm.pane = it }
                Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    RefusalNote(vm.gestures.refusalAt(TicketViewModel.HERE))
                    StaleNote(vm.staleError, vm::reread)
                    val veiled = ticket.line.veiled.isNotEmpty()
                    when {
                        pane == TicketPanes.INFOS -> TicketInfos(ticket, sheet, now, shell, route.id)
                        pane == TicketPanes.HISTORY -> TicketHistory(vm, sheet?.rights?.work == true, now)
                        veiled -> EmptyNote(R.drawable.ic_m_lock, stringResource(R.string.proj_ticket_veiled), ticket.line.veiledLabel)
                        pane == TicketPanes.PLAN -> TicketPlan(ticket, asks) { vm.pane = TicketPanes.THREAD }
                        pane == TicketPanes.THREAD -> {
                            if (ticket.more.can.accept && ticket.line.outside) Hint(stringResource(R.string.proj_word_outside_ticket), R.drawable.ic_m_ticket)
                            if (talk.isEmpty()) Text(stringResource(R.string.proj_thread_none), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            for (n in talk) ThreadNoteView(n, now)
                        }
                        ticket.more.body.isBlank() -> Text(stringResource(R.string.proj_description_none), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        ticket.line.outside -> OutsideBlock(ticket.line.author, ticket.more.body)
                        else -> MdText(ticket.more.body)
                    }
                }
            }
        }
    }
    val notSent = stringResource(R.string.proj_not_sent)
    asking?.let { a ->
        AskDialog(
            title = "${a.title} — #${route.number}",
            lede = e?.line?.title.orEmpty(),
            label = askLabel(a.ask),
            placeholder = "",
            confirm = a.title,
            required = a.ask.required,
            max = 2000,
            danger = true,
            onDismiss = { asking = null },
            onConfirm = { reason ->
                // rien n'est parti (le ticket se relit à l'instant) : la fenêtre reste, avec ce qui est tapé, et on le dit
                if (vm.settle(a.verdict, reason)) asking = null else shell.toast(notSent)
            },
        )
    }
    if (editing && e != null) {
        TicketFormSheet(
            title = stringResource(R.string.proj_ticket_edit, route.number),
            sub = stringResource(R.string.proj_ticket_edit_sub),
            submit = stringResource(R.string.proj_save),
            list = sheet?.let { ticketList(it) },
            initial = TicketForm.of(e),
            editing = true,
            born = "",
            runner = vm.gestures,
            where = TicketViewModel.EDIT,
            onSubmit = vm::modify,
            onDismiss = { editing = false },
        )
    }
}

/** L'en-tête d'un ticket : son numéro et son titre, son étape, sa sorte, qui l'a ouvert ; puis les gestes du moment et « Modifier ». */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun TicketHead(e: EntryDetail, now: Long, busy: Boolean, onSettle: (verdict: String, title: String, ask: AskFor) -> Unit, onEdit: () -> Unit) {
    val line = e.line
    val can = e.more.can
    val tone = ticketTone(line)
    Column(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 8.dp)) {
        Row(verticalAlignment = Alignment.Top) {
            Text("#${line.number}", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.width(8.dp))
            Text(
                line.title.ifBlank { line.veiledLabel.ifBlank { stringResource(R.string.proj_ticket) } },
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.weight(1f).semantics { heading() },
            )
        }
        Gap(6.dp)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            StatePill(tone, line.statusLabel)
            KindChip(line.kindLabel)
            if (line.author.isNotBlank()) Text(stringResource(R.string.proj_opened_by, line.author), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(since(line.at, now), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (line.outside) OutsideMark()
        }
        if (can.validate || can.refuse || can.accept || can.dismiss || can.close || can.reopen || can.modify) {
            Gap(10.dp)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                val validate = stringResource(R.string.proj_do_validate_plan)
                val refuse = stringResource(R.string.proj_do_refuse)
                val accept = stringResource(R.string.proj_do_accept_ticket)
                val dismiss = stringResource(R.string.proj_do_dismiss)
                val close = stringResource(R.string.proj_do_close)
                val reopen = stringResource(R.string.proj_do_reopen)
                if (can.validate) Button(onClick = { onSettle("validate", validate, AskFor.NOTHING) }, enabled = !busy) { Text(validate) }
                if (can.accept) Button(onClick = { onSettle("accept", accept, AskFor.NOTHING) }, enabled = !busy) { Text(accept) }
                if (can.refuse) DangerButton(refuse, busy) { onSettle("refuse", refuse, AskFor.WRONG) }
                if (can.dismiss) DangerButton(dismiss, busy) { onSettle("dismiss", dismiss, if (can.dismissNeedsReason) AskFor.WHY else AskFor.WHY_OPTIONAL) }
                if (can.close) OutlinedButton(onClick = { onSettle("done", close, AskFor.NOTHING) }, enabled = !busy) { Text(close) }
                if (can.reopen) OutlinedButton(onClick = { onSettle("reopen", reopen, AskFor.NOTHING) }, enabled = !busy) { Text(reopen) }
                if (can.modify) {
                    OutlinedButton(onClick = onEdit, enabled = !busy) {
                        MIcon(R.drawable.ic_m_pen, null, size = 18.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.proj_edit))
                    }
                }
            }
        }
    }
}

@Composable
private fun DangerButton(label: String, busy: Boolean, onClick: () -> Unit) {
    OutlinedButton(onClick = onClick, enabled = !busy, colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error)) { Text(label) }
}

/** Son plan, en carte (ambre quand il attend ta validation) ; sans plan, pourquoi il n'y en a pas encore. */
@Composable
private fun TicketPlan(e: EntryDetail, asks: Boolean, onThread: () -> Unit) {
    val can = e.more.can
    if (e.more.planText.isNotBlank()) {
        PlanCard(stringResource(R.string.proj_her_plan), e.line.statusLabel, if (can.validate) StateTone.YOU else ticketTone(e.line), e.more.planText, waits = can.validate, number = e.line.plan)
        if (can.validate) Hint(stringResource(R.string.proj_word_ticket_plan))
        return
    }
    EmptyNote(
        R.drawable.ic_m_plan,
        stringResource(R.string.proj_plan_none),
        when {
            asks -> stringResource(R.string.proj_plan_none_asks)
            can.accept -> stringResource(R.string.proj_plan_none_accept)
            !e.line.open -> e.line.statusLabel
            else -> stringResource(R.string.proj_plan_none_later)
        },
    ) {
        if (asks) OutlinedButton(onClick = onThread) { Text(stringResource(R.string.proj_read_question)) }
    }
}

/** Une note d'un fil : venue d'ailleurs (citée, en texte brut), un changement (une ligne), ou une bulle — elle, toi, une autre personne. */
@Composable
internal fun ThreadNoteView(n: ThreadNote, now: Long) {
    val at = since(n.at, now)
    when {
        n.outside -> OutsideBlock(listOf(n.author, at).filter { it.isNotBlank() }.joinToString(" · "), n.text)
        n.kind == "change" -> Row(verticalAlignment = Alignment.CenterVertically) {
            MIcon(R.drawable.ic_m_check, null, size = 14.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.width(6.dp))
            Text("${n.author} : ${n.text}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
            Text(at, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        else -> Bubble(
            n.authorKind,
            (if (n.authorKind == "you") stringResource(R.string.proj_you) else n.author) + (if (n.kind != "note" && n.kindLabel.isNotBlank()) " · ${n.kindLabel}" else ""),
            at,
            n.text,
        )
    }
}

/** Le champ du fil, en bas : une note ; sur un ticket qui pose une question, sa réponse. */
@Composable
private fun NoteBar(vm: TicketViewModel, asks: Boolean, busy: Boolean) {
    Surface(color = MaterialTheme.colorScheme.surface, tonalElevation = 3.dp, shadowElevation = 6.dp) {
        Row(Modifier.fillMaxWidth().navigationBarsPadding().imePadding().padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.Bottom) {
            OutlinedTextField(
                value = vm.note,
                onValueChange = { vm.note = it },
                placeholder = { Text(stringResource(if (asks) R.string.proj_note_answer_hint else R.string.proj_note_hint)) },
                maxLines = 5,
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(8.dp))
            val label = stringResource(if (asks) R.string.proj_answer else R.string.proj_note_add)
            FilledIconButton(onClick = vm::sendNote, enabled = vm.note.isNotBlank() && !busy) { MIcon(R.drawable.ic_m_send, label) }
        }
    }
}

/** L'Historique : l'histoire de ses étapes (des faits, rejoués par le serveur), mêlée à ce qui est arrivé à ses objectifs. */
@Composable
private fun TicketHistory(vm: TicketViewModel, work: Boolean, now: Long) {
    LaunchedEffect(vm, work) { if (vm.history == null) vm.loadStory(work) }
    when (val load: Load<EntryHistory>? = vm.history) {
        null, Load.Loading -> Box(Modifier.fillMaxWidth().padding(16.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        is Load.Failed -> {
            RefusalNote(load.error.message)
            OutlinedButton(onClick = { vm.loadStory(work) }) { Text(stringResource(R.string.retry)) }
        }
        is Load.Ready -> {
            if (load.value.cut) Hint(stringResource(R.string.proj_history_cut))
            val rows = storyRows(load.value, vm.around)
            Column {
                rows.forEachIndexed { i, r ->
                    TimelineRow(r.tone, i == rows.lastIndex) {
                        Text(moment(r.at, now), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(r.text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f, fill = false))
                            if (r.sha.isNotBlank()) {
                                Spacer(Modifier.width(6.dp))
                                Code(r.sha)
                            }
                        }
                        if (r.outside) {
                            Gap(3.dp)
                            OutsideMark()
                        }
                    }
                }
            }
        }
    }
}

/**
 * Le volet « Infos » : son parcours en six étapes, telles que le serveur les sert (`journey` : passée, en cours, à
 * venir, sautée — rien n'est déduit ici), ses propriétés, et ce qui lui est lié : l'objectif qui le tient, sa pull
 * request avec son statut, son issue chez l'hôte.
 */
@Composable
private fun TicketInfos(e: EntryDetail, sheet: Sheet?, now: Long, shell: Shell, project: Int) {
    val line = e.line
    val tone = ticketTone(line)
    Column {
        e.more.journey?.let { j ->
            SideTitle(stringResource(R.string.proj_side_journey))
            if (j.ended == "dismissed") {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    MIcon(R.drawable.ic_m_x, null, size = 16.dp, tint = MaterialTheme.colorScheme.error)
                    Spacer(Modifier.width(6.dp))
                    Text(j.endedLabel.ifBlank { line.statusLabel }, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.error)
                }
                Gap(6.dp)
            }
            j.steps.forEachIndexed { i, s ->
                val here = s.state == "current"
                val color = when (s.state) {
                    "done" -> toneOf(StateTone.DONE).ink
                    "current" -> toneOf(tone).ink
                    else -> MaterialTheme.colorScheme.outline
                }
                Row(Modifier.padding(vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        Modifier.size(26.dp).then(if (s.state == "done") Modifier.background(color, CircleShape) else Modifier.border(2.dp, color, CircleShape)),
                        contentAlignment = Alignment.Center,
                    ) {
                        when (s.state) {
                            "done" -> MIcon(R.drawable.ic_m_check, s.stateLabel, size = 14.dp, tint = MaterialTheme.colorScheme.surface)
                            "skipped" -> MIcon(R.drawable.ic_m_minus, s.stateLabel, size = 14.dp, tint = color)
                            else -> Text((i + 1).toString(), style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold, color = color)
                        }
                    }
                    Spacer(Modifier.width(12.dp))
                    Column {
                        Text(
                            s.label,
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = if (here) FontWeight.Bold else FontWeight.Normal,
                            color = if (s.state == "todo" || s.state == "skipped") MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface,
                        )
                        val note = stepNote(j, s, line.handLabel)
                        if (note.isNotBlank()) Text(note, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            if (j.skipsLabel.isNotBlank()) {
                Gap(6.dp)
                Hint(j.skipsLabel)
            }
        }
        SideTitle(stringResource(R.string.proj_side_brief))
        Fact(stringResource(R.string.proj_fact_hand), line.handLabel)
        if (line.priorityLabel.isNotBlank()) Fact(stringResource(R.string.proj_fact_priority)) { PriorityMark(line.priorityLabel, line.priority == "high" || line.priority == "urgent") }
        Fact(stringResource(R.string.proj_fact_kind), line.kindLabel)
        Fact(stringResource(R.string.proj_fact_opened_by), line.author)
        Fact(stringResource(R.string.proj_fact_updated), moment(if (line.updatedAt > 0) line.updatedAt else line.at, now))
        SideTitle(stringResource(R.string.proj_side_linked))
        val linked = e.more.linked
        val o = linked.objective
        val pull = linked.pull
        if (o == null && pull == null && line.pull == 0 && line.issue == 0) {
            Text(stringResource(R.string.proj_linked_none), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (o != null) {
                LinkedLine(
                    R.drawable.ic_m_target, objectiveTone(o.status), o.text, stringResource(R.string.proj_goal_n, o.id),
                    pill = { StatePill(objectiveTone(o.status), o.statusLabel) },
                    onClick = { shell.navigate(Route.ProjectGoal(project, "o${o.id}")) },
                )
            }
            if (pull != null) {
                // la pull request liée, avec son statut : son état, la CI, la relecture de l'objectif qui la porte
                val review = sheet?.objectives?.firstOrNull { it.id == o?.id }?.review
                PullCard(pull, linked.checks, review, now) { shell.navigate(pullPage(project, pull.number, o?.id ?: 0)) }
            } else if (line.pull != 0) {
                LinkedLine(R.drawable.ic_m_pr, StateTone.WORK, stringResource(R.string.proj_pull_n, line.pull), stringResource(R.string.proj_pull_own)) {
                    shell.navigate(pullPage(project, line.pull, 0))
                }
            }
            if (line.issue != 0) {
                val issueTone = if (line.issueState == "closed") StateTone.DONE else StateTone.WAIT
                LinkedLine(
                    R.drawable.ic_m_issue, issueTone, stringResource(R.string.proj_issue_n, line.issue), stringResource(R.string.proj_at_host),
                    pill = if (line.issueStateLabel.isNotBlank()) ({ StatePill(issueTone, line.issueStateLabel) }) else null,
                    onClick = { shell.navigate(Route.ProjectCode(project, CodePages.ISSUE, line.issue.toString())) },
                )
            }
        }
    }
}
