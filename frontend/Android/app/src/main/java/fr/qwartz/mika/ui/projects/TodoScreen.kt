package fr.qwartz.mika.ui.projects

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.net.toUri
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.projects.CodePages
import fr.qwartz.mika.data.moi.projects.CodeTabs
import fr.qwartz.mika.data.moi.projects.Approval
import fr.qwartz.mika.data.moi.projects.AskFor
import fr.qwartz.mika.data.moi.projects.EntryDetail
import fr.qwartz.mika.data.moi.projects.GesturePlace
import fr.qwartz.mika.data.moi.projects.GestureRead
import fr.qwartz.mika.data.moi.projects.ProjectsApi
import fr.qwartz.mika.data.moi.projects.Sheet
import fr.qwartz.mika.data.moi.projects.SheetTabs
import fr.qwartz.mika.data.moi.projects.StateTone
import fr.qwartz.mika.data.moi.projects.TodoButton
import fr.qwartz.mika.data.moi.projects.TodoDecision
import fr.qwartz.mika.data.moi.projects.Verb
import fr.qwartz.mika.data.moi.projects.Waiting
import fr.qwartz.mika.data.moi.projects.gesturePlace
import fr.qwartz.mika.data.moi.projects.gestureRead
import fr.qwartz.mika.data.moi.projects.isMerge
import fr.qwartz.mika.data.moi.projects.mergeNumber
import fr.qwartz.mika.data.moi.projects.moment
import fr.qwartz.mika.data.moi.projects.objectiveTone
import fr.qwartz.mika.data.moi.projects.plural
import fr.qwartz.mika.data.moi.projects.safeLink
import fr.qwartz.mika.data.moi.projects.since
import fr.qwartz.mika.data.moi.projects.ticketTone
import fr.qwartz.mika.data.moi.projects.todoDecision
import fr.qwartz.mika.data.moi.projects.waitingIcon
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
 * Une attente d'« À faire », en page (ADR 0296) : ce qu'il faut lire pour décider — exactement ce qui partirait pour un
 * accord, le plan d'un projet, un point d'arrêt et sa preuve, la question ou le plan d'un ticket, un élément à sa
 * charge —, et en bas ses gestes. Le geste est celui du serveur (`gesture`) : ses boutons ne paraissent que s'il le dit
 * faisable ici (`can`), sinon sa raison (`why`) se lit telle quelle. Ce que le web met dans son panneau latéral est le
 * volet « Infos ».
 */

private const val PANE_READ = "lire"
private const val PANE_INFOS = "infos"

@Composable
fun TodoScreen(graph: AppGraph, route: Route.ProjectTodo) {
    val shell = LocalShell.current
    val vm = rememberProjectsModel(graph)
    val where = ProjectsViewModel.todoWhere(route.project, route.key)
    LaunchedEffect(vm) { vm.gestures.said.collect { shell.toast(it) } }
    LaunchedEffect(vm, route) { vm.open(route.project, route.key) }
    // décidée : elle n'est plus à faire, on revient à la liste
    LaunchedEffect(vm.gestures.finished) {
        if (vm.gestures.finished == where) {
            vm.gestures.acknowledge()
            shell.back()
        }
    }
    val now = rememberNow(wallMs = graph.clock::wallMs)
    var pane by rememberSaveable(route.project, route.key) { mutableStateOf(PANE_READ) }
    var asking by remember { mutableStateOf<TodoButton?>(null) }
    val w = vm.shown
    val decision = if (w == null) TodoDecision() else todoDecision(w, vm.approval, vm.sheet?.valueOrNull?.plan, vm.element?.valueOrNull)
    val busy = vm.gestures.busy.isNotEmpty()
    SectionScaffold(
        topBar = { MikaTopBar(title = stringResource(R.string.proj_tab_todo), nav = BarNav.BACK, subtitle = w?.projectTitle) },
        bottomBar = {
            if (w != null && pane == PANE_READ && decision.buttons.isNotEmpty()) {
                DecisionBar(decision.buttons, busy) { b -> if (b.ask == AskFor.NOTHING) vm.decide(b.action) else asking = b }
            }
        },
    ) { modifier ->
        when {
            w != null -> Column(modifier) {
                TodoHead(w, now, shell)
                PaneTabs(listOf(Pane(PANE_READ, stringResource(R.string.proj_pane_read)), Pane(PANE_INFOS, stringResource(R.string.proj_pane_infos))), pane) { pane = it }
                Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    if (pane == PANE_INFOS) {
                        TodoInfos(w, vm, now, shell)
                    } else {
                        RefusalNote(vm.gestures.refusalAt(where))
                        TodoReading(w, vm, decision, now, busy)
                        Elsewhere(w, shell)
                    }
                }
            }
            vm.missing -> Notice(stringResource(R.string.proj_todo_gone), modifier, action = stringResource(R.string.proj_todo_back), onAction = shell.back)
            else -> LoadBox(vm.overview, vm::retry, modifier) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            }
        }
    }
    // la fusion d'une pull request prête : rien ne part sans sa confirmation, qui dit ce qui va être fusionné
    vm.merge.asking?.let { MergeDialog(it, onConfirm = vm::confirmMerge, onDismiss = vm.merge::cancel) }
    asking?.let { b ->
        AskDialog(
            title = buttonLabel(b),
            lede = w?.about.orEmpty(),
            label = askLabel(b.ask),
            placeholder = "",
            confirm = buttonLabel(b),
            required = b.ask.required,
            max = 2000,
            danger = b.verb.danger,
            onDismiss = { asking = null },
            onConfirm = { typed ->
                asking = null
                vm.decide(b.action, typed)
            },
        )
    }
}

