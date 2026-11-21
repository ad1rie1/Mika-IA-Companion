package fr.qwartz.mika.ui.projects

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.projects.ActivityDays
import fr.qwartz.mika.data.moi.projects.ActivityTabs
import fr.qwartz.mika.data.moi.projects.CodePages
import fr.qwartz.mika.data.moi.projects.Coded
import fr.qwartz.mika.data.moi.projects.Happening
import fr.qwartz.mika.data.moi.projects.HappeningTarget
import fr.qwartz.mika.data.moi.projects.NotebookNote
import fr.qwartz.mika.data.moi.projects.Run
import fr.qwartz.mika.data.moi.projects.Sheet
import fr.qwartz.mika.data.moi.projects.StateTone
import fr.qwartz.mika.data.moi.projects.byDay
import fr.qwartz.mika.data.moi.projects.dayCount
import fr.qwartz.mika.data.moi.projects.duration
import fr.qwartz.mika.data.moi.projects.happeningIcon
import fr.qwartz.mika.data.moi.projects.happeningTarget
import fr.qwartz.mika.data.moi.projects.happeningTone
import fr.qwartz.mika.data.moi.projects.moment
import fr.qwartz.mika.data.moi.projects.nextAbout
import fr.qwartz.mika.data.moi.projects.nextWhen
import fr.qwartz.mika.data.moi.projects.objectiveTone
import fr.qwartz.mika.data.moi.projects.plural
import fr.qwartz.mika.data.moi.projects.runIcon
import fr.qwartz.mika.data.moi.projects.runTitle
import fr.qwartz.mika.data.moi.projects.runTone
import fr.qwartz.mika.data.moi.projects.since
import fr.qwartz.mika.data.moi.projects.stepsSpent
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.Shell
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.theme.mika

/*
 * L'onglet Activité d'une fiche (ADR 0296), d'après la maquette validée en largeur de téléphone : trois volets en
 * pastilles — **Fil** (ce qui s'est passé, par jour ; ses filtres par sorte et par objectif ; la suite à la demande ;
 * « Infos » : les trente derniers jours, le prochain passage, qui a fait quoi), **Exécutions** (une ligne de temps, et
 * le détail de l'une en page : son compte rendu, ce qu'elle a fait pas à pas) et **Carnet** (ses notes, par objectif).
 * Les sortes, les verdicts et leurs mots sont ceux du serveur. **Ce qu'il marque comme venu d'ailleurs reste du texte
 * brut**, présenté comme tel : le titre d'une ligne, ce que visait un pas.
 */

private const val PANE_FEED = "fil"
private const val PANE_INFOS = "infos"
private const val PANE_STEPS = "pas"

@Composable
internal fun ActivityTab(graph: AppGraph, vm: ProjectViewModel, sheet: Sheet, now: Long, sub: String) {
    val shell = LocalShell.current
    val activity = rememberActivityModel(graph, vm.id)
    val shown = ActivityTabs.of(sub)
    Toasts(activity.gestures)
    OnResume(activity) { activity.resume() }
    LaunchedEffect(activity, shown) { activity.show(shown) }
    LaunchedEffect(vm.refreshing) { if (vm.refreshing) activity.resume() }
    val totals = activity.totals.value
    Column(Modifier.fillMaxSize()) {
        ChipRow(
            listOf(
                Chip(ActivityTabs.FEED, stringResource(R.string.proj_act_tab_feed)),
                Chip(ActivityTabs.RUNS, stringResource(R.string.proj_act_tab_runs), totals?.runs),
                Chip(ActivityTabs.NOTEBOOK, stringResource(R.string.proj_act_tab_notebook), totals?.notes),
            ),
            selected = shown,
            onPick = { if (it != shown) shell.replace(Route.Project(vm.id, ActivityTabs.tab(it))) },
            modifier = Modifier.padding(top = 4.dp),
        )
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        when (shown) {
            ActivityTabs.RUNS -> RunsPane(activity, shell, now)
            ActivityTabs.NOTEBOOK -> NotebookPane(activity, sheet, now)
            else -> FeedPane(activity, sheet, shell, now)
        }
    }
}

