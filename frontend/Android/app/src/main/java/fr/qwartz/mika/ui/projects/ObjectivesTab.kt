package fr.qwartz.mika.ui.projects

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.horizontalScroll
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.projects.Diagram
import fr.qwartz.mika.data.moi.projects.DiagramRow
import fr.qwartz.mika.data.moi.projects.Goal
import fr.qwartz.mika.data.moi.projects.Segment
import fr.qwartz.mika.data.moi.projects.Sheet
import fr.qwartz.mika.data.moi.projects.StateTone
import fr.qwartz.mika.data.moi.projects.age
import fr.qwartz.mika.data.moi.projects.diagramRows
import fr.qwartz.mika.data.moi.projects.diagramTone
import fr.qwartz.mika.data.moi.projects.goalAwaits
import fr.qwartz.mika.data.moi.projects.goalGroups
import fr.qwartz.mika.data.moi.projects.goalSegments
import fr.qwartz.mika.data.moi.projects.goalWord
import fr.qwartz.mika.data.moi.projects.liveMilestones
import fr.qwartz.mika.data.moi.projects.milestonePart
import fr.qwartz.mika.data.moi.projects.milestoneTones
import fr.qwartz.mika.data.moi.projects.milestoneWord
import fr.qwartz.mika.data.moi.projects.missionWord
import fr.qwartz.mika.data.moi.projects.objectiveTone
import fr.qwartz.mika.data.moi.projects.reachedCount
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon

/*
 * L'onglet Objectifs d'une fiche (ADR 0296) : une bascule Liste | Diagramme. La liste est serrée — une ligne par
 * objectif : un point à la couleur de son état, son titre, sa barre de jalons dessous, « 1/4 » et son âge ; une mission
 * dit sa cadence à la place de la barre — et ouvre le détail en page. Le diagramme montre les objectifs et, en retrait,
 * leurs jalons, chacun avec sa barre, en deux modes : « Avancement » (les barres partent du même bord) et « Dans le
 * temps » ([TimeDiagram] : un axe en jours ou en semaines, de vraies dates seulement).
 */

@Composable
internal fun ObjectivesTab(vm: ProjectViewModel, sheet: Sheet, now: Long, onAdd: () -> Unit) {
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            SingleChoiceSegmentedButtonRow(Modifier.weight(1f)) {
                SegmentedButton(
                    selected = !vm.diagramMode,
                    onClick = { vm.showDiagram(false) },
                    shape = SegmentedButtonDefaults.itemShape(0, 2),
                    label = { Text(stringResource(R.string.proj_goals_list), maxLines = 1) },
                )
                SegmentedButton(
                    selected = vm.diagramMode,
                    onClick = { vm.showDiagram(true) },
                    shape = SegmentedButtonDefaults.itemShape(1, 2),
                    label = { Text(stringResource(R.string.proj_goals_diagram), maxLines = 1) },
                )
            }
            if (sheet.rights.edit) {
                Spacer(Modifier.width(10.dp))
                Button(onClick = onAdd) {
                    MIcon(R.drawable.ic_m_plus, null, size = 18.dp)
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.proj_add))
                }
            }
        }
        if (vm.diagramMode) DiagramView(vm, sheet, now) else GoalList(vm, sheet, now, onAdd)
    }
}

