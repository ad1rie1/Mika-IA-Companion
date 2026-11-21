package fr.qwartz.mika.ui.projects

import androidx.annotation.DrawableRes
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.PrimaryScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.projects.CodePages
import fr.qwartz.mika.data.moi.projects.CodeTabs
import fr.qwartz.mika.data.moi.projects.Linked
import fr.qwartz.mika.data.moi.projects.Listing
import fr.qwartz.mika.data.moi.projects.Sheet
import fr.qwartz.mika.data.moi.projects.SheetTabs
import fr.qwartz.mika.data.moi.projects.StateTone
import fr.qwartz.mika.data.moi.projects.checksTone
import fr.qwartz.mika.data.moi.projects.doneOf
import fr.qwartz.mika.data.moi.projects.instructionBy
import fr.qwartz.mika.data.moi.projects.liveMilestones
import fr.qwartz.mika.data.moi.projects.milestoneTones
import fr.qwartz.mika.data.moi.projects.nextAbout
import fr.qwartz.mika.data.moi.projects.nextWhen
import fr.qwartz.mika.data.moi.projects.objectiveTone
import fr.qwartz.mika.data.moi.projects.othersWaiting
import fr.qwartz.mika.data.moi.projects.planState
import fr.qwartz.mika.data.moi.projects.plural
import fr.qwartz.mika.data.moi.projects.projectTone
import fr.qwartz.mika.data.moi.projects.pullTone
import fr.qwartz.mika.data.moi.projects.reachedCount
import fr.qwartz.mika.data.moi.projects.since
import fr.qwartz.mika.data.moi.projects.ticketList
import fr.qwartz.mika.data.moi.projects.waitingIcon
import fr.qwartz.mika.data.moi.projects.waitingKey
import fr.qwartz.mika.data.moi.projects.whose
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.AskDialog
import fr.qwartz.mika.ui.shell.BarAction
import fr.qwartz.mika.ui.shell.BarMenu
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MenuEntry
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.theme.mika

/*
 * La fiche d'un projet (ADR 0296), en page : son en-tête (son titre, son état, pour qui ; piloter : donner une consigne,
 * lancer maintenant, mettre en pause, reprendre), ses onglets qui défilent en largeur, puis l'onglet montré. Pas de page
 * qui empile tout : la Vue d'ensemble est faite de cartes courtes, et chaque liste ouvre son détail en page.
 *
 * Un onglet se branche dans [SheetTabContent] : la Vue d'ensemble, [ObjectivesTab], [TicketsTab], [CodeTab], [DocsTab],
 * [ActivityTab], [LinksTab], [ListsTab] ; « Modifier le projet » (ses réglages, la pause, l'archiver) dans [projectMenu].
 */

/** Le modèle d'un projet, que ses écrans partagent (la fiche, un objectif, un ticket) : un par projet et par session. */
@Composable
internal fun rememberProjectModel(graph: AppGraph, id: Int): ProjectViewModel {
    val session = rememberSessionKey(graph)
    return viewModel(key = "project|$session|$id") { ProjectViewModel(ProjectsDeps(graph), id) }
}