// ── Le fil ──────────────────────────────────────────────────────────────

@Composable
private fun FeedPane(activity: ActivityViewModel, sheet: Sheet, shell: Shell, now: Long) {
    var pane by rememberSaveable { mutableStateOf(PANE_FEED) }
    LaunchedEffect(pane) { if (pane == PANE_INFOS) activity.openDays() }
    val counts = activity.filtered.value
    val kinds = activity.feed?.valueOrNull?.kinds ?: counts?.kinds?.map { Coded(it.code, it.label) }.orEmpty()
    Column(Modifier.fillMaxSize()) {
        ChipRow(
            listOf(Chip("", stringResource(R.string.proj_act_all), counts?.total)) + kinds.map { Chip(it.code, it.label.replaceFirstChar { c -> c.uppercase() }, counts?.totals?.get(it.code)) },
            selected = activity.kind,
            // une sorte se retire en la touchant de nouveau
            onPick = { activity.pickKind(if (it == activity.kind) "" else it) },
            modifier = Modifier.padding(top = 2.dp),
        )
        GoalPicker(sheet, activity.objective, Modifier.padding(horizontal = 12.dp), onPick = activity::pickObjective)
        PaneTabs(listOf(Pane(PANE_FEED, stringResource(R.string.proj_act_tab_feed)), Pane(PANE_INFOS, stringResource(R.string.proj_pane_infos))), pane) { pane = it }
        if (pane == PANE_INFOS) {
            StillPane { FeedInfos(activity, sheet, now) }
        } else {
            ListedPane(activity.feed, { activity.loadFeed() }) { _ ->
                val items = activity.items
                if (counts?.cut == true) item(key = "cut") { Hint(stringResource(R.string.proj_act_cut), modifier = Modifier.padding(12.dp)) }
                if (items.isEmpty()) {
                    item(key = "none") { EmptyNote(R.drawable.ic_m_history, stringResource(R.string.proj_act_none), stringResource(R.string.proj_act_none_sub)) }
                }
                for (day in byDay(items, { it.at }, now)) {
                    item(key = "d${day.label}") { GroupLabel(day.label) }
                    items(day.items, key = { "e${it.seq}" }) { x -> HappeningRow(x) { openHappening(shell, activity.id, x) } }
                }
                moreRow(activity.cursor > 0 && items.isNotEmpty(), activity.loadingMore, activity::more)
            }
        }
    }
}

/** Où mène une ligne du fil : la page de son exécution, de son commit, de sa pull request, de son ticket, de son objectif. */
private fun openHappening(shell: Shell, project: Int, x: Happening) {
    when (val to = happeningTarget(x)) {
        is HappeningTarget.ToRun -> shell.navigate(Route.ProjectPage(project, SheetPages.RUN, to.id))
        is HappeningTarget.ToCommit -> shell.navigate(Route.ProjectCode(project, CodePages.COMMIT, to.sha))
        is HappeningTarget.ToPull -> shell.navigate(pullPage(project, to.number, x.objective))
        is HappeningTarget.ToTicket -> shell.navigate(Route.ProjectTicket(project, to.number))
        is HappeningTarget.ToGoal -> shell.navigate(Route.ProjectGoal(project, "o${to.objective}"))
        HappeningTarget.Nowhere -> Unit
    }
}