/** La liste serrée : ses filtres en pastilles (un filtre se retire en le touchant de nouveau), puis ses trois groupes. */
@Composable
private fun GoalList(vm: ProjectViewModel, sheet: Sheet, now: Long, onAdd: () -> Unit) {
    val shell = LocalShell.current
    val groups = goalGroups(sheet)
    val labels = mapOf(
        "open" to stringResource(R.string.proj_goals_open),
        "missions" to stringResource(R.string.proj_goals_missions),
        "done" to stringResource(R.string.proj_goals_done),
    )
    val seen = groups.filter { (vm.goalFilter.isEmpty() || vm.goalFilter == it.code) && it.items.isNotEmpty() }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
        if (groups.all { it.items.isEmpty() }) {
            item(key = "none") {
                EmptyNote(R.drawable.ic_m_target, stringResource(R.string.proj_goals_none), stringResource(R.string.proj_goals_none_sub)) {
                    if (sheet.rights.edit) FilledTonalButton(onClick = onAdd) { Text(stringResource(R.string.proj_goal_add)) }
                }
            }
        } else {
            item(key = "filters") {
                ChipRow(
                    groups.map { Chip(it.code, labels[it.code].orEmpty(), it.items.size) },
                    selected = vm.goalFilter,
                    onPick = vm::pickGoalFilter,
                    modifier = Modifier.padding(bottom = 6.dp),
                )
            }
            if (seen.isEmpty()) {
                item(key = "nothing") { EmptyNote(R.drawable.ic_m_target, stringResource(R.string.proj_goals_nothing), stringResource(R.string.proj_goals_nothing_sub)) }
            }
        }
        for (g in seen) {
            item(key = "g${g.code}") { GroupLabel(labels[g.code].orEmpty(), g.items.size) }
            // sa clé porte son groupe : unique dans toute la liste, quoi que rende le serveur
            keyedItems(g.items, { "${g.code}:${it.key}" }) { goal -> GoalRow(goal, now) { shell.navigate(Route.ProjectGoal(vm.id, goal.key)) } }
        }
    }
}

