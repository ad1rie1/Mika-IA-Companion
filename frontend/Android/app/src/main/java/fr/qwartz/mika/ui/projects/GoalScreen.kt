package fr.qwartz.mika.ui.projects

import androidx.annotation.DrawableRes
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.projects.ActivityPage
import fr.qwartz.mika.data.moi.projects.Goal
import fr.qwartz.mika.data.moi.projects.Milestone
import fr.qwartz.mika.data.moi.projects.Mission
import fr.qwartz.mika.data.moi.projects.Objective
import fr.qwartz.mika.data.moi.projects.Sheet
import fr.qwartz.mika.data.moi.projects.StateTone
import fr.qwartz.mika.data.moi.projects.findGoal
import fr.qwartz.mika.data.moi.projects.liveMilestones
import fr.qwartz.mika.data.moi.projects.milestoneIcon
import fr.qwartz.mika.data.moi.projects.milestoneTone
import fr.qwartz.mika.data.moi.projects.milestoneTones
import fr.qwartz.mika.data.moi.projects.moment
import fr.qwartz.mika.data.moi.projects.needWaiting
import fr.qwartz.mika.data.moi.projects.objectiveTone
import fr.qwartz.mika.data.moi.projects.plural
import fr.qwartz.mika.data.moi.projects.reachedCount
import fr.qwartz.mika.data.moi.projects.since
import fr.qwartz.mika.data.moi.projects.ticketTone
import fr.qwartz.mika.data.moi.projects.verdictTone
import fr.qwartz.mika.data.moi.projects.waitingKey
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
import fr.qwartz.mika.ui.shell.Notice
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Shell

/*
 * Un objectif ou une mission, en page (ADR 0296) : son en-tête (« Lancer maintenant », « Modifier »), puis ses volets —
 * Jalons (en étapes, avec leurs preuves ; un point d'arrêt prêt a ses boutons), Comptes rendus, et « Infos » (ce que le
 * web met dans son panneau latéral : fini quand, où il en est, sa branche et sa pull request, ses tickets, le gérer).
 * Chaque bouton suit ce que le serveur dit de l'objet (`can`, `rights`).
 */

private const val PANE_STEPS = "jalons"
private const val PANE_REPORTS = "rendus"
private const val PANE_INFOS = "infos"

/** Ce que l'écran demande avant un geste : une raison, une confirmation. */
private sealed interface GoalAsk : java.io.Serializable {
    data class RefuseCheckpoint(val milestone: Int) : GoalAsk
    data class DropMilestone(val milestone: Int, val text: String) : GoalAsk
    data object DropGoal : GoalAsk
}

