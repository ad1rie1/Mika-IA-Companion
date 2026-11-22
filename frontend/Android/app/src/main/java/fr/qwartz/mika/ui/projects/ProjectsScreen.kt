package fr.qwartz.mika.ui.projects

import androidx.annotation.DrawableRes
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.hue
import fr.qwartz.mika.data.moi.initials
import fr.qwartz.mika.data.moi.projects.Archived
import fr.qwartz.mika.data.moi.projects.shortDate
import fr.qwartz.mika.data.moi.projects.Overview
import fr.qwartz.mika.data.moi.projects.ProjectHead
import fr.qwartz.mika.data.moi.projects.StateTone
import fr.qwartz.mika.data.moi.projects.Waiting
import fr.qwartz.mika.data.moi.projects.planState
import fr.qwartz.mika.data.moi.projects.plural
import fr.qwartz.mika.data.moi.projects.progressTone
import fr.qwartz.mika.data.moi.projects.projectTone
import fr.qwartz.mika.data.moi.projects.since
import fr.qwartz.mika.data.moi.projects.todoGroups
import fr.qwartz.mika.data.moi.projects.waitingIcon
import fr.qwartz.mika.data.moi.projects.waitingKey
import fr.qwartz.mika.data.moi.projects.whose
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.BarAction
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.rememberSessionKey

/*
 * Projets (ADR 0296), la rubrique du tiroir : ce que fait l'écran Projets du client web, d'après la même maquette
 * validée, lue dans ses vues en largeur de téléphone. Deux volets qui se remplacent sans s'empiler : « À faire » (ce qui
 * attend la personne dans tous ses projets, groupé par projet) et « Projets » (ses projets en cartes). Une ligne ouvre
 * son détail en page, avec un retour.
 */

/** Les volets de la rubrique ; une adresse inconnue retombe sur « À faire ». */
internal object ProjectsTabs {
    const val TODO = "a-faire"
    const val PROJECTS = "projets"

    fun of(tab: String): String = if (tab == PROJECTS) PROJECTS else TODO
}

/** Le modèle de la rubrique, un par session : la liste et l'attente ouverte le partagent. */
@Composable
internal fun rememberProjectsModel(graph: AppGraph): ProjectsViewModel {
    val session = rememberSessionKey(graph)
    return viewModel(key = "projects|$session") { ProjectsViewModel(ProjectsDeps(graph)) }
}

/**
 * La rubrique (`Route.Projects(tab)`) ; [nav] : le tiroir depuis le tiroir, la flèche quand un autre écran y mène. Elle
 * se relit à chaque retour sur l'écran, et en tirant.
 */
@Composable
fun ProjectsScreen(graph: AppGraph, tab: String, nav: BarNav) {
    val shell = LocalShell.current
    val vm = rememberProjectsModel(graph)
    LaunchedEffect(vm) { vm.gestures.said.collect { shell.toast(it) } }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(vm, lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) { vm.resume() }
    }
    // le projet qui vient d'être confié s'ouvre : il naît à cadrer
    LaunchedEffect(vm.created) {
        val id = vm.created
        if (id != 0) {
            vm.createdOpened()
            shell.navigate(Route.Project(id))
        }
    }
    // le projet qui vient d'être désarchivé s'ouvre : il revient en pause
    LaunchedEffect(vm.restored) {
        val id = vm.restored
        if (id != 0) {
            vm.restoredOpened()
            shell.navigate(Route.Project(id))
        }
    }
    val shown = ProjectsTabs.of(tab)
    val now = rememberNow(wallMs = graph.clock::wallMs)
    SectionScaffold(topBar = { ProjectsTopBar(shown, nav, vm) }) { modifier ->
        PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::pull, modifier = modifier) {
            LoadBox(vm.overview, vm::retry) { overview ->
                if (shown == ProjectsTabs.PROJECTS) ProjectsTab(overview, now, vm) else TodoTab(overview, now, vm)
            }
        }
    }
    NewProjectSheet(vm)
}

/** La barre : le titre, « Nouveau projet » si le serveur l'ouvre, puis les deux volets et leurs comptes. */
@Composable
private fun ProjectsTopBar(tab: String, nav: BarNav, vm: ProjectsViewModel) {
    val shell = LocalShell.current
    val overview = vm.overview.valueOrNull
    Column {
        MikaTopBar(
            title = stringResource(R.string.nav_projects),
            nav = nav,
            actions = {
                if (overview?.create?.can == true) BarAction(R.drawable.ic_m_plus, stringResource(R.string.proj_new_title), vm::openNew)
            },
        )
        val tabs = listOf(
            Triple(ProjectsTabs.TODO, R.string.proj_tab_todo, overview?.todoTotal),
            Triple(ProjectsTabs.PROJECTS, R.string.proj_tab_projects, overview?.projects?.size),
        )
        PrimaryTabRow(selectedTabIndex = tabs.indexOfFirst { it.first == tab }.coerceAtLeast(0)) {
            for ((id, label, count) in tabs) {
                Tab(
                    selected = id == tab,
                    onClick = { if (id != tab) shell.replace(Route.Projects(id)) },
                    text = {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(stringResource(label))
                            if (count != null) {
                                Spacer(Modifier.width(6.dp))
                                CountChip(count.toString())
                            }
                        }
                    },
                )
            }
        }
    }
}

