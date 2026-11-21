package fr.qwartz.mika.ui.projects

import androidx.compose.foundation.BorderStroke
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
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalIconButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.projects.CodePages
import fr.qwartz.mika.data.moi.projects.Demand
import fr.qwartz.mika.data.moi.projects.Gives
import fr.qwartz.mika.data.moi.projects.LinkChange
import fr.qwartz.mika.data.moi.projects.LinkTabs
import fr.qwartz.mika.data.moi.projects.Linked
import fr.qwartz.mika.data.moi.projects.Links
import fr.qwartz.mika.data.moi.projects.Sheet
import fr.qwartz.mika.data.moi.projects.SheetTabs
import fr.qwartz.mika.data.moi.projects.StateTone
import fr.qwartz.mika.data.moi.projects.Tie
import fr.qwartz.mika.data.moi.projects.allDemands
import fr.qwartz.mika.data.moi.projects.askRequest
import fr.qwartz.mika.data.moi.projects.askTone
import fr.qwartz.mika.data.moi.projects.demandTicket
import fr.qwartz.mika.data.moi.projects.findTie
import fr.qwartz.mika.data.moi.projects.given
import fr.qwartz.mika.data.moi.projects.linkCandidates
import fr.qwartz.mika.data.moi.projects.linkRequest
import fr.qwartz.mika.data.moi.projects.linkWhyRequest
import fr.qwartz.mika.data.moi.projects.moment
import fr.qwartz.mika.data.moi.projects.planState
import fr.qwartz.mika.data.moi.projects.plural
import fr.qwartz.mika.data.moi.projects.projectTone
import fr.qwartz.mika.data.moi.projects.shortDate
import fr.qwartz.mika.data.moi.projects.since
import fr.qwartz.mika.data.moi.projects.ticketList
import fr.qwartz.mika.data.moi.projects.ties
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.Shell

/*
 * L'onglet Dépendances d'une fiche (ADR 0296), d'après la maquette validée en largeur de téléphone : **Schéma** — le
 * projet au centre, puis ce dont il dépend (les projets qu'il lit) et ce qui dépend de lui, chaque lien avec son
 * pourquoi et ce qu'il donne — et **Demandes** (envoyées, reçues, leur étape, leur ticket). Un lien s'ouvre en page :
 * depuis quand, pourquoi, ce qu'il donne, le commit que montre la vue, le mode direct, les demandes entre les deux,
 * « Lui demander quelque chose », le retirer. Ajouter, modifier et retirer un lien : seulement si le serveur dit qu'elle
 * pose ses liens (`links.can`). Un projet lié ne dit son nom que si la personne le voit elle-même.
 */

/** Les endroits où un geste sur les liens se dit. */
private const val AT_LINK = "link"
private const val AT_ADD = "link-add"
private const val AT_WHY = "link-why"
private const val AT_ASK = "link-ask"
private const val AT_REMOVE = "link-remove"