/** Le filtre par objectif : « Tous les objectifs », ou l'un de ceux de la fiche (un objectif, une mission). */
@Composable
private fun GoalPicker(sheet: Sheet, picked: Int, modifier: Modifier = Modifier, onPick: (Int) -> Unit) {
    val goals = sheet.objectives.map { it.id to it.text } + sheet.missions.map { it.id to it.text }
    if (goals.isEmpty()) return
    var open by remember { mutableStateOf(false) }
    Box(modifier) {
        OutlinedButton(onClick = { open = true }) {
            MIcon(R.drawable.ic_m_target, null, size = 16.dp)
            Spacer(Modifier.width(6.dp))
            Text(
                goals.firstOrNull { it.first == picked }?.second ?: stringResource(R.string.proj_act_all_goals),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f, fill = false),
            )
            Spacer(Modifier.width(4.dp))
            MIcon(R.drawable.ic_m_chev_down, null, size = 14.dp)
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            DropdownMenuItem(text = { Text(stringResource(R.string.proj_act_all_goals)) }, onClick = {
                open = false
                onPick(0)
            })
            for ((id, text) in goals) {
                DropdownMenuItem(text = { Text(text, maxLines = 2, overflow = TextOverflow.Ellipsis) }, onClick = {
                    open = false
                    onPick(id)
                })
            }
        }
    }
}