@Composable
fun GoalScreen(graph: AppGraph, route: Route.ProjectGoal) {
    val shell = LocalShell.current
    val vm = rememberProjectModel(graph, route.id)
    LaunchedEffect(vm) { vm.gestures.said.collect { shell.toast(it) } }
    OnResume(vm, project = route.id) { vm.resume() }
    val now = rememberNow(wallMs = graph.clock::wallMs)
    var pane by rememberSaveable(route.id, route.key) { mutableStateOf(if (route.key.startsWith("m")) PANE_REPORTS else PANE_STEPS) }
    // une feuille ou une fenêtre ouverte survit à une rotation (et ce qu'on y tape aussi)
    var editing by rememberSaveable(route.id, route.key) { mutableStateOf(false) }
    // le jalon dont la feuille est ouverte : `null` fermé, 0 un jalon neuf, sinon celui qu'on modifie
    var milestoneForm by rememberSaveable(route.id, route.key) { mutableStateOf<Int?>(null) }
    var ask by rememberSaveable(route.id, route.key) { mutableStateOf<GoalAsk?>(null) }
    var dropped by rememberSaveable(route.id, route.key) { mutableStateOf(false) }
    val sheet = vm.sheet.valueOrNull
    val goal = sheet?.let { findGoal(it, route.key) }
    val where = goal?.let { ProjectViewModel.goalWhere(it.id) }.orEmpty()
    // l'objectif qui s'ouvre ne redit pas un refus d'avant, et ne se referme pas sur un geste abouti après son départ
    if (where.isNotEmpty()) FreshEntry(vm.gestures, where)
    // l'objectif retiré n'est plus là : on revient à la liste — sur ce geste-là, que [GestureRunner.finished] ne dit
    // qu'une fois abouti (un geste qui part efface le précédent)
    LaunchedEffect(vm.gestures.finished, vm.gestures.busy, dropped) {
        if (dropped && where.isNotEmpty()) {
            if (vm.gestures.finished == where) {
                vm.gestures.acknowledge()
                shell.back()
            } else if (vm.gestures.busy.isEmpty()) {
                // refusé : l'objectif est toujours là, on y reste — et un geste suivant ne ramène pas en arrière
                dropped = false
            }
        }
    }
    SectionScaffold(topBar = { MikaTopBar(title = stringResource(R.string.proj_tab_objectives), nav = BarNav.BACK, subtitle = sheet?.project?.title) }) { modifier ->
        LoadBox(vm.sheet, vm::retry, modifier) { s ->
            val g = findGoal(s, route.key)
            if (g == null) {
                Notice(stringResource(R.string.proj_goal_gone), modifier, action = stringResource(R.string.shell_back), onAction = shell.back)
                return@LoadBox
            }
            // aucun geste sur une fiche d'avant : elle se relit au retour sur l'écran et après chaque geste
            val busy = vm.gestures.busy.isNotEmpty() || vm.stale
            Column(modifier) {
                GoalHead(g, s, now, busy, onLaunch = { vm.pilot("now", objective = g.id, where = ProjectViewModel.goalWhere(g.id)) }, onEdit = { editing = true })
                val panes = when (g) {
                    is Goal.Once -> listOf(
                        Pane(PANE_STEPS, stringResource(R.string.proj_pane_steps), "${reachedCount(g.o)}/${liveMilestones(g.o).size}"),
                        Pane(PANE_REPORTS, stringResource(R.string.proj_pane_reports), if (g.o.runs > 0) g.o.runs.toString() else ""),
                        Pane(PANE_INFOS, stringResource(R.string.proj_pane_infos)),
                    )
                    is Goal.Constant -> listOf(
                        Pane(PANE_REPORTS, stringResource(R.string.proj_pane_passes), if (g.m.passes > 0) g.m.passes.toString() else ""),
                        Pane(PANE_INFOS, stringResource(R.string.proj_pane_infos)),
                    )
                }
                val shown = if (panes.any { it.code == pane }) pane else panes.first().code
                PaneTabs(panes, shown) { pane = it }
                Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    RefusalNote(vm.gestures.refusalAt(ProjectViewModel.goalWhere(g.id)))
                    StaleNote(vm.staleError, vm::reread)
                    when (g) {
                        is Goal.Once -> when (shown) {
                            PANE_REPORTS -> Reports(vm, s, g.id, now, g.o.result.ifBlank { stringResource(R.string.proj_reports_none) }, g.o)
                            PANE_INFOS -> ObjectiveInfos(g.o, s, now, shell, busy, onStatus = { status -> if (status == "dropped") ask = GoalAsk.DropGoal else vm.goalStatus(g, status) })
                            else -> Steps(
                                g.o, s, now, shell, busy,
                                onValidate = { m -> vm.checkpoint(g.o.id, m, "validate") },
                                onRefuse = { m -> ask = GoalAsk.RefuseCheckpoint(m) },
                                onEdit = { m -> milestoneForm = m },
                                onDrop = { m -> ask = GoalAsk.DropMilestone(m.id, m.text) },
                                onAdd = { milestoneForm = 0 },
                            )
                        }
                        is Goal.Constant -> when (shown) {
                            PANE_INFOS -> MissionInfos(g.m, now, busy) { ask = GoalAsk.DropGoal }
                            else -> {
                                NeedBlock(s, g.m.id, g.m.need, shell)
                                Text(stringResource(R.string.proj_each_pass), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                                Text(g.m.eachPass.ifBlank { stringResource(R.string.proj_each_pass_none) }, style = MaterialTheme.typography.bodyMedium)
                                Reports(vm, s, g.id, now, stringResource(R.string.proj_passes_none), null)
                            }
                        }
                    }
                }
            }
        }
    }
    // rien n'est parti (la fiche se relit à l'instant, un autre geste attend sa réponse) : on le dit — une fenêtre où
    // l'on tape reste, avec ce qui est tapé
    val notSent = stringResource(R.string.proj_not_sent)
    val notSentPlain = stringResource(R.string.proj_not_sent_plain)
    if (sheet != null && goal != null) {
        if (editing) GoalFormSheet(vm, sheet, goal) { editing = false }
        val o = (goal as? Goal.Once)?.o
        val form = milestoneForm
        if (o != null && form != null) {
            MilestoneFormSheet(vm, sheet, o, o.milestones.firstOrNull { it.id == form && form != 0 }) { milestoneForm = null }
        }
        when (val a = ask) {
            is GoalAsk.RefuseCheckpoint -> AskDialog(
                title = stringResource(R.string.proj_checkpoint_refuse),
                lede = o?.milestones?.firstOrNull { it.id == a.milestone }?.text.orEmpty(),
                label = stringResource(R.string.proj_ask_missing),
                placeholder = "",
                confirm = stringResource(R.string.proj_do_refuse),
                required = true,
                max = 2000,
                danger = true,
                onDismiss = { ask = null },
                onConfirm = { reason -> if (vm.checkpoint(goal.id, a.milestone, "refuse", reason)) ask = null else shell.toast(notSent) },
            )
            is GoalAsk.DropMilestone -> AskDialog(
                title = stringResource(R.string.proj_milestone_drop),
                lede = stringResource(R.string.proj_milestone_drop_lede, a.text),
                label = stringResource(R.string.proj_ask_why_optional),
                placeholder = "",
                confirm = stringResource(R.string.proj_remove),
                required = false,
                max = 2000,
                danger = true,
                onDismiss = { ask = null },
                onConfirm = { reason -> if (vm.dropMilestone(goal.id, a.milestone, reason)) ask = null else shell.toast(notSent) },
            )
            GoalAsk.DropGoal -> AlertDialog(
                onDismissRequest = { ask = null },
                title = { Text(stringResource(if (goal is Goal.Constant) R.string.proj_mission_drop_title else R.string.proj_goal_drop_title)) },
                text = { Text(stringResource(if (goal is Goal.Constant) R.string.proj_mission_drop_text else R.string.proj_goal_drop_text, goal.text)) },
                confirmButton = {
                    TextButton(
                        onClick = {
                            ask = null
                            // seulement si le geste est parti : sinon rien n'est à attendre, et on le dit
                            dropped = vm.goalStatus(goal, "dropped")
                            if (!dropped) shell.toast(notSentPlain)
                        },
                        colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
                    ) { Text(stringResource(R.string.proj_remove)) }
                },
                dismissButton = { TextButton(onClick = { ask = null }) { Text(stringResource(R.string.cancel)) } },
            )
            null -> Unit
        }
    }
}