@Composable
fun ProjectScreen(graph: AppGraph, route: Route.Project) {
    val shell = LocalShell.current
    val vm = rememberProjectModel(graph, route.id)
    LaunchedEffect(vm) { vm.gestures.said.collect { shell.toast(it) } }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(vm, lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) { vm.resume() }
    }
    val now = rememberNow(wallMs = graph.clock::wallMs)
    var instructing by remember { mutableStateOf(false) }
    var launching by remember { mutableStateOf(false) }
    var addingGoal by remember { mutableStateOf(false) }
    var newTicket by remember { mutableStateOf(false) }
    val sheet = vm.sheet.valueOrNull
    val tab = sheet?.let { SheetTabs.shown(it, route.tab) } ?: route.tab
    SectionScaffold(
        topBar = { ProjectTopBar(route.id, sheet, tab, vm.gestures.busy.isNotEmpty(), onInstruct = { instructing = true }, onLaunch = { launching = true }, onPause = { vm.pilot(it) }) },
    ) { modifier ->
        LoadBox(vm.sheet, vm::retry, modifier) { s ->
            Column(modifier) {
                RefusalNote(vm.gestures.refusalAt(ProjectViewModel.TOP), Modifier.padding(horizontal = 12.dp, vertical = 6.dp))
                PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::pull, modifier = Modifier.fillMaxSize()) {
                    SheetTabContent(tab, SheetTabs.sub(route.tab), graph, vm, s, now, onAddGoal = { addingGoal = true }, onNewTicket = { newTicket = true })
                }
            }
        }
    }
    if (instructing) {
        AskDialog(
            title = stringResource(R.string.proj_pilot_instruct),
            lede = stringResource(R.string.proj_pilot_instruct_lede),
            label = stringResource(R.string.proj_pilot_instruct_label),
            placeholder = "",
            confirm = stringResource(R.string.proj_pilot_instruct_ok),
            required = true,
            max = 2000,
            danger = false,
            onDismiss = { instructing = false },
            onConfirm = { text ->
                instructing = false
                vm.pilot("instruct", text)
            },
        )
    }
    if (launching) {
        AlertDialog(
            onDismissRequest = { launching = false },
            title = { Text(stringResource(R.string.proj_pilot_now_title)) },
            text = { Text(stringResource(R.string.proj_pilot_now_text)) },
            confirmButton = {
                TextButton(onClick = {
                    launching = false
                    vm.pilot("now")
                }) { Text(stringResource(R.string.proj_pilot_now)) }
            },
            dismissButton = { TextButton(onClick = { launching = false }) { Text(stringResource(R.string.cancel)) } },
        )
    }
    if (sheet != null && addingGoal) GoalFormSheet(vm, sheet, null) { addingGoal = false }
    if (sheet != null && newTicket) {
        TicketFormSheet(
            title = stringResource(R.string.proj_ticket_new),
            sub = sheet.project.title,
            submit = stringResource(R.string.proj_ticket_open),
            list = ticketList(sheet),
            initial = fr.qwartz.mika.data.moi.projects.TicketForm.fresh(ticketList(sheet)),
            editing = false,
            born = sheet.rights.ticketBorn,
            runner = vm.gestures,
            where = ProjectViewModel.TICKET_NEW,
            onSubmit = vm::openTicket,
            onDismiss = { newTicket = false },
        )
    }
}

/**
 * Ce que le menu « ⋮ » de la fiche offre : « Modifier le projet » — ses réglages, le mettre en pause, l'archiver — pour
 * qui change son cadre (`rights.frame`) ; pour qui ne fait que lire son détail, « Voir ses réglages » : la même page,
 * où rien ne se saisit. Rien sans le détail.
 */
@Composable
internal fun projectMenu(sheet: Sheet, onSettings: () -> Unit): List<MenuEntry> =
    if (!sheet.rights.detail) {
        emptyList()
    } else {
        listOf(MenuEntry(stringResource(if (sheet.rights.frame) R.string.proj_set_title else R.string.proj_set_see), R.drawable.ic_m_settings, onSettings))
    }

/** Le nom d'un onglet de la fiche. */
@Composable
internal fun tabLabel(tab: String): String = stringResource(
    when (tab) {
        SheetTabs.OBJECTIVES -> R.string.proj_tab_objectives
        SheetTabs.TICKETS -> R.string.proj_tab_tickets
        SheetTabs.CODE -> R.string.proj_tab_code
        SheetTabs.DOCS -> R.string.proj_tab_docs
        SheetTabs.ACTIVITY -> R.string.proj_tab_activity
        SheetTabs.LINKS -> R.string.proj_tab_links
        SheetTabs.LISTS -> R.string.proj_tab_lists
        else -> R.string.proj_tab_overview
    },
)