/** Une ligne de la liste : le point de son état (ambre devant lui quand quelque chose attend la personne), son titre, sa barre, « 1/4 », son âge. */
@Composable
private fun GoalRow(goal: Goal, now: Long, onClick: () -> Unit) {
    Column(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Row(Modifier.padding(start = 8.dp, end = 16.dp, top = 9.dp, bottom = 9.dp), verticalAlignment = Alignment.CenterVertically) {
            val awaits = goal is Goal.Once && goalAwaits(goal.o)
            Box(Modifier.size(6.dp).background(if (awaits) toneOf(StateTone.YOU).bar else androidx.compose.ui.graphics.Color.Transparent, CircleShape))
            Spacer(Modifier.width(5.dp))
            val tone = when (goal) {
                is Goal.Once -> objectiveTone(goal.o.status)
                is Goal.Constant -> if (goal.m.status == "open") StateTone.WORK else StateTone.WAIT
            }
            Box(Modifier.size(9.dp).background(toneOf(tone).ink, CircleShape))
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(goal.text, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Gap(4.dp)
                when (goal) {
                    is Goal.Once -> if (liveMilestones(goal.o).isNotEmpty()) {
                        MilestoneBar(milestoneTones(goal.o), Modifier.width(150.dp))
                    } else {
                        Text(stringResource(R.string.proj_no_milestone_short), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    is Goal.Constant -> Text(goal.m.cadenceLabel, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                }
            }
            if (goal is Goal.Once && liveMilestones(goal.o).isNotEmpty()) {
                Spacer(Modifier.width(10.dp))
                Text("${reachedCount(goal.o)}/${liveMilestones(goal.o).size}", style = MaterialTheme.typography.bodyMedium)
            }
            Spacer(Modifier.width(12.dp))
            Text(
                age(if (goal is Goal.Once) goal.o.lastRun else (goal as Goal.Constant).m.lastRun, now),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
            )
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    }
}

// ── Le diagramme ────────────────────────────────────────────────────────

/**
 * Le diagramme des objectifs et de leurs jalons, en mode « Avancement » : une ligne par objectif et, en retrait dessous
 * (repliables), une ligne par jalon ; à droite la part faite, puis un mot — « atteint le 3 nov. », « 2 exécutions »,
 * « attend ta validation ». De vraies dates seulement, celles de `GET …/diagramme`. Une ligne ouvre son objectif.
 */
@Composable
private fun DiagramView(vm: ProjectViewModel, sheet: Sheet, now: Long) {
    when (val load = vm.diagram) {
        null, Load.Loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        is Load.Failed -> Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            RefusalNote(load.error.message)
            OutlinedButton(onClick = { vm.loadDiagram() }) { Text(stringResource(R.string.retry)) }
        }
        is Load.Ready -> {
            // « Avancement » (les barres partent du même bord) ou « Dans le temps » ; là, en jours ou en semaines
            var time by rememberSaveable { mutableStateOf(false) }
            var picked by rememberSaveable { mutableIntStateOf(SCALE_AUTO) }
            var shown by remember { mutableStateOf(false) }
            Column(Modifier.fillMaxSize()) {
                Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                    SingleChoiceSegmentedButtonRow {
                        SegmentedButton(selected = !time, onClick = { time = false }, shape = SegmentedButtonDefaults.itemShape(0, 2), label = { Text(stringResource(R.string.proj_time_progress), maxLines = 1) })
                        SegmentedButton(selected = time, onClick = { time = true }, shape = SegmentedButtonDefaults.itemShape(1, 2), label = { Text(stringResource(R.string.proj_time_time), maxLines = 1) })
                    }
                    if (time) {
                        Spacer(Modifier.width(10.dp))
                        SingleChoiceSegmentedButtonRow {
                            SegmentedButton(selected = !shown, onClick = { picked = SCALE_DAYS }, shape = SegmentedButtonDefaults.itemShape(0, 2), label = { Text(stringResource(R.string.proj_time_days), maxLines = 1) })
                            SegmentedButton(selected = shown, onClick = { picked = SCALE_WEEKS }, shape = SegmentedButtonDefaults.itemShape(1, 2), label = { Text(stringResource(R.string.proj_time_weeks), maxLines = 1) })
                        }
                    }
                }
                if (time) {
                    TimeDiagram(vm, sheet, load.value, now, if (picked == SCALE_AUTO) null else picked == SCALE_WEEKS) { shown = it }
                } else {
                    DiagramRows(vm, sheet, load.value, now)
                }
            }
        }
    }
}

/** L'échelle du diagramme dans le temps : celle qui tient dans la piste, ou celle qu'on a choisie. */
private const val SCALE_AUTO = 0
private const val SCALE_DAYS = 1
private const val SCALE_WEEKS = 2

@Composable
private fun DiagramRows(vm: ProjectViewModel, sheet: Sheet, d: Diagram, now: Long) {
    val shell = LocalShell.current
    val rows = diagramRows(d, vm.folded)
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
        item(key = "head") {
            Row(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceContainerLow).padding(horizontal = 12.dp, vertical = 8.dp)) {
                HeadCell(stringResource(R.string.proj_diagram_names), Modifier.weight(NAMES))
                HeadCell(stringResource(R.string.proj_diagram_part), Modifier.width(BAR + 8.dp))
                HeadCell(stringResource(R.string.proj_diagram_word), Modifier.weight(WORDS))
            }
        }
        if (d.cut) item(key = "cut") { Hint(stringResource(R.string.proj_diagram_cut), modifier = Modifier.padding(12.dp)) }
        if (rows.isEmpty()) {
            item(key = "none") { EmptyNote(R.drawable.ic_m_target, stringResource(R.string.proj_goals_none), stringResource(R.string.proj_goals_none_sub)) }
        }
        items(
            rows.size,
            key = { i ->
                when (val r = rows[i]) {
                    is DiagramRow.StepRow -> "j${r.o.id}-${r.m.id}"
                    is DiagramRow.MissionRow -> "m${r.o.id}"
                    is DiagramRow.GoalRow -> "o${r.o.id}"
                }
            },
        ) { i ->
            val r = rows[i]
            val key = if (r.o.kind == "constant") "m${r.o.id}" else "o${r.o.id}"
            val known = sheet.objectives.any { it.id == r.o.id } || sheet.missions.any { it.id == r.o.id }
            Column(Modifier.fillMaxWidth().then(if (known) Modifier.clickable { shell.navigate(Route.ProjectGoal(vm.id, key)) } else Modifier)) {
                Row(Modifier.padding(horizontal = 12.dp, vertical = if (r is DiagramRow.StepRow) 7.dp else 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Row(Modifier.weight(NAMES), verticalAlignment = Alignment.CenterVertically) { DiagramName(vm, r) }
                    Spacer(Modifier.width(8.dp))
                    when (r) {
                        is DiagramRow.StepRow -> SegmentBar(listOf(Segment(diagramTone(r.m), milestonePart(r.m))).filter { it.part > 0f }, Modifier.width(BAR))
                        is DiagramRow.GoalRow -> SegmentBar(goalSegments(r.o), Modifier.width(BAR))
                        is DiagramRow.MissionRow -> PassDots(minOf(12, if (r.o.passes.isNotEmpty()) r.o.passes.size else r.o.runs), Modifier.width(BAR))
                    }
                    Spacer(Modifier.width(8.dp))
                    val ready = r is DiagramRow.StepRow && r.m.ready
                    Text(
                        when (r) {
                            is DiagramRow.StepRow -> milestoneWord(r.m, now)
                            is DiagramRow.GoalRow -> goalWord(r.o, now)
                            is DiagramRow.MissionRow -> missionWord(r.o, now)
                        },
                        style = MaterialTheme.typography.bodySmall,
                        fontWeight = if (ready) FontWeight.SemiBold else FontWeight.Normal,
                        color = if (ready) toneOf(StateTone.YOU).ink else MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(WORDS),
                    )
                }
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            }
        }
    }
}

private const val NAMES = 1.15f
private const val WORDS = 0.85f
private val BAR = 78.dp

@Composable
private fun HeadCell(text: String, modifier: Modifier) {
    Text(text.uppercase(), style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2, modifier = modifier)
}

/** Le nom d'une ligne : un objectif (et de quoi replier ses jalons), un jalon en retrait, une mission. */
@Composable
private fun DiagramName(vm: ProjectViewModel, r: DiagramRow) {
    when (r) {
        is DiagramRow.GoalRow -> {
            if (r.o.milestones.isNotEmpty()) {
                val label = stringResource(if (r.folded) R.string.proj_diagram_unfold else R.string.proj_diagram_fold)
                Box(Modifier.size(28.dp).clip(CircleShape).clickable(onClickLabel = label) { vm.fold(r.o.id) }, contentAlignment = Alignment.Center) {
                    MIcon(if (r.folded) R.drawable.ic_m_chev_right else R.drawable.ic_m_chev_down, label, size = 16.dp)
                }
            } else {
                Spacer(Modifier.width(28.dp))
            }
            Text(r.o.text, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        is DiagramRow.StepRow -> {
            Spacer(Modifier.width(28.dp))
            Box(Modifier.size(9.dp).clip(RoundedCornerShape(2.dp)).background(toneOf(diagramTone(r.m)).let { if (diagramTone(r.m) == StateTone.WAIT) it.ink else it.bar }))
            Spacer(Modifier.width(8.dp))
            Text(r.m.text, style = MaterialTheme.typography.bodySmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        is DiagramRow.MissionRow -> {
            Box(Modifier.size(28.dp), contentAlignment = Alignment.Center) { MIcon(R.drawable.ic_m_refresh, null, size = 16.dp, tint = toneOf(StateTone.WORK).ink) }
            Column {
                Text(r.o.text, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text(stringResource(R.string.proj_diagram_mission, r.o.statusLabel), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
            }
        }
    }
}

/** Les passages d'une mission : un point par passage, douze au plus. */
@Composable
private fun PassDots(n: Int, modifier: Modifier) {
    val c = toneOf(StateTone.WORK).bar
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(2.dp), verticalAlignment = Alignment.CenterVertically) {
        repeat(n.coerceAtLeast(0)) { Box(Modifier.size(5.dp).background(c, CircleShape)) }
    }
}