/** L'en-tête : sa tuile, « Objectif n° 2 » ou « Mission », son titre, son état, ses passages ; puis ses deux boutons. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun GoalHead(g: Goal, sheet: Sheet, now: Long, busy: Boolean, onLaunch: () -> Unit, onEdit: () -> Unit) {
    val (tone, statusLabel, runs, last, done) = when (g) {
        is Goal.Once -> HeadFacts(objectiveTone(g.o.status), g.o.statusLabel, g.o.runs, g.o.lastRun, g.o.status == "done")
        is Goal.Constant -> HeadFacts(if (g.m.status == "open") StateTone.WORK else StateTone.WAIT, g.m.statusLabel, g.m.passes, g.m.lastRun, false)
    }
    Column(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 8.dp)) {
        Row(verticalAlignment = Alignment.Top) {
            Tile(if (g is Goal.Constant) R.drawable.ic_m_refresh else R.drawable.ic_m_target, tone, 44.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    (if (g is Goal.Constant) stringResource(R.string.proj_mission) else stringResource(R.string.proj_goal_n, g.id)).uppercase(),
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(g.text, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, modifier = Modifier.semantics { heading() })
                Gap(4.dp)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    StatePill(tone, statusLabel)
                    Text(plural(runs, "passage", "passages"), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    if (last > 0) Text(stringResource(R.string.proj_last_one, since(last, now)), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
        val launch = sheet.rights.pilot && !done
        if (launch || g.can.modify) {
            Gap(10.dp)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (launch) {
                    OutlinedButton(onClick = onLaunch, enabled = !busy, modifier = Modifier.weight(1f)) {
                        MIcon(R.drawable.ic_m_play, null, size = 18.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.proj_pilot_now), maxLines = 1)
                    }
                }
                if (g.can.modify) {
                    OutlinedButton(onClick = onEdit, enabled = !busy, modifier = Modifier.weight(1f)) {
                        MIcon(R.drawable.ic_m_pen, null, size = 18.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.proj_edit), maxLines = 1)
                    }
                }
            }
        }
    }
}

private data class HeadFacts(val tone: StateTone, val statusLabel: String, val runs: Int, val last: Long, val done: Boolean)

/** Elle a besoin de quelque chose : ses mots en bulle, et où lui répondre (l'attente d'« À faire » que le serveur a comptée). */
@Composable
private fun NeedBlock(sheet: Sheet, objective: Int, need: String, shell: Shell) {
    if (need.isBlank()) return
    Bubble("self", stringResource(R.string.mika), "", need, markdown = true)
    val w = needWaiting(sheet, objective)
    if (w != null && w.mine) {
        Button(onClick = { shell.navigate(Route.ProjectTodo(w.project, waitingKey(w))) }) {
            MIcon(R.drawable.ic_m_send, null, size = 18.dp)
            Spacer(Modifier.width(8.dp))
            Text(stringResource(R.string.proj_answer_her))
        }
    }
}