/**
 * L'en-tête de la fiche : la flèche, le titre du projet, son état et pour qui ; à droite piloter — seulement avec le
 * droit servi (`rights.pilot`) — ; dessous, ses onglets, qui défilent en largeur, avec leurs comptes.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ProjectTopBar(
    id: Int,
    sheet: Sheet?,
    tab: String,
    busy: Boolean,
    onInstruct: () -> Unit,
    onLaunch: () -> Unit,
    onPause: (String) -> Unit,
) {
    val shell = LocalShell.current
    val p = sheet?.project
    Column {
        MikaTopBar(
            title = p?.title ?: stringResource(R.string.proj_project),
            nav = BarNav.BACK,
            subtitle = p?.let { listOf(planState(it)?.second ?: it.statusLabel, whose(it)).filter { s -> s.isNotBlank() }.joinToString(" · ") },
            actions = {
                if (sheet != null && sheet.rights.pilot) {
                    val paused = sheet.project.status == "paused"
                    BarAction(R.drawable.ic_m_pen, stringResource(R.string.proj_pilot_instruct), { if (!busy) onInstruct() })
                    BarAction(R.drawable.ic_m_play, stringResource(R.string.proj_pilot_now), { if (!busy) onLaunch() })
                    if (paused) {
                        BarAction(R.drawable.ic_m_refresh, stringResource(R.string.proj_pilot_resume), { if (!busy) onPause("resume") })
                    } else {
                        BarAction(R.drawable.ic_m_pause, stringResource(R.string.proj_pilot_pause), { if (!busy) onPause("pause") })
                    }
                }
                if (sheet != null) BarMenu(projectMenu(sheet) { shell.navigate(Route.ProjectPage(id, SheetPages.SETTINGS)) })
            },
        )
        if (sheet != null) {
            val tabs = SheetTabs.of(sheet)
            val counts = mapOf(
                SheetTabs.OBJECTIVES to sheet.objectives.count { it.status != "done" },
                SheetTabs.TICKETS to (ticketList(sheet)?.living ?: 0),
            )
            PrimaryScrollableTabRow(selectedTabIndex = tabs.indexOf(tab).coerceAtLeast(0), edgePadding = 8.dp) {
                for (t in tabs) {
                    Tab(
                        selected = t == tab,
                        onClick = { if (t != tab) shell.replace(Route.Project(id, t)) },
                        text = {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(tabLabel(t), maxLines = 1)
                                val n = counts[t] ?: 0
                                if (n > 0) {
                                    Spacer(Modifier.width(6.dp))
                                    CountChip(n.toString())
                                }
                            }
                        },
                    )
                }
            }
        }
    }
}

/**
 * L'onglet montré : sa vue reçoit le modèle du projet ([vm] : la fiche lue, ses gestes), la fiche ([sheet] : ses droits)
 * et, si son adresse en nomme un, son volet ([sub] : `code/pulls`, `documentation/images`, `listes/<liste>`).
 */
@Composable
private fun SheetTabContent(
    tab: String,
    sub: String,
    graph: AppGraph,
    vm: ProjectViewModel,
    sheet: Sheet,
    now: Long,
    onAddGoal: () -> Unit,
    onNewTicket: () -> Unit,
) {
    when (tab) {
        SheetTabs.OVERVIEW -> OverviewTab(graph, vm, sheet, now, onAddGoal)
        SheetTabs.OBJECTIVES -> ObjectivesTab(vm, sheet, now, onAddGoal)
        SheetTabs.TICKETS -> TicketsTab(vm, sheet, now, onNewTicket)
        SheetTabs.CODE -> CodeTab(graph, vm, sheet, now, sub)
        SheetTabs.DOCS -> DocsTab(graph, vm, sheet, now, sub)
        SheetTabs.ACTIVITY -> ActivityTab(graph, vm, sheet, now, sub)
        SheetTabs.LINKS -> LinksTab(vm, sheet, now, sub)
        SheetTabs.LISTS -> ListsTab(graph, vm, sheet, now, sub)
        else -> OverviewTab(graph, vm, sheet, now, onAddGoal)
    }
}

// ── La Vue d'ensemble ───────────────────────────────────────────────────

/** Les couleurs des six étapes du parcours d'un ticket, dans la barre de leur répartition. */
private val STAGE_COLORS = listOf(Color(0xFF64748B), Color(0xFF1565D8), Color(0xFFB45309), Color(0xFF7C3AED), Color(0xFF0F766E), Color(0xFF1B7F3B))