/** Un geste qui refuse ou écarte : son bouton est en rouge. */
private val Verb.danger: Boolean
    get() = this == Verb.ACCORD_REFUSE || this == Verb.CHECKPOINT_REFUSE || this == Verb.TICKET_REFUSE || this == Verb.TICKET_DISMISS

/** Les mots d'un bouton : ceux de l'écran, ou ceux du serveur pour un geste qu'il nomme lui-même. */
@Composable
internal fun buttonLabel(b: TodoButton): String = when (b.verb) {
    Verb.ACCORD_ACCEPT -> stringResource(R.string.proj_do_accord)
    Verb.ACCORD_REFUSE, Verb.CHECKPOINT_REFUSE, Verb.TICKET_REFUSE -> stringResource(R.string.proj_do_refuse)
    Verb.PLAN_APPROVE, Verb.TICKET_VALIDATE -> stringResource(R.string.proj_do_validate_plan)
    Verb.PLAN_REVISE -> stringResource(R.string.proj_do_revise)
    Verb.CHECKPOINT_VALIDATE -> stringResource(R.string.proj_do_validate_milestone)
    Verb.TICKET_ACCEPT -> stringResource(R.string.proj_do_accept_ticket)
    Verb.TICKET_DISMISS -> stringResource(R.string.proj_do_dismiss)
    Verb.STATUS -> stringResource(R.string.proj_do_status, b.label)
    Verb.GO -> b.label.ifBlank { stringResource(R.string.proj_do_go) }
}

/** Ce qu'un bouton demande de saisir. */
@Composable
internal fun askLabel(ask: AskFor): String = stringResource(
    when (ask) {
        AskFor.REVISE -> R.string.proj_ask_revise
        AskFor.MISSING -> R.string.proj_ask_missing
        AskFor.WRONG -> R.string.proj_ask_wrong
        AskFor.WHY -> R.string.proj_ask_why
        AskFor.WHY_OPTIONAL -> R.string.proj_ask_why_optional
        AskFor.REPLY, AskFor.NOTHING -> R.string.proj_ask_reply
    },
)

/** L'en-tête d'une attente : sa tuile, sa sorte, de quoi il s'agit, son projet, depuis quand ; puis « Ouvrir dans le projet ». */
@Composable
private fun TodoHead(w: Waiting, now: Long, shell: Shell) {
    Column(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 8.dp)) {
        Row(verticalAlignment = Alignment.Top) {
            Tile(projectIcon(waitingIcon(w.kind, w.what)), StateTone.YOU, 44.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(w.kindLabel.uppercase(), style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(w.about, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, modifier = Modifier.semantics { heading() })
                Gap(4.dp)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(w.projectTitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary, maxLines = 1, modifier = Modifier.weight(1f, fill = false))
                    Spacer(Modifier.width(10.dp))
                    Text(since(w.since, now), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                    if (w.outside) {
                        Spacer(Modifier.width(8.dp))
                        OutsideMark()
                    }
                }
            }
        }
        Gap(10.dp)
        OutlinedButton(onClick = { shell.navigate(waitingHome(w)) }, modifier = Modifier.fillMaxWidth()) {
            Text(stringResource(R.string.proj_open_in_project))
            Spacer(Modifier.width(6.dp))
            MIcon(R.drawable.ic_m_chev_right, null, size = 18.dp)
        }
    }
}