// ── À faire ─────────────────────────────────────────────────────────────

/** « À faire » : ce qui t'attend, groupé par projet ; des pastilles filtrent sur un projet ; une ligne ouvre de quoi décider. */
@Composable
private fun TodoTab(overview: Overview, now: Long, vm: ProjectsViewModel) {
    val shell = LocalShell.current
    val groups = todoGroups(vm.todo)
    val seen = groups.filter { vm.filter == 0 || it.project == vm.filter }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
        if (groups.isEmpty()) {
            item(key = "none") {
                EmptyNote(R.drawable.ic_m_check, stringResource(R.string.proj_todo_none), stringResource(R.string.proj_todo_none_sub))
            }
        }
        if (groups.size > 1) {
            item(key = "filters") {
                ChipRow(
                    listOf(Chip("0", stringResource(R.string.proj_filter_all))) + groups.map { Chip(it.project.toString(), it.title, it.items.size) },
                    selected = vm.filter.toString(),
                    onPick = { vm.pick(it.toIntOrNull() ?: 0) },
                    modifier = Modifier.padding(vertical = 6.dp),
                )
            }
        }
        for (g in seen) {
            item(key = "g${g.project}") { GroupLabel(g.title, g.items.size) }
            // la clé d'une ligne porte son rang : deux attentes de même clé ne font pas tomber la liste
            itemsIndexed(g.items, key = { i, w -> "w${w.project}:${waitingKey(w)}:$i" }) { _, w ->
                TodoRow(w, now) { shell.navigate(Route.ProjectTodo(w.project, waitingKey(w))) }
            }
        }
        if (vm.todoRest > 0) {
            item(key = "more") {
                TextButton(onClick = vm::more, enabled = !vm.loadingMore, modifier = Modifier.fillMaxWidth().padding(8.dp)) {
                    MIcon(R.drawable.ic_m_chev_down, null, size = 18.dp)
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.proj_todo_more, vm.todoRest))
                }
            }
        }
    }
}