/**
 * La Vue d'ensemble : des cartes courtes, sans rien d'imbriqué — « À toi », où il en est, ses objectifs et leurs barres
 * de jalons, son code, ses tickets par étape, son prochain passage, ses dépendances. Chacune mène à son onglet.
 */
@Composable
private fun OverviewTab(graph: AppGraph, vm: ProjectViewModel, sheet: Sheet, now: Long, onAddGoal: () -> Unit) {
    val shell = LocalShell.current
    val section = rememberProjectsModel(graph)
    val p = sheet.project
    val go: (String) -> Unit = { shell.replace(Route.Project(p.id, it)) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        YoursCard(sheet, now) {
            section.showOnly(p.id)
            shell.navigate(Route.Projects(ProjectsTabs.TODO))
        }
        if (!sheet.rights.detail) {
            OverviewCard(R.drawable.ic_m_lock, stringResource(R.string.proj_see_only_title)) {
                Text(p.description.ifBlank { stringResource(R.string.proj_see_only_what) }, style = MaterialTheme.typography.bodyMedium)
                Gap(6.dp)
                Text(stringResource(R.string.proj_see_only_more), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            return@Column
        }
        // où il en est : son dernier compte rendu, à elle
        OverviewCard(R.drawable.ic_m_sparkle, stringResource(R.string.proj_card_where), container = mika.soft, border = mika.line) {
            if (p.lastRun > 0) {
                Text(since(p.lastRun, now), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Gap(4.dp)
            }
            Text(p.where.ifBlank { stringResource(R.string.proj_where_none) }, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            if (p.description.isNotBlank()) {
                Gap(6.dp)
                Text(p.description, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 4, overflow = TextOverflow.Ellipsis)
            }
        }
        // ses objectifs : ceux en cours d'abord, quatre au plus
        val objectives = sheet.objectives
        OverviewCard(
            R.drawable.ic_m_target,
            stringResource(R.string.proj_tab_objectives),
            link = doneOf(objectives.count { it.status == "done" }, objectives.size),
            onLink = { go(SheetTabs.OBJECTIVES) },
        ) {
            val shown = (objectives.filter { it.status != "done" } + objectives.filter { it.status == "done" }).take(4)
            if (shown.isEmpty()) {
                Text(stringResource(R.string.proj_goals_none), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (sheet.rights.edit) {
                    Gap(8.dp)
                    OutlinedButton(onClick = onAddGoal) {
                        MIcon(R.drawable.ic_m_plus, null, size = 18.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.proj_goal_add))
                    }
                }
            }
            for (o in shown) {
                Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).clickable { shell.navigate(Route.ProjectGoal(p.id, "o${o.id}")) }.padding(vertical = 6.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(o.text, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                        Spacer(Modifier.width(8.dp))
                        StatePill(objectiveTone(o.status), o.statusLabel)
                    }
                    Gap(6.dp)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        MilestoneBar(milestoneTones(o), Modifier.weight(1f))
                        Spacer(Modifier.width(10.dp))
                        val live = liveMilestones(o).size
                        Text(
                            if (live > 0) "${reachedCount(o)} / ${plural(live, "jalon", "jalons")}" else stringResource(R.string.proj_no_milestone),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
        // son code : ses pull requests ouvertes et leur état, son dernier commit
        OverviewCard(R.drawable.ic_m_code, stringResource(R.string.proj_tab_code), link = stringResource(R.string.proj_pulls), onLink = { go(CodeTabs.tab(CodeTabs.PULLS)) }) {
            val pulls = objectives.filter { it.pull?.state == "open" }
            for (o in pulls) {
                val pull = o.pull ?: continue
                MiniRow(R.drawable.ic_m_pr, pullTone(pull.state), pull.title.ifBlank { o.text }, listOf(stringResource(R.string.proj_number, pull.number), since(pull.at, now)).filter { it.isNotBlank() }.joinToString(" · "), onClick = { shell.navigate(pullPage(p.id, pull.number, o.id)) }) {
                    StatePill(o.checks?.let { checksTone(it.state) } ?: pullTone(pull.state), pull.stateLabel)
                }
            }
            val commit = sheet.repo?.commit
            when {
                commit != null -> Row(
                    Modifier.clip(RoundedCornerShape(8.dp)).clickable { shell.navigate(Route.ProjectCode(p.id, CodePages.COMMIT, commit.sha)) }.padding(top = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Code(commit.short)
                    Spacer(Modifier.width(8.dp))
                    Text(commit.title, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                    if (commit.outside) {
                        Spacer(Modifier.width(6.dp))
                        OutsideMark()
                    }
                    Spacer(Modifier.width(8.dp))
                    Text(since(commit.at, now), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                }
                pulls.isEmpty() -> Text(stringResource(R.string.proj_pulls_none), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        // ses tickets : leur répartition par étape du parcours, en une barre
        val tickets = ticketList(sheet)
        OverviewCard(R.drawable.ic_m_ticket, stringResource(R.string.proj_tab_tickets), link = plural(tickets?.living ?: 0, "ouvert", "ouverts"), onLink = { go(SheetTabs.TICKETS) }) {
            TicketStages(tickets)
        }
        // son prochain passage : daté par le moteur, jamais estimé
        val next = sheet.next
        OverviewCard(
            R.drawable.ic_m_clock,
            stringResource(R.string.proj_card_next),
            link = stringResource(R.string.proj_tab_activity),
            onLink = if (sheet.rights.work) ({ go(SheetTabs.ACTIVITY) }) else null,
        ) {
            Text(next?.let { nextWhen(it, now) }?.ifBlank { null } ?: p.statusLabel, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text(
                next?.let { nextAbout(it) }?.ifBlank { null }
                    ?: if (p.lastRun > 0) stringResource(R.string.proj_last_pass, since(p.lastRun, now)) else stringResource(R.string.proj_no_pass),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            sheet.rhythm?.summary?.takeIf { it.isNotBlank() }?.let { NoteLine(R.drawable.ic_m_calendar, it) }
            for (c in sheet.instructions) {
                NoteLine(
                    if (c.veiled) R.drawable.ic_m_lock else R.drawable.ic_m_pen,
                    "${instructionBy(c)} : " + (if (c.veiled) c.text else "« ${c.text} »") + since(c.at, now).let { if (it.isBlank()) "" else " · $it" },
                )
            }
            for (m in sheet.missions) {
                MiniRow(
                    R.drawable.ic_m_refresh, StateTone.WORK, m.text,
                    (listOf(m.cadenceLabel) + m.on.map { it.label }).filter { it.isNotBlank() }.joinToString(" · "),
                    onClick = { shell.navigate(Route.ProjectGoal(p.id, "m${m.id}")) },
                )
            }
        }
        // ses dépendances : de quoi il dépend, qui dépend de lui
        val links = sheet.links
        OverviewCard(
            R.drawable.ic_m_link,
            links?.labels?.title?.ifBlank { null } ?: stringResource(R.string.proj_tab_links),
            link = stringResource(R.string.proj_links_schema),
            onLink = { go(SheetTabs.LINKS) },
        ) {
            if (links == null || (links.reads.isEmpty() && links.readers.isEmpty())) {
                Text(stringResource(R.string.proj_links_none), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                LinkedNames(links.labels.reads.ifBlank { stringResource(R.string.proj_links_reads) }, links.reads)
                Gap(6.dp)
                LinkedNames(links.labels.readers.ifBlank { stringResource(R.string.proj_links_readers) }, links.readers)
            }
        }
    }
}

/** « À toi » : combien de choses attendent la personne dans ce projet, les trois premières, et ce qui attend quelqu'un d'autre. */
@Composable
private fun YoursCard(sheet: Sheet, now: Long, onAll: () -> Unit) {
    val shell = LocalShell.current
    val mine = sheet.todo.filter { it.mine }
    val theirs = sheet.todo.filterNot { it.mine }
    val c = toneOf(StateTone.YOU)
    OverviewCard(
        R.drawable.ic_m_inbox,
        stringResource(R.string.proj_card_yours),
        link = stringResource(R.string.proj_see_all),
        onLink = if (mine.isNotEmpty()) onAll else null,
        container = if (mine.isNotEmpty()) c.container.copy(alpha = 0.5f) else MaterialTheme.colorScheme.surface,
        border = if (mine.isNotEmpty()) c.bar.copy(alpha = 0.5f) else MaterialTheme.colorScheme.outlineVariant,
    ) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(mine.size.toString(), style = MaterialTheme.typography.displaySmall, fontWeight = FontWeight.Bold, color = if (mine.isNotEmpty()) c.ink else MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.width(10.dp))
            Text(
                stringResource(
                    when (mine.size) {
                        0 -> R.string.proj_yours_none
                        1 -> R.string.proj_yours_one
                        else -> R.string.proj_yours_many
                    },
                ),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(bottom = 6.dp),
            )
        }
        for (w in mine.take(3)) {
            MiniRow(
                projectIcon(waitingIcon(w.kind, w.what)), StateTone.YOU, w.about,
                listOf(w.kindLabel, since(w.since, now)).filter { it.isNotBlank() }.joinToString(" · "),
                onClick = { shell.navigate(Route.ProjectTodo(w.project, waitingKey(w))) },
            )
        }
        if (mine.size > 3) {
            Text(
                stringResource(R.string.proj_yours_more, mine.size - 3),
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.clip(RoundedCornerShape(8.dp)).clickable(onClick = onAll).padding(vertical = 6.dp),
            )
        }
        if (theirs.isNotEmpty()) {
            NoteLine(R.drawable.ic_m_clock, othersWaiting(theirs))
        }
    }
}

/** Une petite ligne d'une carte : sa tuile, un titre, une ligne sous lui, et sa pastille au bout. */
@Composable
internal fun MiniRow(
    @DrawableRes icon: Int,
    tone: StateTone,
    title: String,
    sub: String,
    onClick: (() -> Unit)? = null,
    pill: (@Composable () -> Unit)? = null,
) {
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier).padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Tile(icon, tone, 32.dp)
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium, maxLines = 2, overflow = TextOverflow.Ellipsis)
            if (sub.isNotBlank()) Text(sub, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        if (pill != null) {
            Spacer(Modifier.width(8.dp))
            pill()
        }
    }
}

/** Une ligne de note dans une carte : une petite icône, puis ses mots. */
@Composable
internal fun NoteLine(@DrawableRes icon: Int, text: String) {
    Row(Modifier.padding(top = 6.dp), verticalAlignment = Alignment.Top) {
        MIcon(icon, null, size = 14.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 2.dp))
        Spacer(Modifier.width(6.dp))
        Text(text, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** La répartition des tickets par étape du parcours : les six étapes, comptées et nommées par le serveur (`journey`). */
@Composable
private fun TicketStages(list: Listing?) {
    val stages = list?.journey.orEmpty()
    if (list == null || list.total == 0 || stages.isEmpty()) {
        Text(stringResource(R.string.proj_tickets_none), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        return
    }
    Row(Modifier.fillMaxWidth().height(10.dp).clip(RoundedCornerShape(50)), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
        stages.forEachIndexed { i, s ->
            if (s.count > 0) Box(Modifier.weight(s.count.toFloat()).height(10.dp).background(STAGE_COLORS[i % STAGE_COLORS.size]))
        }
    }
    Gap(8.dp)
    stages.forEachIndexed { i, s ->
        Row(Modifier.padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).background(STAGE_COLORS[i % STAGE_COLORS.size], CircleShape))
            Spacer(Modifier.width(8.dp))
            Text(
                s.label,
                style = MaterialTheme.typography.bodySmall,
                color = if (s.count > 0) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.weight(1f),
            )
            Text(s.count.toString(), style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.SemiBold)
        }
    }
}

/** Des projets liés, nommés seulement si elle les voit. */
@Composable
private fun LinkedNames(label: String, items: List<Linked>) {
    val hidden = stringResource(R.string.proj_hidden_project)
    Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    Text(
        items.joinToString(", ") { if (it.visible) it.title else hidden }.ifBlank { stringResource(R.string.proj_links_no_project) },
        style = MaterialTheme.typography.bodyMedium,
    )
}