/** Où l'attente vit dans la fiche de son projet : son ticket, son objectif, sa liste, sa pull request (l'onglet Code). */
internal fun waitingHome(w: Waiting): Route = when {
    w.kind == "ticket" && isMerge(w) -> mergeNumber(w).let { if (it > 0) pullPage(w.project, it, 0) else Route.Project(w.project, CodeTabs.tab(CodeTabs.PULLS)) }
    w.kind == "ticket" && w.number != 0 -> Route.ProjectTicket(w.project, w.number)
    w.kind == "item" -> Route.Project(w.project, SheetTabs.LISTS)
    w.objective != 0 -> Route.ProjectGoal(w.project, "o${w.objective}")
    else -> Route.Project(w.project)
}

/** Les boutons d'une décision, en bas de l'écran : le geste principal plein, les autres bordés, un refus en rouge. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun DecisionBar(buttons: List<TodoButton>, busy: Boolean, onClick: (TodoButton) -> Unit) {
    Surface(color = MaterialTheme.colorScheme.surface, tonalElevation = 3.dp, shadowElevation = 6.dp) {
        FlowRow(
            Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 16.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            for (b in buttons) {
                val label = buttonLabel(b)
                if (b.primary) {
                    Button(onClick = { onClick(b) }, enabled = b.enabled && !busy) { Text(label) }
                } else {
                    OutlinedButton(
                        onClick = { onClick(b) },
                        enabled = b.enabled && !busy,
                        colors = if (b.verb.danger) ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error) else ButtonDefaults.outlinedButtonColors(),
                    ) { Text(label) }
                }
            }
        }
    }
}

/** Ce qu'il faut lire pour décider, selon ce que le geste de l'attente demande. */
@Composable
private fun TodoReading(w: Waiting, vm: ProjectsViewModel, decision: TodoDecision, now: Long, busy: Boolean) {
    when (val read = gestureRead(w)) {
        is GestureRead.Accord -> Reading(vm.approvals, vm::read) {
            val a = vm.approval
            if (a == null) {
                Lede(w.about)
                Hint(stringResource(R.string.proj_accord_gone))
            } else {
                AccordReading(a, now)
            }
        }
        GestureRead.ProjectPlan -> Reading(vm.sheet, vm::read) { sheet ->
            val plan = sheet.plan
            if (plan == null || plan.text.isBlank()) {
                Lede(w.about)
            } else {
                PlanCard(stringResource(R.string.proj_her_plan), plan.stateLabel, if (plan.state == "proposed") StateTone.YOU else StateTone.WAIT, plan.text, waits = plan.state == "proposed")
                if (plan.questions.isNotBlank()) {
                    Text(stringResource(R.string.proj_her_questions), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                    MdText(plan.questions)
                }
                if (decision.buttons.isNotEmpty()) Hint(stringResource(R.string.proj_word_plan))
            }
        }
        is GestureRead.Checkpoint -> Reading(vm.sheet, vm::read) { sheet -> CheckpointReading(w, sheet, read, now, decision.buttons.isNotEmpty()) }
        is GestureRead.Element -> Reading(vm.element, vm::read) { e -> ElementReading(w, e, vm, decision, now, busy) }
        GestureRead.Nothing -> Lede(w.about)
    }
    if (isMerge(w) && gesturePlace(w) != GesturePlace.THEIRS) {
        val shell = LocalShell.current
        // fusionner d'ici : seulement si le serveur l'ouvre (`can`), par la même confirmation que dans l'onglet Code —
        // la pull request se relit, puis la demande nomme le commit de tête lu
        if (gesturePlace(w) == GesturePlace.HERE && mergeNumber(w) > 0) {
            Button(onClick = vm::askMerge, enabled = !busy && !vm.merge.reading, modifier = Modifier.fillMaxWidth()) {
                MIcon(R.drawable.ic_m_merge, null, size = 18.dp)
                Spacer(Modifier.width(8.dp))
                Text(w.gesture.label.ifBlank { stringResource(R.string.proj_code_merge) })
            }
        }
        OutlinedButton(onClick = { shell.navigate(waitingHome(w)) }, modifier = Modifier.fillMaxWidth()) {
            MIcon(R.drawable.ic_m_pr, null, size = 18.dp)
            Spacer(Modifier.width(8.dp))
            Text(stringResource(R.string.proj_open_pull))
        }
        Hint(stringResource(R.string.proj_word_merge))
    }
}

/** Une lecture en cours, refusée (en mots, et « Réessayer »), ou aboutie. */
@Composable
private fun <T> Reading(load: Load<T>?, onRetry: () -> Unit, content: @Composable (T) -> Unit) {
    when (load) {
        null, Load.Loading -> Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        is Load.Failed -> {
            RefusalNote(load.error.message)
            OutlinedButton(onClick = onRetry) { Text(stringResource(R.string.retry)) }
        }
        is Load.Ready -> content(load.value)
    }
}

@Composable
internal fun Lede(text: String) {
    if (text.isNotBlank()) Text(text, style = MaterialTheme.typography.bodyLarge)
}

/** Un accord : exactement ce qui partirait, mot pour mot, en texte brut à chasse fixe ; puis ce que c'est, où, pourquoi. */
@Composable
private fun AccordReading(a: Approval, now: Long) {
    val context = LocalContext.current
    Text(stringResource(R.string.proj_accord_exact), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, modifier = Modifier.semantics { heading() })
    Surface(shape = RoundedCornerShape(12.dp), color = MaterialTheme.colorScheme.surfaceContainerLow, border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant), modifier = Modifier.fillMaxWidth()) {
        SelectionContainer {
            Text(
                a.text,
                style = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace, lineHeight = 19.sp),
                modifier = Modifier.padding(12.dp),
            )
        }
    }
    RefusalNote(a.blocked)
    Column {
        Fact(stringResource(R.string.proj_fact_what), a.label)
        Fact(stringResource(R.string.proj_fact_where), a.where)
        Fact(stringResource(R.string.proj_fact_why), a.why)
        Fact(stringResource(R.string.proj_fact_brief), a.summary)
        Fact(stringResource(R.string.proj_fact_asked), listOf(a.askedBy.takeIf { it.isNotBlank() }?.let { stringResource(R.string.proj_by, it) }.orEmpty(), moment(a.at, now)).filter { it.isNotBlank() }.joinToString(" · "))
    }
    val page = safeLink(a.whereUrl)
    if (page.isNotEmpty()) {
        OutlinedButton(onClick = { openOutside(context, page) }) {
            MIcon(R.drawable.ic_m_external, null, size = 18.dp)
            Spacer(Modifier.width(8.dp))
            Text(stringResource(R.string.proj_host_page))
        }
    }
    Hint(stringResource(R.string.proj_word_accord))
}