/**
 * Une ligne du fil : son heure, la tuile de sa sorte, ce qui s'est passé, ce qui a été écrit dessous, son verdict, qui
 * l'a fait. Son titre se pose en texte brut ; venu d'ailleurs, il le dit.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun HappeningRow(x: Happening, onClick: () -> Unit) {
    val target = happeningTarget(x) != HappeningTarget.Nowhere
    Column(Modifier.fillMaxWidth().then(if (target) Modifier.clickable(onClick = onClick) else Modifier)) {
        Row(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.Top) {
            Text(MoiDates.clock(x.at), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.width(44.dp).padding(top = 8.dp))
            Tile(projectIcon(happeningIcon(x.kind)), happeningTone(x) ?: StateTone.WAIT, 32.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(x.title, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold, maxLines = 4, overflow = TextOverflow.Ellipsis)
                val under = listOf(x.sha.take(7), x.sub).filter { it.isNotBlank() }.joinToString(" · ")
                if (under.isNotBlank()) Text(under, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Gap(4.dp)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp), itemVerticalAlignment = Alignment.CenterVertically) {
                    if (x.outside) OutsideMark()
                    if (x.verdictLabel.isNotBlank()) StatePill(runTone(false, x.verdict), x.verdictLabel)
                    val about = when {
                        x.ticket > 0 -> "#${x.ticket}"
                        x.objective > 0 -> stringResource(R.string.proj_goal_n, x.objective).replaceFirstChar { it.lowercase() }
                        else -> ""
                    }
                    MetaText(listOf(x.author, about).filter { it.isNotBlank() }.joinToString(" · "))
                }
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    }
}

/** « Infos » du fil : ses trente derniers jours, son prochain passage, qui a fait quoi. */
@Composable
private fun FeedInfos(activity: ActivityViewModel, sheet: Sheet, now: Long) {
    SideTitle(stringResource(R.string.proj_act_side_days))
    when (val load = activity.days.load) {
        null, Load.Loading -> Muted(stringResource(R.string.proj_act_reading))
        is Load.Failed -> RefusalNote(load.error.message)
        is Load.Ready -> {
            val d = load.value
            Text(plural(d.total, "événement", "événements"), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Gap(6.dp)
            DaysChart(d, activity.kind)
            Gap(8.dp)
            for (k in d.kinds) Fact(k.label.replaceFirstChar { it.uppercase() }, (d.totals[k.code] ?: 0).toString())
            if (d.cut) Hint(stringResource(R.string.proj_act_days_cut))
            if (d.by.isNotEmpty()) {
                SideTitle(stringResource(R.string.proj_act_side_by))
                for (b in d.by) Fact(b.label.replaceFirstChar { it.uppercase() }, plural(b.count, "événement", "événements"))
            }
        }
    }
    SideTitle(stringResource(R.string.proj_card_next))
    val next = sheet.next
    Text(next?.let { nextWhen(it, now) }?.ifBlank { null } ?: sheet.project.statusLabel, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
    Muted(
        next?.let { nextAbout(it) }?.ifBlank { null }
            ?: if (sheet.project.lastRun > 0) stringResource(R.string.proj_last_pass, since(sheet.project.lastRun, now)) else stringResource(R.string.proj_no_pass),
    )
    sheet.rhythm?.summary?.takeIf { it.isNotBlank() }?.let { NoteLine(R.drawable.ic_m_calendar, it) }
}

/** L'activité jour par jour, sur trente jours : une barre par jour (la sorte filtrée, ou tout), la dernière est aujourd'hui. */
@Composable
private fun DaysChart(d: ActivityDays, kind: String) {
    val values = d.days.map { dayCount(it, kind) }
    val top = maxOf(4, values.maxOrNull() ?: 0)
    val bar = toneOf(StateTone.WORK).bar
    val today = MaterialTheme.colorScheme.primary
    val track = MaterialTheme.colorScheme.surfaceContainerHigh
    Canvas(Modifier.fillMaxWidth().height(96.dp).background(track, RoundedCornerShape(10.dp)).padding(8.dp)) {
        if (values.isEmpty()) return@Canvas
        val slot = size.width / values.size
        values.forEachIndexed { i, v ->
            if (v <= 0) return@forEachIndexed
            val h = size.height * v / top
            drawRect(if (i == values.lastIndex) today else bar, topLeft = Offset(i * slot + slot * 0.15f, size.height - h), size = Size(slot * 0.7f, h))
        }
    }
    Row(Modifier.fillMaxWidth()) {
        Text(stringResource(R.string.proj_act_days_from), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
        Text(stringResource(R.string.proj_act_days_peak, top.toString()), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

// ── Les exécutions ──────────────────────────────────────────────────────

@Composable
private fun RunsPane(activity: ActivityViewModel, shell: Shell, now: Long) {
    ListedPane(activity.runs.load, activity.runs::retry) { page ->
        val items = activity.allRuns
        if (items.isEmpty()) {
            item(key = "none") { EmptyNote(R.drawable.ic_m_history, stringResource(R.string.proj_act_runs_none), stringResource(R.string.proj_act_runs_none_sub)) }
        }
        var left = items.size
        for (day in byDay(items, { it.at }, now)) {
            item(key = "d${day.label}") { GroupLabel(day.label) }
            left -= day.items.size
            val last = left == 0
            items(day.items, key = { "r${it.id}" }) { r -> RunRow(r, last && r === day.items.last()) { shell.navigate(Route.ProjectPage(activity.id, SheetPages.RUN, r.id)) } }
        }
        moreRow(activity.runsCursor > 0 && items.isNotEmpty() && items.size < page.total, activity.loadingMore, activity::moreRuns)
    }
}

/** Une exécution dans la ligne de temps : ce qu'elle visait, sa sorte, son verdict, son heure et sa durée. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RunRow(r: Run, last: Boolean, onClick: () -> Unit) {
    Box(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(start = 12.dp, end = 16.dp, top = 8.dp)) {
        TimelineRow(runTone(r), last) {
            Text(runTitle(r), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Gap(4.dp)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp), itemVerticalAlignment = Alignment.CenterVertically) {
                KindChip(r.sortLabel)
                StatePill(runTone(r), r.verdictLabel.ifBlank { r.outcomeLabel })
                MetaText(listOf(MoiDates.clock(r.at), duration(r.seconds)).filter { it.isNotBlank() }.joinToString(" · "))
            }
        }
    }
}

// ── Le carnet ───────────────────────────────────────────────────────────

@Composable
private fun NotebookPane(activity: ActivityViewModel, sheet: Sheet, now: Long) {
    val goals = sheet.objectives.map { it.id to it.text } + sheet.missions.map { it.id to it.text }
    Column(Modifier.fillMaxSize()) {
        Column(Modifier.padding(horizontal = 16.dp, vertical = 10.dp)) {
            Text(stringResource(R.string.proj_act_notebook_title), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text(stringResource(R.string.proj_act_notebook_sub), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        val total = activity.notes?.valueOrNull?.total
        ChipRow(
            listOf(Chip("0", stringResource(R.string.proj_act_all), total.takeIf { activity.notebookObjective == 0 })) +
                goals.map { (id, text) -> Chip(id.toString(), text.take(40), total.takeIf { activity.notebookObjective == id }) },
            selected = activity.notebookObjective.toString(),
            onPick = { code -> (code.toIntOrNull() ?: 0).let { activity.pickNotebook(if (it == activity.notebookObjective) 0 else it) } },
        )
        ListedPane(activity.notes, activity::retryNotes) { page ->
            val items = activity.allNotes
            if (items.isEmpty()) {
                item(key = "none") {
                    EmptyNote(R.drawable.ic_m_book, stringResource(R.string.proj_act_notebook_none), stringResource(if (activity.notebookObjective != 0) R.string.proj_act_notebook_none_goal else R.string.proj_act_notebook_none_sub))
                }
            }
            if (page.totalCut) item(key = "cut") { Hint(stringResource(R.string.proj_act_cut), modifier = Modifier.padding(12.dp)) }
            items(items, key = { "n${it.seq}" }) { n -> NoteCard(n, now) }
            moreRow(activity.notesCursor > 0 && items.isNotEmpty(), activity.loadingMore, activity::moreNotes)
        }
    }
}

/** Une note de son carnet : ses mots à elle, l'objectif qu'elle visait, quand. */
@Composable
private fun NoteCard(n: NotebookNote, now: Long) {
    Surface(
        shape = RoundedCornerShape(14.dp),
        color = mika.soft,
        border = BorderStroke(1.dp, mika.line),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
    ) {
        Column(Modifier.padding(14.dp)) {
            MdText(n.text)
            Gap(8.dp)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    n.objective?.text?.ifBlank { null } ?: stringResource(R.string.proj_the_project).replaceFirstChar { it.uppercase() },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(8.dp))
                Text(moment(n.at, now), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
            }
        }
    }
}

// ── Une exécution ───────────────────────────────────────────────────────

@Composable
internal fun RunScreen(graph: AppGraph, route: Route.ProjectPage) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val project = rememberProjectModel(graph, route.id)
    val section = rememberProjectsModel(graph)
    val vm: CodeReadViewModel<Run> = viewModel(key = "run|$session|${route.id}|${route.key}") {
        CodeReadViewModel(ProjectsDeps(graph)) { it.run(route.id, route.key) }
    }
    val now = rememberNow(wallMs = graph.clock::wallMs)
    Toasts(vm.gestures)
    OnResume(vm) {
        project.resume()
        vm.resume()
    }
    var pane by rememberSaveable { mutableStateOf(PANE_STEPS) }
    DetailPage(
        title = stringResource(R.string.proj_act_tab_runs),
        projectTitle = project.sheet.valueOrNull?.project?.title,
        load = vm.read.load,
        onRetry = vm.read::retry,
        panes = { r -> listOf(Pane(PANE_STEPS, stringResource(R.string.proj_act_pane_steps), r.steps.size.takeIf { it > 0 }?.toString().orEmpty()), Pane(PANE_INFOS, stringResource(R.string.proj_pane_infos))) },
        pane = pane,
        onPane = { pane = it },
        head = { r ->
            CodeHead(projectIcon(runIcon(r.sort)), runTone(r), stringResource(R.string.proj_act_run_over, r.sortLabel), runTitle(r), meta = {
                StatePill(runTone(r), r.verdictLabel.ifBlank { r.outcomeLabel })
                MetaText(moment(r.at, now))
                MetaText(duration(r.seconds))
            })
        },
    ) { r ->
        if (pane == PANE_INFOS) {
            paneBlock("infos") {
                SideTitle(stringResource(R.string.proj_side_brief))
                Fact(stringResource(R.string.proj_act_fact_verdict)) { StatePill(runTone(r), r.verdictLabel.ifBlank { r.outcomeLabel }) }
                Fact(stringResource(R.string.proj_fact_kind), r.sortLabel)
                Fact(stringResource(R.string.proj_fact_when), moment(r.at, now))
                Fact(stringResource(R.string.proj_act_fact_duration), duration(r.seconds))
                if (r.proven) Fact(stringResource(R.string.proj_proof), stringResource(R.string.proj_act_proven))
                if (r.need.isNotBlank()) {
                    SideTitle(stringResource(R.string.proj_act_side_need))
                    Text(r.need, style = MaterialTheme.typography.bodyMedium)
                    OutlinedButton(onClick = {
                        section.showOnly(route.id)
                        shell.navigate(Route.Projects(ProjectsTabs.TODO))
                    }) { Text(stringResource(R.string.proj_act_see_todo)) }
                }
                r.objective?.let { o ->
                    SideTitle(stringResource(R.string.proj_act_side_about))
                    val mission = o.kind == "constant"
                    LinkedLine(
                        if (mission) R.drawable.ic_m_refresh else R.drawable.ic_m_target, objectiveTone(o.status), o.text,
                        if (mission) stringResource(R.string.proj_mission) else stringResource(R.string.proj_goal_n, o.id),
                        pill = { StatePill(objectiveTone(o.status), o.statusLabel) },
                        onClick = { shell.navigate(Route.ProjectGoal(route.id, (if (mission) "m" else "o") + o.id)) },
                    )
                    if (o.ticket > 0) {
                        LinkedLine(R.drawable.ic_m_ticket, StateTone.WAIT, stringResource(R.string.proj_ticket_n, o.ticket), stringResource(R.string.proj_ticket_born_of), onClick = { shell.navigate(Route.ProjectTicket(route.id, o.ticket)) })
                    }
                }
                if (r.commit.isNotBlank()) {
                    SideTitle(stringResource(R.string.proj_act_side_commit))
                    LinkedLine(R.drawable.ic_m_commit, StateTone.WAIT, r.commit.take(7), r.branch, onClick = { shell.navigate(Route.ProjectCode(route.id, CodePages.COMMIT, r.commit)) })
                }
            }
        } else {
            runSteps(r, now)
        }
    }
}

/** Le volet « Pas à pas » : son compte rendu (ses mots à elle), puis chaque pas — l'outil, ce qu'il visait, le temps passé — et son verdict. */
private fun LazyListScope.runSteps(r: Run, now: Long) {
    if (r.report.isNotBlank()) paneBlock("report") { Bubble("self", stringResource(R.string.mika), since(r.at, now), r.report, markdown = true) }
    paneBlock("steps-head") {
        Text(stringResource(R.string.proj_act_steps_title), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
        if (!r.stepsKept) Hint(stringResource(R.string.proj_act_steps_gone))
        if (!r.stepsAims && r.stepsAimsWhy.isNotBlank()) Hint(r.stepsAimsWhy, R.drawable.ic_m_lock)
    }
    val spent = stepsSpent(r.steps)
    item(key = "steps") {
        Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
            r.steps.forEachIndexed { i, s ->
                TimelineRow(if (s.ok) StateTone.WORK else StateTone.FAIL, last = false) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(s.label, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                        Text("+ " + duration(spent[i]).ifBlank { "0 s" }, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                    }
                    // ce qu'il visait : un chemin, une commande, une adresse — posé tel quel, jamais lu comme un lien
                    if (s.aim.isNotBlank()) {
                        Gap(2.dp)
                        Code(s.aim)
                    }
                    if (s.outside || !s.ran) {
                        Gap(4.dp)
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            if (s.outside) OutsideMark()
                            if (!s.ran) Text(stringResource(R.string.proj_act_step_not_run), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(start = if (s.outside) 8.dp else 0.dp))
                        }
                    }
                }
            }
            TimelineRow(runTone(r), last = true) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(stringResource(R.string.proj_act_fact_verdict), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(r.verdictLabel.ifBlank { r.outcomeLabel }, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold)
                    }
                    Text(duration(r.seconds), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
    if (r.stepsCut) paneBlock("steps-cut") { Hint(stringResource(R.string.proj_act_steps_cut)) }
}