/** Les jalons en étapes : chacun son état, comment on le vérifie, sa preuve repliée ; un point d'arrêt prêt a ses boutons. */
@Composable
private fun Steps(
    o: Objective,
    sheet: Sheet,
    now: Long,
    shell: Shell,
    busy: Boolean,
    onValidate: (Int) -> Unit,
    onRefuse: (Int) -> Unit,
    onEdit: (Int) -> Unit,
    onDrop: (Milestone) -> Unit,
    onAdd: () -> Unit,
) {
    NeedBlock(sheet, o.id, o.need, shell)
    if (o.milestones.isEmpty()) {
        Text(stringResource(R.string.proj_steps_none), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    Column {
        o.milestones.forEachIndexed { i, m ->
            key(m.id) { StepView(m, i == o.milestones.lastIndex, sheet.rights.settle, now, shell, busy, onValidate, onRefuse, onEdit, onDrop) }
        }
    }
    if (o.can.milestone) {
        OutlinedButton(onClick = onAdd, enabled = !busy) {
            MIcon(R.drawable.ic_m_plus, null, size = 18.dp)
            Spacer(Modifier.width(6.dp))
            Text(stringResource(R.string.proj_milestone_add))
        }
    }
    o.checks?.said?.text?.takeIf { it.isNotBlank() }?.let { OutsideBlock(stringResource(R.string.proj_ci_tail), it, mono = true) }
    o.pull?.said?.text?.takeIf { it.isNotBlank() }?.let { OutsideBlock(stringResource(R.string.proj_host_last_word), it) }
}

/** Un jalon : sa pastille sur la ligne de temps, son texte, son état, comment il se vérifie, sa preuve, ses gestes. */
@Composable
internal fun StepView(
    m: Milestone,
    last: Boolean,
    settle: Boolean,
    now: Long,
    shell: Shell,
    busy: Boolean,
    onValidate: (Int) -> Unit = {},
    onRefuse: (Int) -> Unit = {},
    onEdit: (Int) -> Unit = {},
    onDrop: (Milestone) -> Unit = {},
) {
    val tone = milestoneTone(m)
    var proof by rememberSaveable(m.id) { mutableStateOf(false) }
    TimelineRow(tone, last) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            MIcon(projectIcon(milestoneIcon(tone)), null, size = 14.dp, tint = toneOf(tone).ink)
            Spacer(Modifier.width(6.dp))
            Text(m.text, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        }
        Gap(4.dp)
        Row(verticalAlignment = Alignment.CenterVertically) {
            when {
                m.ready -> StatePill(StateTone.YOU, stringResource(R.string.proj_step_ready))
                m.status == "open" && m.started && tone == StateTone.WORK -> StatePill(StateTone.WORK, stringResource(R.string.proj_step_doing))
                else -> StatePill(tone, m.statusLabel)
            }
            Spacer(Modifier.weight(1f))
            val at = listOf(m.reachedAt, m.readyAt, m.refusedAt).firstOrNull { it > 0 } ?: 0
            if (at > 0) Text(since(at, now), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (m.can.modify) SmallAction(R.drawable.ic_m_pen, stringResource(R.string.proj_milestone_edit), enabled = !busy) { onEdit(m.id) }
            if (m.can.drop) SmallAction(R.drawable.ic_m_trash, stringResource(R.string.proj_milestone_drop), danger = true, enabled = !busy) { onDrop(m) }
            if (!m.can.modify && !m.can.drop && m.can.why.isNotBlank() && m.status == "open") {
                // ce jalon ne se change pas d'ici : sa raison, avec les mots du serveur
                SmallAction(R.drawable.ic_m_lock, m.can.why) { shell.toast(m.can.why) }
            }
        }
        Gap(4.dp)
        Text(
            stringResource(R.string.proj_checked_by, m.checkLabel) + (if (m.how.isBlank()) "" else " — ${m.how}"),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (m.check == "command" && m.command.isNotBlank()) {
            Gap(4.dp)
            Code(m.command)
        }
        if (m.item.isNotBlank()) {
            Gap(4.dp)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Code(m.item)
                if (m.itemStatusLabel.isNotBlank()) {
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.proj_item_must_be, m.itemStatusLabel), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
        if (m.reason.isNotBlank() && (m.refusedAt > 0 || m.status == "dropped")) {
            Gap(4.dp)
            Text(
                if (m.refusedAt > 0) stringResource(R.string.proj_refused_because, m.reason) else m.reason,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
        val text = m.proof?.text.orEmpty()
        if (text.isNotBlank()) {
            Gap(4.dp)
            Row(Modifier.clip(RoundedCornerShape(8.dp)).clickable { proof = !proof }.padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                MIcon(if (proof) R.drawable.ic_m_chev_down else R.drawable.ic_m_chev_right, null, size = 14.dp, tint = MaterialTheme.colorScheme.primary)
                Spacer(Modifier.width(4.dp))
                Text(stringResource(R.string.proj_proof), style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
                if (m.commit.isNotBlank()) {
                    Spacer(Modifier.width(6.dp))
                    Code(m.commit.take(7))
                }
            }
            if (proof) OutsideBlock(stringResource(R.string.proj_proof_from), text, mono = true)
        }
        if (m.ready && settle) {
            Gap(8.dp)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { onValidate(m.id) }, enabled = !busy) {
                    MIcon(R.drawable.ic_m_check, null, size = 18.dp)
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.proj_do_validate_milestone))
                }
                OutlinedButton(onClick = { onRefuse(m.id) }, enabled = !busy) { Text(stringResource(R.string.proj_do_refuse)) }
            }
        }
    }
}

/** Un petit bouton-icône dans une ligne (modifier, retirer), son nom dit à l'accessibilité. */
@Composable
internal fun SmallAction(@DrawableRes icon: Int, label: String, danger: Boolean = false, enabled: Boolean = true, onClick: () -> Unit) {
    Box(Modifier.size(36.dp).clip(CircleShape).clickable(enabled = enabled, onClickLabel = label, onClick = onClick), contentAlignment = Alignment.Center) {
        MIcon(icon, label, size = 17.dp, tint = if (danger) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/**
 * Les comptes rendus d'un objectif ou les passages d'une mission : ses exécutions, lues dans le fil d'activité (avec le
 * droit de le lire : `rights.work`). [o] : l'objectif, pour sa relecture.
 */
@Composable
private fun Reports(vm: ProjectViewModel, sheet: Sheet, objective: Int, now: Long, none: String, o: Objective?) {
    if (!sheet.rights.work) {
        Text(none, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    } else {
        LaunchedEffect(vm, objective) { vm.loadReports(objective) }
        when (val load: Load<ActivityPage>? = vm.reports[objective]) {
            null, Load.Loading -> Box(Modifier.fillMaxWidth().padding(16.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            is Load.Failed -> {
                RefusalNote(load.error.message)
                OutlinedButton(onClick = { vm.loadReports(objective, force = true) }) { Text(stringResource(R.string.retry)) }
            }
            is Load.Ready -> if (load.value.items.isEmpty()) {
                Text(none, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                Column {
                    load.value.items.forEachIndexed { i, r ->
                        TimelineRow(verdictTone(r.verdict), i == load.value.items.lastIndex) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(moment(r.at, now), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
                                if (r.verdictLabel.isNotBlank()) StatePill(verdictTone(r.verdict), r.verdictLabel)
                            }
                            Gap(2.dp)
                            Text(r.title, style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                }
            }
        }
    }
    val review = o?.review
    if (review != null) {
        Text(stringResource(R.string.proj_her_review), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
        StatePill(if (review.ok) StateTone.DONE else StateTone.FAIL, review.label)
        if (review.text.isNotBlank()) Text(review.text, style = MaterialTheme.typography.bodyMedium)
    }
}

/** Le volet « Infos » d'un objectif : fini quand, où il en est, sa branche et sa pull request, ses tickets, le gérer. */
@Composable
private fun ObjectiveInfos(o: Objective, sheet: Sheet, now: Long, shell: Shell, busy: Boolean, onStatus: (String) -> Unit) {
    val id = sheet.project.id
    val tone = objectiveTone(o.status)
    Column {
        SideTitle(stringResource(R.string.proj_goal_done_when))
        Text(o.doneWhen.ifBlank { stringResource(R.string.proj_done_when_none) }, style = MaterialTheme.typography.bodyMedium)
        SideTitle(stringResource(R.string.proj_card_where))
        Row(verticalAlignment = Alignment.CenterVertically) {
            MilestoneBar(milestoneTones(o), Modifier.weight(1f), height = 7.dp)
            Spacer(Modifier.width(10.dp))
            val live = liveMilestones(o).size
            Text(
                if (live > 0) "${reachedCount(o)} / ${plural(live, "jalon", "jalons")}" else stringResource(R.string.proj_no_milestone),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Gap(6.dp)
        Fact(stringResource(R.string.proj_fact_state)) { StatePill(tone, o.statusLabel) }
        Fact(stringResource(R.string.proj_fact_passes), o.runs.toString())
        Fact(stringResource(R.string.proj_fact_last_pass), moment(o.lastRun, now))
        Fact(stringResource(R.string.proj_fact_result), o.result)
        Fact(stringResource(R.string.proj_fact_note), o.note)
        SideTitle(stringResource(R.string.proj_side_branch))
        if (o.branch.isBlank() && o.pull == null) {
            Text(stringResource(R.string.proj_branch_none), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (o.branch.isNotBlank()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                MIcon(R.drawable.ic_m_branch, null, size = 16.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.width(6.dp))
                Code(o.branch)
                val base = sheet.repo?.branch.orEmpty()
                if (base.isNotBlank()) {
                    MIcon(R.drawable.ic_m_chev_right, null, size = 14.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    Code(base)
                }
            }
            Gap(8.dp)
        }
        o.pull?.let { PullCard(it, o.checks, o.review, now) { shell.navigate(pullPage(id, it.number, o.id)) } }
        SideTitle(stringResource(R.string.proj_side_tickets))
        if (o.tickets.isEmpty() && o.ticket == 0) {
            Text(stringResource(R.string.proj_tickets_linked_none), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            for (t in o.tickets) {
                val tt = ticketTone(t.status, t.open, false)
                LinkedLine(
                    R.drawable.ic_m_ticket, tt, t.title.ifBlank { t.veiledLabel.ifBlank { t.handle } }, t.handle,
                    pill = { StatePill(tt, t.stepLabel.ifBlank { t.statusLabel }) },
                    onClick = { shell.navigate(Route.ProjectTicket(id, t.number)) },
                )
            }
            if (o.tickets.isEmpty() && o.ticket != 0) {
                LinkedLine(R.drawable.ic_m_ticket, StateTone.WAIT, stringResource(R.string.proj_ticket_n, o.ticket), stringResource(R.string.proj_ticket_born_of)) {
                    shell.navigate(Route.ProjectTicket(id, o.ticket))
                }
            }
        }
        if (o.can.reopen || o.can.done || o.can.drop) {
            SideTitle(stringResource(R.string.proj_side_manage))
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                if (o.can.reopen) ManageButton(R.drawable.ic_m_refresh, stringResource(R.string.proj_goal_reopen), busy) { onStatus("open") }
                if (o.can.done) ManageButton(R.drawable.ic_m_check, stringResource(R.string.proj_goal_say_done), busy) { onStatus("done") }
                if (o.can.drop) ManageButton(R.drawable.ic_m_trash, stringResource(R.string.proj_goal_drop), busy, danger = true) { onStatus("dropped") }
            }
        } else if (o.can.why.isNotBlank()) {
            Gap(12.dp)
            Hint(o.can.why, R.drawable.ic_m_lock)
        }
    }
}

@Composable
private fun ManageButton(@DrawableRes icon: Int, label: String, busy: Boolean, danger: Boolean = false, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick,
        enabled = !busy,
        colors = if (danger) ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error) else ButtonDefaults.outlinedButtonColors(),
        modifier = Modifier.fillMaxWidth(),
    ) {
        MIcon(icon, null, size = 18.dp)
        Spacer(Modifier.width(8.dp))
        Text(label)
    }
}

/** Le volet « Infos » d'une mission : son rythme (sa cadence, ce qui la déclenche), ses passages, la retirer. */
@Composable
private fun MissionInfos(m: Mission, now: Long, busy: Boolean, onDrop: () -> Unit) {
    Column {
        SideTitle(stringResource(R.string.proj_side_rhythm))
        Fact(stringResource(R.string.proj_fact_cadence), m.cadenceLabel)
        Fact(stringResource(R.string.proj_fact_triggers), m.on.joinToString(", ") { it.label }.ifBlank { "—" })
        if (m.onlyOnEvent) Fact(stringResource(R.string.proj_fact_when), stringResource(R.string.proj_only_on_event))
        Fact(stringResource(R.string.proj_fact_passes), m.passes.toString())
        Fact(stringResource(R.string.proj_fact_last_one), moment(m.lastRun, now))
        if (m.can.drop) {
            SideTitle(stringResource(R.string.proj_side_manage))
            ManageButton(R.drawable.ic_m_trash, stringResource(R.string.proj_mission_drop), busy, danger = true, onClick = onDrop)
        } else if (m.can.why.isNotBlank()) {
            Gap(12.dp)
            Hint(m.can.why, R.drawable.ic_m_lock)
        }
    }
}