/** Un plan en carte : son titre, son état, puis son texte (le sien : en Markdown) ; ambre quand il attend la personne. */
@Composable
internal fun PlanCard(title: String, stateLabel: String, tone: StateTone, text: String, waits: Boolean, number: Int = 0) {
    val c = toneOf(StateTone.YOU)
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = if (waits) c.container.copy(alpha = 0.45f) else MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, if (waits) c.bar.copy(alpha = 0.5f) else MaterialTheme.colorScheme.outlineVariant),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                MIcon(R.drawable.ic_m_plan, null, size = 18.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.width(8.dp))
                Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                if (number > 0) {
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.proj_number, number), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Spacer(Modifier.weight(1f))
                StatePill(tone, stateLabel)
            }
            Gap(10.dp)
            MdText(text)
        }
    }
}

/** Un point d'arrêt dit prêt : ce qu'elle en dit, le jalon, comment il se vérifie, sa preuve (venue d'ailleurs). */
@Composable
private fun CheckpointReading(w: Waiting, sheet: Sheet, read: GestureRead.Checkpoint, now: Long, decides: Boolean) {
    val o = sheet.objectives.firstOrNull { it.id == read.objective }
    val m = o?.milestones?.firstOrNull { it.id == read.milestone }
    if (o == null || m == null) {
        Lede(w.about)
        return
    }
    Lede(m.how.ifBlank { w.about })
    Column {
        Fact(stringResource(R.string.proj_fact_milestone), m.text)
        Fact(stringResource(R.string.proj_fact_checked_by), m.checkLabel)
        Fact(stringResource(R.string.proj_fact_ready_since), moment(m.readyAt, now))
    }
    m.proof?.text?.takeIf { it.isNotBlank() }?.let { OutsideBlock(stringResource(R.string.proj_proof), it, mono = true) }
    if (decides) Hint(stringResource(R.string.proj_word_checkpoint))
}