@Composable
internal fun LinksTab(vm: ProjectViewModel, sheet: Sheet, now: Long, sub: String) {
    val shell = LocalShell.current
    val links = sheet.links
    if (links == null) {
        StillPane { EmptyNote(R.drawable.ic_m_link, tabLabel(SheetTabs.LINKS), stringResource(R.string.proj_dep_unknown)) }
        return
    }
    val shown = LinkTabs.of(sub)
    var adding by rememberSaveable { mutableStateOf(false) }
    val demands = remember(links) { allDemands(links) }
    Column(Modifier.fillMaxSize()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            ChipRow(
                listOf(
                    Chip(LinkTabs.SCHEMA, stringResource(R.string.proj_dep_tab_schema), links.reads.size + links.readers.size),
                    Chip(LinkTabs.DEMANDS, stringResource(R.string.proj_dep_tab_demands), demands.size),
                ),
                selected = shown,
                onPick = { if (it != shown) shell.replace(Route.Project(vm.id, LinkTabs.tab(it))) },
                modifier = Modifier.weight(1f).padding(top = 4.dp),
            )
            if (links.can) {
                FilledTonalIconButton(onClick = { adding = true }, modifier = Modifier.padding(end = 8.dp)) { MIcon(R.drawable.ic_m_plus, stringResource(R.string.proj_dep_add)) }
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        if (shown == LinkTabs.DEMANDS) DemandsPane(vm, sheet, links, demands, shell, now) else SchemaPane(vm, sheet, links, shell, now)
    }
    if (adding) AddLinkSheet(vm, sheet, links) { adding = false }
}

/** Le nom d'un projet lié, s'il se dit. */
@Composable
private fun linkedName(x: Linked): String = if (x.visible && x.title.isNotBlank()) x.title else stringResource(R.string.proj_hidden_project)

/** Le nom de l'autre projet d'une demande : celui du lien du même numéro (une demande ne le redit pas), si elle le voit. */
@Composable
private fun demandProject(links: Links, a: Demand): String {
    val found = (links.reads + links.readers + links.candidates).firstOrNull { it.project != null && it.project == a.project && it.visible }
    return if (found != null && found.title.isNotBlank()) "« ${found.title} »" else stringResource(R.string.proj_hidden_project)
}

@Composable
private fun demandTitle(a: Demand): String = a.title.ifBlank { if (a.veiled) stringResource(R.string.proj_dep_demand_veiled) else stringResource(R.string.proj_dep_demand_n, a.number) }

@Composable
private fun demandSense(a: Demand): String = stringResource(
    when {
        a.direction == "received" -> R.string.proj_dep_received
        a.from == "you" -> R.string.proj_dep_yours
        else -> R.string.proj_dep_sent
    },
)

// ── Le schéma ───────────────────────────────────────────────────────────

@Composable
private fun SchemaPane(vm: ProjectViewModel, sheet: Sheet, links: Links, shell: Shell, now: Long) {
    val all = remember(links) { ties(links) }
    val p = sheet.project
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        RefusalNote(vm.gestures.refusalAt(AT_LINK))
        // le projet, au centre
        Surface(shape = RoundedCornerShape(20.dp), color = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.35f), border = BorderStroke(2.dp, MaterialTheme.colorScheme.primary), modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                ProjectLogo(p)
                Gap(8.dp)
                Text(p.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center)
                Gap(4.dp)
                val plan = planState(p)
                StatePill(plan?.first ?: projectTone(p.status), plan?.second ?: p.statusLabel)
                val about = p.description.ifBlank { p.where }
                if (about.isNotBlank()) {
                    Gap(8.dp)
                    Text(about, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center, maxLines = 4, overflow = TextOverflow.Ellipsis)
                }
                Gap(10.dp)
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Gap(8.dp)
                CentreCount(sheet.objectives.count { it.status != "done" }, stringResource(R.string.proj_dep_goals_open))
                CentreCount(ticketList(sheet)?.living ?: 0, stringResource(R.string.proj_dep_tickets_open))
                CentreCount(links.asks.size, stringResource(R.string.proj_dep_asks_sent))
            }
        }
        // ce dont il dépend
        val reads = all.filter { it.reads }
        SchemaTitle(links.labels.reads.ifBlank { stringResource(R.string.proj_links_reads) }, reads.size, stringResource(R.string.proj_dep_reads_sub))
        for (t in reads) TieCard(t, now) { shell.navigate(Route.ProjectPage(vm.id, SheetPages.LINK, t.key)) }
        if (reads.isEmpty()) NoneBox(stringResource(R.string.proj_dep_reads_none))
        for (x in links.planAsks) NoneBox(stringResource(R.string.proj_dep_plan_asks, linkedName(x)), R.drawable.ic_m_plan)
        // ce qui dépend de lui
        val readers = all.filterNot { it.reads }
        SchemaTitle(links.labels.readers.ifBlank { stringResource(R.string.proj_links_readers) }, readers.size, stringResource(R.string.proj_dep_readers_sub))
        for (t in readers) TieCard(t, now) { shell.navigate(Route.ProjectPage(vm.id, SheetPages.LINK, t.key)) }
        if (readers.isEmpty()) NoneBox(stringResource(R.string.proj_dep_readers_none))
        Hint(stringResource(R.string.proj_dep_schema_hint))
    }
}