/** Une attente : ce que c'est (une tuile ambre : à toi), de quoi il s'agit, sa sorte, depuis quand. */
@Composable
internal fun TodoRow(w: Waiting, now: Long, onClick: () -> Unit) {
    Column(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Row(Modifier.padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Tile(projectIcon(waitingIcon(w.kind, w.what)), StateTone.YOU)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(w.about, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Gap(3.dp)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(w.kindLabel, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                    if (w.outside) {
                        Spacer(Modifier.width(8.dp))
                        OutsideMark()
                    }
                    Spacer(Modifier.weight(1f))
                    Text(since(w.since, now), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                }
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    }
}

// ── Projets ─────────────────────────────────────────────────────────────

/** « Projets » : ses projets en cartes, ceux où quelque chose l'attend d'abord (l'ordre du serveur), puis « Nouveau projet ». */
@Composable
private fun ProjectsTab(overview: Overview, now: Long, vm: ProjectsViewModel) {
    val shell = LocalShell.current
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 12.dp, end = 12.dp, top = 12.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (overview.projects.isEmpty() && !overview.create.can) {
            item(key = "none") {
                EmptyNote(R.drawable.ic_m_flag, stringResource(R.string.proj_none), overview.create.why.ifBlank { stringResource(R.string.proj_none_sub) })
            }
        }
        keyedItems(overview.projects, { "p${it.id}" }) { p -> ProjectCardView(p, now) { shell.navigate(Route.Project(p.id)) } }
        if (overview.create.can) {
            item(key = "new") {
                Surface(
                    onClick = vm::openNew,
                    shape = RoundedCornerShape(20.dp),
                    color = MaterialTheme.colorScheme.surfaceContainerLow,
                    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                        MIcon(R.drawable.ic_m_plus, null, tint = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(12.dp))
                        Column {
                            Text(stringResource(R.string.proj_new_title), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                            Text(stringResource(R.string.proj_new_card), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }
        }
        // les projets archivés qu'elle peut restaurer : rien n'en est effacé, ils reviennent en pause
        val archived = vm.archives.value?.items.orEmpty()
        if (archived.isNotEmpty()) {
            item(key = "archived") {
                Text(
                    stringResource(R.string.proj_archived_title),
                    style = MaterialTheme.typography.labelLarge,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 8.dp),
                )
            }
            keyedItems(archived, { "a${it.id}" }) { a -> ArchivedRow(a, now, vm) }
        }
    }
}

/** Un projet archivé : son titre, depuis quand, à qui ; « Désarchiver » — un refus se dit dessous, avec les mots du serveur. */
@Composable
private fun ArchivedRow(a: Archived, now: Long, vm: ProjectsViewModel) {
    Surface(shape = RoundedCornerShape(16.dp), border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                MIcon(R.drawable.ic_m_archive, null, size = 20.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(a.title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text(
                        listOf(stringResource(R.string.proj_archived_since, shortDate(a.archivedAt, now)), a.ownerName).filter { it.isNotBlank() }.joinToString(" · "),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.width(8.dp))
                OutlinedButton(onClick = { vm.restore(a.id) }, enabled = vm.gestures.busy.isEmpty()) { Text(stringResource(R.string.proj_archived_restore), maxLines = 1) }
            }
            RefusalNote(vm.gestures.refusalAt(ProjectsViewModel.restoreWhere(a.id)), Modifier.padding(top = 8.dp))
        }
    }
}

/** Les teintes du carré d'un projet (celles des ronds d'initiales de la maquette). */
private val LOGO_COLORS = listOf(
    Color(0xFF4F46E5), Color(0xFFC2410C), Color(0xFF0F766E), Color(0xFF7C3AED),
    Color(0xFF475569), Color(0xFFB45309), Color(0xFF0369A1), Color(0xFFBE185D),
)

/** Le carré d'un projet : son initiale, d'une teinte stable. */
@Composable
internal fun ProjectLogo(p: ProjectHead, size: Int = 44) {
    val tint = LOGO_COLORS[hue("p${p.id}")]
    Box(Modifier.size(size.dp).clip(RoundedCornerShape(12.dp)).background(tint.copy(alpha = 0.14f)), contentAlignment = Alignment.Center) {
        Text(initials(p.title).take(1), color = tint, fontWeight = FontWeight.Bold, fontSize = (size * 0.4f).sp)
    }
}

/**
 * La carte d'un projet : son titre, pour qui, son état ; où il en est ; la progression de ses objectifs (un segment par
 * objectif) ; ses compteurs ; sa dernière activité et ses dépendances. Tout vient de la liste (`card`) : aucune fiche
 * n'est lue pour la remplir.
 */
@Composable
private fun ProjectCardView(p: ProjectHead, now: Long, onClick: () -> Unit) {
    val card = p.card
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(20.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.Top) {
                ProjectLogo(p)
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(p.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text(
                        whose(p, card?.ledBy.orEmpty()) + if (p.detail) "" else " · " + stringResource(R.string.proj_see_only_short),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.width(8.dp))
                val plan = planState(p)
                if (plan != null) StatePill(plan.first, plan.second) else StatePill(projectTone(p.status), p.statusLabel)
            }
            Gap(12.dp)
            Text(
                p.where.ifBlank { stringResource(if (p.detail) R.string.proj_where_none else R.string.proj_see_only) },
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 4,
                overflow = TextOverflow.Ellipsis,
            )
            if (card != null) {
                Gap(12.dp)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    MilestoneBar(card.objectives.states.map { progressTone(it.state) }.ifEmpty { listOf(StateTone.WAIT) }, Modifier.weight(1f))
                    Spacer(Modifier.width(10.dp))
                    Text(
                        "${card.objectives.done} / ${plural(card.objectives.total, "objectif", "objectifs")}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Gap(12.dp)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (card != null) {
                    Counter(card.pullsOpen, stringResource(R.string.proj_count_pulls), Modifier.weight(1f))
                    Counter(card.ticketsOpen, stringResource(R.string.proj_count_tickets), Modifier.weight(1f))
                }
                Counter(p.waiting, stringResource(R.string.proj_count_yours), Modifier.weight(1f), you = p.waiting > 0)
            }
            val last = card?.lastActivity?.takeIf { it > 0 } ?: p.lastRun
            val hidden = stringResource(R.string.proj_hidden_project)
            val deps = card?.let { c ->
                c.reads.map { stringResource(R.string.proj_depends_on, if (it.visible) it.title else hidden) } +
                    c.readers.map { stringResource(R.string.proj_depended_by, if (it.visible) it.title else hidden) }
            }.orEmpty()
            if (last > 0 || deps.isNotEmpty()) {
                Gap(10.dp)
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Gap(8.dp)
                if (last > 0) FootLine(R.drawable.ic_m_clock, since(last, now))
                for (d in deps) FootLine(R.drawable.ic_m_link, d)
            }
        }
    }
}

@Composable
private fun FootLine(@DrawableRes icon: Int, text: String) {
    Row(Modifier.padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        MIcon(icon, null, size = 14.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.width(6.dp))
        Text(text, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** Un compteur d'une carte : son nombre en grand, ce qu'il compte ; « à toi » en ambre quand quelque chose attend. */
@Composable
internal fun Counter(n: Int, label: String, modifier: Modifier = Modifier, you: Boolean = false) {
    val c = toneOf(StateTone.YOU)
    Column(
        modifier.clip(RoundedCornerShape(12.dp)).background(if (you) c.container else MaterialTheme.colorScheme.surfaceContainerLow).padding(horizontal = 12.dp, vertical = 8.dp),
    ) {
        Text(n.toString(), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, color = if (you) c.ink else MaterialTheme.colorScheme.onSurface)
        Text(label, style = MaterialTheme.typography.bodySmall, color = if (you) c.ink else MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2)
    }
}