/** Un élément : un ticket (son plan à valider, sa question, sinon sa description et son fil), ou un élément d'une liste à sa charge. */
@Composable
private fun ElementReading(w: Waiting, e: EntryDetail, vm: ProjectsViewModel, decision: TodoDecision, now: Long, busy: Boolean) {
    val line = e.line
    val more = e.more
    if (line.veiled.isNotEmpty()) {
        Lede(w.about)
        Hint(line.veiledLabel, R.drawable.ic_m_lock)
        return
    }
    if (line.list != ProjectsApi.TICKETS) {
        Lede(more.body.ifBlank { line.title })
        Column {
            Fact(stringResource(R.string.proj_fact_status)) { StatePill(StateTone.WAIT, line.statusLabel) }
            Fact(stringResource(R.string.proj_fact_actor), line.actorLabel)
        }
        return
    }
    val asks = w.what == "question"
    val question = more.thread.lastOrNull { it.kind == "question" }
    when {
        w.what == "validation" && more.planText.isNotBlank() -> {
            // ce qui est demandé d'abord, puis le plan à valider : le numéro montré est celui que « Valider » nommera
            if (more.body.isNotBlank()) {
                if (line.outside) OutsideBlock(line.author, more.body) else MdText(more.body)
            }
            PlanCard(stringResource(R.string.proj_her_plan), line.statusLabel, StateTone.YOU, more.planText, waits = true, number = line.plan)
        }
        asks && question != null -> Bubble("self", question.author, since(question.at, now), question.text, markdown = true)
        more.body.isBlank() && more.thread.isEmpty() -> Lede(w.about)
        else -> {
            if (more.body.isNotBlank()) {
                if (line.outside) OutsideBlock(line.author, more.body) else MdText(more.body)
            }
            for (n in more.thread.filter { it.kind != "change" }) ThreadNoteView(n, now)
        }
    }
    if (decision.answer) {
        OutlinedTextField(
            value = vm.answer,
            onValueChange = { vm.answer = it },
            placeholder = { Text(stringResource(R.string.proj_answer_hint)) },
            minLines = 3,
            modifier = Modifier.fillMaxWidth(),
        )
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
            Button(onClick = { vm.decide("answer", vm.answer) }, enabled = vm.answer.isNotBlank() && !busy) {
                MIcon(R.drawable.ic_m_send, null, size = 18.dp)
                Spacer(Modifier.width(8.dp))
                Text(stringResource(R.string.proj_answer))
            }
        }
        Hint(stringResource(R.string.proj_word_answer))
    }
    when {
        decision.buttons.any { it.verb == Verb.TICKET_VALIDATE } -> Hint(stringResource(R.string.proj_word_ticket_plan))
        decision.buttons.any { it.verb == Verb.TICKET_ACCEPT } && line.outside -> Hint(stringResource(R.string.proj_word_outside_ticket))
    }
}

/** Ce qui ne se fait pas ici : où, et pourquoi, avec les mots du serveur. */
@Composable
private fun Elsewhere(w: Waiting, shell: Shell) {
    val context = LocalContext.current
    val noBrowser = stringResource(R.string.proj_no_browser)
    when (gesturePlace(w)) {
        GesturePlace.HERE -> Unit
        GesturePlace.THEIRS -> Hint(
            if (w.waitsFor.isBlank()) stringResource(R.string.proj_theirs) else stringResource(R.string.proj_theirs_named, w.waitsFor),
            R.drawable.ic_m_clock,
        )
        GesturePlace.HOST -> {
            Hint(w.why.ifBlank { w.gesture.label }, R.drawable.ic_m_external)
            val url = safeLink(w.gesture.url)
            if (url.isNotEmpty()) {
                OutlinedButton(onClick = { if (!openOutside(context, url)) shell.toast(noBrowser) }) {
                    MIcon(R.drawable.ic_m_external, null, size = 18.dp)
                    Spacer(Modifier.width(8.dp))
                    Text(w.gesture.label.ifBlank { stringResource(R.string.proj_host_page) })
                }
            }
        }
        GesturePlace.DENIED, GesturePlace.CONSOLE -> Hint(w.why.ifBlank { w.gesture.label }, R.drawable.ic_m_lock)
    }
}