@Composable
private fun CentreCount(n: Int, label: String) {
    Row(Modifier.padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(n.toString(), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
        Spacer(Modifier.width(8.dp))
        Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun SchemaTitle(title: String, count: Int, sub: String) {
    Column(Modifier.padding(top = 6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Spacer(Modifier.width(8.dp))
            CountChip(count.toString())
        }
        Text(sub, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun NoneBox(text: String, icon: Int = 0) {
    Surface(shape = RoundedCornerShape(14.dp), border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant), modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            if (icon != 0) {
                MIcon(icon, null, size = 16.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.width(8.dp))
            }
            Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

/** Le carré d'un projet lié : son initiale s'il se dit, « ? » sinon. */
@Composable
private fun TieLogo(x: Linked, size: Int = 40) {
    val tint = if (x.visible) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant
    Box(Modifier.size(size.dp).clip(RoundedCornerShape(12.dp)).background(tint.copy(alpha = 0.14f)), contentAlignment = Alignment.Center) {
        Text(if (x.visible) x.title.trim().take(1).uppercase().ifEmpty { "?" } else "?", color = tint, fontWeight = FontWeight.Bold, fontSize = (size * 0.4f).sp)
    }
}

/** Ce qu'un lien donne, en pastilles : chaque chose, donnée ou non. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun GivesRow(g: Gives) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        for ((code, on) in given(g)) {
            val c = toneOf(if (on) StateTone.DONE else StateTone.WAIT)
            Row(Modifier.clip(RoundedCornerShape(50)).background(c.container).padding(horizontal = 8.dp, vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                MIcon(if (on) R.drawable.ic_m_check else R.drawable.ic_m_x, null, size = 12.dp, tint = c.ink)
                Spacer(Modifier.width(4.dp))
                Text(giveWord(code), style = MaterialTheme.typography.labelMedium, color = c.ink, maxLines = 1)
            }
        }
    }
}

@Composable
private fun giveWord(code: String): String = stringResource(
    when (code) {
        "detail" -> R.string.proj_dep_give_detail
        "files" -> R.string.proj_dep_give_files
        "docs" -> R.string.proj_dep_give_docs
        else -> R.string.proj_dep_give_see
    },
)

@Composable
private fun giveHelp(code: String): String = stringResource(
    when (code) {
        "detail" -> R.string.proj_dep_give_detail_sub
        "files" -> R.string.proj_dep_give_files_sub
        "docs" -> R.string.proj_dep_give_docs_sub
        else -> R.string.proj_dep_give_see_sub
    },
)

/** Un lien du schéma : le projet lié, pourquoi, ce que le lien donne, le commit que montre la vue, ses demandes. */
@Composable
private fun TieCard(t: Tie, now: Long, onClick: () -> Unit) {
    val x = t.link
    Surface(onClick = onClick, shape = RoundedCornerShape(16.dp), border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                TieLogo(x)
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(linkedName(x), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text(stringResource(if (t.reads) R.string.proj_dep_read_by_it else R.string.proj_dep_reads_it), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (x.suspended) StatePill(StateTone.FAIL, stringResource(R.string.proj_dep_suspended))
            }
            if (x.why.isNotBlank()) Text(x.why, style = MaterialTheme.typography.bodyMedium)
            GivesRow(x.gives)
            val commit = x.commit
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (commit != null) {
                    Code(commit.short)
                    Spacer(Modifier.width(8.dp))
                    Text(since(commit.at, now), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                } else {
                    Text(x.gives.askLabel, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                }
                Spacer(Modifier.weight(1f))
                Text(
                    if (x.asks.isEmpty()) stringResource(R.string.proj_dep_no_demand) else plural(x.asks.size, "demande", "demandes"),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                )
            }
        }
    }
}

// ── Les demandes ────────────────────────────────────────────────────────

@Composable
private fun DemandsPane(vm: ProjectViewModel, sheet: Sheet, links: Links, demands: List<Demand>, shell: Shell, now: Long) {
    var picked by rememberSaveable { mutableIntStateOf(-1) }
    ListedPane(vm.sheet, vm::retry) { _ ->
        item(key = "title") {
            Text(stringResource(R.string.proj_dep_demands_title), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 14.dp, bottom = 6.dp))
        }
        if (demands.isEmpty()) {
            item(key = "none") { EmptyNote(R.drawable.ic_m_send, stringResource(R.string.proj_dep_demands_none), stringResource(R.string.proj_dep_demands_none_sub)) }
        }
        itemsIndexed(demands, key = { i, _ -> "a$i" }) { i, a -> DemandRow(links, a, now) { picked = i } }
    }
    demands.getOrNull(picked)?.let { a -> DemandSheet(sheet, links, a, shell, now) { picked = -1 } }
}

/** Une demande en une ligne : son sens, son titre (s'il se lit), son étape, l'autre projet, depuis quand. */
@Composable
private fun DemandRow(links: Links, a: Demand, now: Long, onClick: () -> Unit) {
    Column(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Row(Modifier.padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.Top) {
            Tile(if (a.direction == "received") R.drawable.ic_m_download else R.drawable.ic_m_send, askTone(a.status))
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(demandTitle(a), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Gap(6.dp)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    StatePill(askTone(a.status), a.stepLabel.ifBlank { a.statusLabel })
                    Spacer(Modifier.width(8.dp))
                    Text(
                        stringResource(if (a.direction == "received") R.string.proj_dep_from else R.string.proj_dep_to, demandProject(links, a)),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f),
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(since(a.at, now), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                }
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    }
}

/** Une demande, ouverte : son sens, son étape (et sa précision), où son ticket se lit. Son texte vit dans son ticket. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DemandSheet(sheet: Sheet, links: Links, a: Demand, shell: Shell, now: Long, onDismiss: () -> Unit) {
    val where = demandProject(links, a)
    val received = a.direction == "received"
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.fillMaxWidth().navigationBarsPadding().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(bottom = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(demandSense(a).uppercase(), style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(demandTitle(a), style = MaterialTheme.typography.titleLarge)
            StatePill(askTone(a.status), a.stepLabel.ifBlank { a.statusLabel })
            Text(
                when {
                    received -> stringResource(R.string.proj_dep_lede_received, where, a.number)
                    a.from == "you" -> stringResource(R.string.proj_dep_lede_yours, where, sheet.project.title)
                    else -> stringResource(R.string.proj_dep_lede_sent, where, a.number)
                },
                style = MaterialTheme.typography.bodyMedium,
            )
            if (a.veiled) Hint(stringResource(R.string.proj_dep_demand_veiled_hint), R.drawable.ic_m_lock)
            if (a.stepLabel.isNotBlank() && a.statusLabel != a.stepLabel) Fact(stringResource(R.string.proj_dep_fact_fine), a.statusLabel)
            Fact(stringResource(R.string.proj_fact_since), moment(a.at, now))
            Fact(stringResource(R.string.proj_dep_fact_closed), moment(a.closedAt, now))
            val ticket = demandTicket(sheet.project.id, a)
            if (ticket != null) {
                Button(onClick = {
                    onDismiss()
                    shell.navigate(Route.ProjectTicket(ticket.first, ticket.second))
                }) { Text(stringResource(R.string.proj_ticket_open) + " #${ticket.second}") }
            } else {
                Hint(stringResource(R.string.proj_dep_ticket_hidden), R.drawable.ic_m_lock)
            }
        }
    }
}

// ── Ajouter une dépendance ──────────────────────────────────────────────

/**
 * « Ajouter une dépendance » : les projets qu'elle peut lui faire lire (servis : `candidates`), ce que chaque lien
 * donnerait, et le mot du lien. Ce que le lien donne vient des lignes d'accès du projet lu : cela ne se choisit pas ici.
 */
@Composable
private fun AddLinkSheet(vm: ProjectViewModel, sheet: Sheet, links: Links, onDismiss: () -> Unit) {
    val options = remember(links) { linkCandidates(links) }
    var project by rememberSaveable { mutableIntStateOf(options.firstOrNull()?.project ?: 0) }
    var why by rememberSaveable { mutableStateOf("") }
    LaunchedEffect(Unit) { vm.gestures.forget(AT_ADD) }
    DoneCloses(vm.gestures, AT_ADD, onDismiss)
    val nothing = stringResource(R.string.proj_dep_would_nothing)
    val would = stringResource(R.string.proj_dep_would)
    val words = options.associate { c -> (c.project ?: 0) to given(c.gives).filter { it.second }.map { giveWord(it.first) } }
    FormSheet(
        title = stringResource(R.string.proj_dep_add),
        sub = stringResource(R.string.proj_dep_add_sub, sheet.project.title),
        submit = stringResource(R.string.proj_add),
        busy = vm.gestures.busy == AT_ADD,
        error = vm.gestures.refusalAt(AT_ADD),
        onDismiss = onDismiss,
        onSubmit = { vm.gestures.send(vm.id, linkRequest(LinkChange.ADD, project, why), AT_ADD) { vm.reload() } },
        enabled = project != 0,
    ) {
        if (options.isEmpty()) {
            EmptyNote(R.drawable.ic_m_link, stringResource(R.string.proj_dep_add_none), stringResource(R.string.proj_dep_add_none_sub))
        } else {
            FormCards(
                stringResource(R.string.proj_dep_add_project),
                options.map { c ->
                    val gives = words[c.project ?: 0].orEmpty()
                    Triple((c.project ?: 0).toString(), c.title, (if (gives.isEmpty()) nothing else "$would ${gives.joinToString(", ")}") + " · ${c.gives.askLabel}")
                },
                project.toString(),
            ) { project = it.toIntOrNull() ?: 0 }
            FormText(stringResource(R.string.proj_fact_why), why, { why = it.take(300) }, hint = stringResource(R.string.proj_dep_why_hint), help = stringResource(R.string.proj_dep_why_help), error = vm.gestures.fieldsAt(AT_ADD)["why"])
            Hint(stringResource(R.string.proj_dep_gives_hint))
        }
    }
}

// ── Un lien, en page ────────────────────────────────────────────────────

@Composable
internal fun LinkScreen(graph: AppGraph, route: Route.ProjectPage) {
    val shell = LocalShell.current
    val vm = rememberProjectModel(graph, route.id)
    val now = rememberNow(wallMs = graph.clock::wallMs)
    Toasts(vm.gestures)
    OnResume(vm) { vm.resume() }
    var editingWhy by rememberSaveable { mutableStateOf(false) }
    var asking by rememberSaveable { mutableStateOf(false) }
    var removing by rememberSaveable { mutableStateOf(false) }
    var picked by remember { mutableStateOf<Demand?>(null) }
    // le lien retiré, sa page n'a plus rien à montrer : retour au schéma
    LaunchedEffect(vm.gestures.finished) {
        if (vm.gestures.finished == AT_REMOVE) {
            vm.gestures.acknowledge()
            shell.back()
        }
    }
    val busy = vm.gestures.busy.isNotEmpty()
    DetailPage(
        title = tabLabel(SheetTabs.LINKS),
        projectTitle = vm.sheet.valueOrNull?.project?.title,
        load = vm.sheet,
        onRetry = vm::retry,
        panes = { emptyList() },
        pane = "",
        onPane = {},
        head = { s ->
            val t = s.links?.let { findTie(it, route.key) }
            if (t != null) {
                Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                    TieLogo(t.link, 48)
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text(linkedName(t.link), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                        Text(
                            stringResource(if (t.reads) R.string.proj_dep_head_reads else R.string.proj_dep_head_reader, s.project.title) +
                                if (t.link.since > 0) " · " + stringResource(R.string.proj_dep_since, shortDate(t.link.since, now)) else "",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        },
    ) { s ->
        val links = s.links
        val t = links?.let { findTie(it, route.key) }
        if (links == null || t == null) {
            item(key = "gone") { EmptyNote(R.drawable.ic_m_link, stringResource(R.string.proj_dep_gone), stringResource(R.string.proj_dep_gone_sub)) }
            return@DetailPage
        }
        val x = t.link
        val other = x.project
        // ce lien se gère d'ici : elle pose ses liens, elle voit le projet, et c'est un projet qu'il lit
        val mine = links.can && x.visible && other != null && t.reads
        paneBlock("why") {
            RefusalNote(vm.gestures.refusalAt(AT_LINK))
            if (x.suspended) Banner(StateTone.FAIL, R.drawable.ic_m_alert, stringResource(R.string.proj_dep_suspended_long))
            if (!x.visible) Hint(stringResource(R.string.proj_dep_hidden_hint), R.drawable.ic_m_lock)
            if (x.why.isNotBlank()) Text(x.why, style = MaterialTheme.typography.bodyLarge)
            if (mine) {
                OutlinedButton(onClick = { editingWhy = true }, enabled = !busy) {
                    MIcon(R.drawable.ic_m_pen, null, size = 18.dp)
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(if (x.why.isBlank()) R.string.proj_dep_why_say else R.string.proj_dep_why_change))
                }
            }
        }
        paneBlock("gives") {
            SideTitle(stringResource(if (t.reads) R.string.proj_dep_side_gives else R.string.proj_dep_side_gives_reader))
            for ((code, on) in given(x.gives)) {
                Row(verticalAlignment = Alignment.Top) {
                    MIcon(if (on) R.drawable.ic_m_check else R.drawable.ic_m_x, null, size = 18.dp, tint = toneOf(if (on) StateTone.DONE else StateTone.WAIT).ink, modifier = Modifier.padding(top = 2.dp))
                    Spacer(Modifier.width(10.dp))
                    Column {
                        Text(giveWord(code).replaceFirstChar { it.uppercase() }, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold)
                        Text(giveHelp(code), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            Hint(stringResource(R.string.proj_dep_gives_read_hint))
        }
        val commit = x.commit
        if (commit != null && other != null) {
            paneBlock("commit") {
                SideTitle(stringResource(R.string.proj_dep_side_commit))
                Row(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).clickable { shell.navigate(Route.ProjectCode(other, CodePages.COMMIT, commit.sha)) }.padding(vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Code(commit.short)
                    Spacer(Modifier.width(8.dp))
                    Text(commit.title, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                    Spacer(Modifier.width(8.dp))
                    Text(since(commit.at, now), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                }
                if (commit.outside) OutsideMark()
            }
        }
        paneBlock("asks") {
            SideTitle(stringResource(R.string.proj_dep_side_asks))
            Muted(x.gives.askLabel)
            if (mine && other != null) {
                FormCheck(stringResource(R.string.proj_dep_direct), stringResource(R.string.proj_dep_direct_sub), x.direct) { on ->
                    if (!busy) vm.gestures.send(vm.id, linkRequest(if (on) LinkChange.DIRECT_ON else LinkChange.DIRECT_OFF, other), AT_LINK) { vm.reload() }
                }
            }
            SideTitle(stringResource(R.string.proj_dep_side_between) + "  ${x.asks.size}")
            if (x.asks.isEmpty()) Muted(stringResource(R.string.proj_dep_between_none))
            for (a in x.asks) {
                LinkedLine(
                    if (a.direction == "received") R.drawable.ic_m_download else R.drawable.ic_m_send, askTone(a.status), demandTitle(a),
                    demandSense(a) + " · " + since(a.at, now),
                    pill = { StatePill(askTone(a.status), a.stepLabel.ifBlank { a.statusLabel }) },
                    onClick = { picked = a },
                )
            }
            val here = x.askHere
            when {
                here?.can == true -> Button(onClick = { asking = true }, enabled = !busy) {
                    MIcon(R.drawable.ic_m_send, null, size = 18.dp)
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.proj_dep_ask))
                }
                !here?.why.isNullOrBlank() -> Hint(here?.why.orEmpty(), R.drawable.ic_m_lock)
            }
        }
        paneBlock("manage") {
            SideTitle(stringResource(R.string.proj_side_manage))
            if (x.visible && other != null) {
                OutlinedButton(onClick = { shell.navigate(Route.Project(other)) }) {
                    MIcon(R.drawable.ic_m_external, null, size = 18.dp)
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.proj_dep_open, x.title), maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            if (mine) {
                OutlinedButton(onClick = { removing = true }, enabled = !busy) {
                    MIcon(R.drawable.ic_m_trash, null, size = 18.dp, tint = MaterialTheme.colorScheme.error)
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.proj_dep_remove), color = MaterialTheme.colorScheme.error)
                }
            }
        }
    }
    val sheet = vm.sheet.valueOrNull
    val tie = sheet?.links?.let { findTie(it, route.key) }
    val other = tie?.link?.project
    if (sheet != null && tie != null && other != null) {
        if (editingWhy) {
            WordSheet(
                title = stringResource(R.string.proj_dep_why_title),
                sub = linkedName(tie.link),
                label = stringResource(R.string.proj_fact_why),
                initial = tie.link.why,
                runner = vm.gestures,
                where = AT_WHY,
                onDismiss = { editingWhy = false },
            ) { why -> vm.gestures.send(vm.id, linkWhyRequest(other, why), AT_WHY) { vm.reload() } }
        }
        val here = tie.link.askHere
        if (asking && here?.can == true) {
            AskSheet(linkedName(tie.link), here.born, vm.gestures, onDismiss = { asking = false }) { title, text ->
                vm.gestures.send(here.project ?: other, askRequest(here.route.ifBlank { "ticket" }, title, text), AT_ASK) { vm.reload() }
            }
        }
        if (removing) {
            ConfirmDialog(
                stringResource(R.string.proj_dep_remove),
                stringResource(R.string.proj_dep_remove_text, sheet.project.title, tie.link.title),
                stringResource(R.string.proj_remove),
                onDismiss = { removing = false },
            ) { vm.gestures.send(vm.id, linkRequest(LinkChange.REMOVE, other), AT_REMOVE) { vm.reload() } }
        }
        picked?.let { a -> sheet.links?.let { l -> DemandSheet(sheet, l, a, shell, now) { picked = null } } }
    }
}

/** Le mot d'un lien : pourquoi ce projet lit l'autre. */
@Composable
private fun WordSheet(title: String, sub: String, label: String, initial: String, runner: GestureRunner, where: String, onDismiss: () -> Unit, onSave: (String) -> Unit) {
    var word by rememberSaveable { mutableStateOf(initial) }
    LaunchedEffect(Unit) { runner.forget(where) }
    DoneCloses(runner, where, onDismiss)
    FormSheet(title = title, sub = sub, submit = stringResource(R.string.proj_save), busy = runner.busy == where, error = runner.refusalAt(where), onDismiss = onDismiss, onSubmit = { onSave(word) }, enabled = word.trim() != initial.trim()) {
        FormLong(label, word, { word = it.take(300) }, rows = 2, hint = stringResource(R.string.proj_dep_why_hint), help = stringResource(R.string.proj_dep_why_help), error = runner.fieldsAt(where)["why"])
    }
}

/** « Lui demander quelque chose » : un ticket qu'elle ouvre elle-même chez le projet lu, avec les droits qu'elle a sur lui. */
@Composable
private fun AskSheet(project: String, born: String, runner: GestureRunner, onDismiss: () -> Unit, onAsk: (String, String) -> Unit) {
    var title by rememberSaveable { mutableStateOf("") }
    var text by rememberSaveable { mutableStateOf("") }
    LaunchedEffect(Unit) { runner.forget(AT_ASK) }
    DoneCloses(runner, AT_ASK, onDismiss)
    val errors = runner.fieldsAt(AT_ASK)
    FormSheet(
        title = stringResource(R.string.proj_dep_ask),
        sub = project,
        submit = stringResource(R.string.proj_dep_ask_ok),
        busy = runner.busy == AT_ASK,
        error = runner.refusalAt(AT_ASK),
        onDismiss = onDismiss,
        onSubmit = { onAsk(title, text) },
        enabled = title.isNotBlank(),
    ) {
        FormText(stringResource(R.string.proj_dep_ask_title), title, { title = it }, hint = stringResource(R.string.proj_dep_ask_title_hint), error = errors["title"])
        FormLong(stringResource(R.string.proj_dep_ask_text), text, { text = it }, rows = 4, error = errors["text"])
        Hint(stringResource(if (born == "proposed") R.string.proj_dep_ask_proposed else R.string.proj_dep_ask_open))
    }
}