/** Une page de l'hôte du dépôt, dans le navigateur du téléphone (http ou https seulement : [safeLink]). */
internal fun openOutside(context: Context, url: String): Boolean = try {
    context.startActivity(Intent(Intent.ACTION_VIEW, url.toUri()).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    true
} catch (_: ActivityNotFoundException) {
    false
}

/** Le volet « Infos » d'une attente : en bref, et ce qui lui est lié. */
@Composable
private fun TodoInfos(w: Waiting, vm: ProjectsViewModel, now: Long, shell: Shell) {
    Column {
        SideTitle(stringResource(R.string.proj_side_brief))
        Fact(stringResource(R.string.proj_fact_project), w.projectTitle)
        Fact(stringResource(R.string.proj_fact_what), w.kindLabel)
        Fact(stringResource(R.string.proj_fact_since), moment(w.since, now))
        if (w.outside) Fact(stringResource(R.string.proj_fact_from)) { OutsideMark() }
        SideTitle(stringResource(R.string.proj_side_linked))
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            when (val read = gestureRead(w)) {
                is GestureRead.Accord -> vm.approval?.concerns?.let { c ->
                    c.ticket?.let { t ->
                        LinkedLine(
                            R.drawable.ic_m_ticket, ticketTone(t.status, t.open, false), t.title.ifBlank { t.veiledLabel.ifBlank { t.handle } }, t.handle,
                            pill = { StatePill(ticketTone(t.status, t.open, false), t.stepLabel.ifBlank { t.statusLabel }) },
                            onClick = { shell.navigate(Route.ProjectTicket(w.project, t.number)) },
                        )
                    }
                    if (c.issue != 0) {
                        LinkedLine(R.drawable.ic_m_issue, StateTone.WAIT, stringResource(R.string.proj_issue_n, c.issue), stringResource(R.string.proj_at_host)) {
                            shell.navigate(Route.ProjectCode(w.project, CodePages.ISSUE, c.issue.toString()))
                        }
                    }
                    if (c.pull != 0) {
                        LinkedLine(R.drawable.ic_m_pr, StateTone.WORK, stringResource(R.string.proj_pull_n, c.pull), stringResource(R.string.proj_at_host)) {
                            shell.navigate(pullPage(w.project, c.pull, 0))
                        }
                    }
                    if (c.objective != 0) {
                        LinkedLine(R.drawable.ic_m_target, StateTone.WORK, stringResource(R.string.proj_goal_n, c.objective), stringResource(R.string.proj_goal_concerned)) {
                            shell.navigate(Route.ProjectGoal(w.project, "o${c.objective}"))
                        }
                    }
                }
                is GestureRead.Checkpoint -> vm.sheet?.valueOrNull?.objectives?.firstOrNull { it.id == read.objective }?.let { o ->
                    LinkedLine(
                        R.drawable.ic_m_target, objectiveTone(o.status), o.text, stringResource(R.string.proj_goal_n, o.id),
                        pill = { StatePill(objectiveTone(o.status), o.statusLabel) },
                        onClick = { shell.navigate(Route.ProjectGoal(w.project, "o${o.id}")) },
                    )
                }
                is GestureRead.Element -> vm.element?.valueOrNull?.let { e ->
                    if (e.line.list == ProjectsApi.TICKETS) {
                        LinkedLine(R.drawable.ic_m_chat, StateTone.WAIT, stringResource(R.string.proj_ticket_thread), plural(e.more.thread.size, "message", "messages")) {
                            shell.navigate(Route.ProjectTicket(w.project, e.line.number))
                        }
                        e.more.linked.objective?.let { o ->
                            LinkedLine(
                                R.drawable.ic_m_target, objectiveTone(o.status), o.text, stringResource(R.string.proj_goal_n, o.id),
                                pill = { StatePill(objectiveTone(o.status), o.statusLabel) },
                                onClick = { shell.navigate(Route.ProjectGoal(w.project, "o${o.id}")) },
                            )
                        }
                        e.more.linked.pull?.let { p -> PullCard(p, e.more.linked.checks, null, now) { shell.navigate(pullPage(w.project, p.number, e.more.linked.objective?.id ?: 0)) } }
                    }
                }
                else -> Unit
            }
            LinkedLine(R.drawable.ic_m_flag, StateTone.WAIT, w.projectTitle, stringResource(R.string.proj_the_project)) { shell.navigate(Route.Project(w.project)) }
        }
    }
}

/** Une ligne de code d'un bloc : pour un texte brut qui défile de côté. */
@Composable
internal fun MonoBlock(text: String, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(MaterialTheme.colorScheme.surfaceContainerLow).horizontalScroll(rememberScrollState()).padding(10.dp)) {
        Text(text, style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace, lineHeight = 17.sp))
    }
}

@Composable
internal fun SectionDivider() {
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
}
