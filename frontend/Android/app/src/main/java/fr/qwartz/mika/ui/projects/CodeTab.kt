package fr.qwartz.mika.ui.projects

import androidx.compose.foundation.background
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.projects.Branch
import fr.qwartz.mika.data.moi.projects.CodePages
import fr.qwartz.mika.data.moi.projects.CodePull
import fr.qwartz.mika.data.moi.projects.CodeSummary
import fr.qwartz.mika.data.moi.projects.CodeTabs
import fr.qwartz.mika.data.moi.projects.Issue
import fr.qwartz.mika.data.moi.projects.Sheet
import fr.qwartz.mika.data.moi.projects.StateTone
import fr.qwartz.mika.data.moi.projects.TrackedChecks
import fr.qwartz.mika.data.moi.projects.TreeRow
import fr.qwartz.mika.data.moi.projects.branchAbout
import fr.qwartz.mika.data.moi.projects.byDay
import fr.qwartz.mika.data.moi.projects.checksTone
import fr.qwartz.mika.data.moi.projects.hiddenWords
import fr.qwartz.mika.data.moi.projects.issueTitle
import fr.qwartz.mika.data.moi.projects.issueTone
import fr.qwartz.mika.data.moi.projects.plural
import fr.qwartz.mika.data.moi.projects.pullColor
import fr.qwartz.mika.data.moi.projects.pullKey
import fr.qwartz.mika.data.moi.projects.pullLive
import fr.qwartz.mika.data.moi.projects.pullTitle
import fr.qwartz.mika.data.moi.projects.since
import fr.qwartz.mika.data.moi.projects.treeRows
import fr.qwartz.mika.data.moi.projects.keyed
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.Shell

/*
 * L'onglet Code d'une fiche (ADR 0296) : ses six volets, dans une barre qui défile en largeur — Fichiers (le choix de
 * la branche, l'arborescence un dossier à la fois), Commits (la ligne de temps par jour, le filtre par branche, la
 * suite à la demande), Pull requests, Branches, Issues, CI. Chaque ligne ouvre son détail en page (`Route.ProjectCode`).
 * Le dépôt en bref (`GET …/code`) dit s'il y a un dépôt, et ce qu'elle peut en faire.
 */

/** La page d'une pull request : par son numéro, ou par son objectif tant qu'elle n'en a pas. */
internal fun pullPage(project: Int, number: Int, objective: Int, pane: String = ""): Route =
    Route.ProjectCode(project, CodePages.PULL, if (number > 0) number.toString() else "o$objective", pane = pane)

@Composable
internal fun CodeTab(graph: AppGraph, vm: ProjectViewModel, sheet: Sheet, now: Long, sub: String) {
    val shell = LocalShell.current
    val code = rememberCodeModel(graph, vm.id)
    val shown = CodeTabs.of(sub)
    Toasts(code.gestures)
    OnResume(code, project = vm.id) { code.resume() }
    LaunchedEffect(code, shown) { code.show(shown) }
    // tirer pour relire : la fiche se relit (son modèle), et le code avec elle
    LaunchedEffect(vm.refreshing) { if (vm.refreshing) code.reload() }
    when (val load = code.summary.load) {
        null, Load.Loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        is Load.Failed -> Still {
            RefusalNote(load.error.message)
            OutlinedButton(onClick = code.summary::retry) { Text(stringResource(R.string.retry)) }
        }
        is Load.Ready -> if (!load.value.hasRepo) {
            Still { EmptyNote(R.drawable.ic_m_code, stringResource(R.string.proj_code_no_repo), stringResource(R.string.proj_code_no_repo_sub)) }
        } else {
            val s = load.value
            Column(Modifier.fillMaxSize()) {
                ChipRow(
                    CodeTabs.ALL.map { Chip(it, codeTabLabel(it), CodeTabs.count(it, s.counts)) },
                    selected = shown,
                    onPick = { if (it != shown) shell.replace(Route.Project(vm.id, CodeTabs.tab(it))) },
                    modifier = Modifier.padding(top = 4.dp),
                )
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                when (shown) {
                    CodeTabs.COMMITS -> CommitsList(code, shell, now)
                    CodeTabs.PULLS -> PullsList(code, shell, now)
                    CodeTabs.BRANCHES -> BranchesList(code, s, shell, now)
                    CodeTabs.ISSUES -> IssuesList(code, shell, now)
                    CodeTabs.CI -> ChecksListView(code, shell, now)
                    else -> FilesList(code, s, shell)
                }
            }
        }
    }
}

/** Un volet sans liste (une lecture refusée, pas de dépôt) : il défile quand même, pour qu'on puisse tirer et relire. */
@Composable
private fun Still(content: @Composable () -> Unit) {
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { content() }
    }
}

/** Une liste d'un volet : en cours, refusée (en mots, et « Réessayer »), ou lue. */
@Composable
private fun <T> Listed(load: Load<T>?, onRetry: () -> Unit, content: LazyListScope.(T) -> Unit) {
    when (load) {
        null, Load.Loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        is Load.Failed -> Still {
            RefusalNote(load.error.message)
            OutlinedButton(onClick = onRetry) { Text(stringResource(R.string.retry)) }
        }
        is Load.Ready -> LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) { content(load.value) }
    }
}

/** Le titre d'une liste : ce que c'est, et son compte en mots. */
@Composable
private fun ListTitle(title: String, count: String) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
        Spacer(Modifier.width(10.dp))
        MetaText(count)
    }
}

/** Une ligne d'une liste : sa tuile à la couleur de son état, son titre, puis ce qu'on en dit en petit. */
@Composable
private fun ListRow(
    icon: Int,
    tone: StateTone,
    title: String,
    onClick: () -> Unit,
    mono: Boolean = false,
    yours: Boolean = false,
    sub: @Composable () -> Unit,
) {
    Column(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Row(Modifier.padding(start = 6.dp, end = 16.dp, top = 12.dp, bottom = 12.dp), verticalAlignment = Alignment.Top) {
            // un point ambre : c'est à toi
            Box(Modifier.padding(top = 14.dp).size(6.dp).background(if (yours) toneOf(StateTone.YOU).bar else Color.Transparent, CircleShape))
            Spacer(Modifier.width(4.dp))
            Tile(icon, tone, 36.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    title,
                    style = MaterialTheme.typography.titleSmall.let { if (mono) it.copy(fontFamily = FontFamily.Monospace) else it },
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Gap(5.dp)
                sub()
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    }
}

/** Sous le titre d'une ligne : des pastilles et des mots, puis depuis quand, au bout. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RowFacts(age: String, content: @Composable () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        FlowRow(
            Modifier.weight(1f),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
            itemVerticalAlignment = Alignment.CenterVertically,
        ) { content() }
        if (age.isNotBlank()) {
            Spacer(Modifier.width(8.dp))
            Text(age, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
        }
    }
}

/** Le choix d'une branche : celle qu'on lit, et les autres dans un menu ; [all] : « Toutes les branches » (les commits). */
@Composable
private fun BranchPicker(label: String, names: List<String>, selected: String, all: String?, onPick: (String) -> Unit, modifier: Modifier = Modifier) {
    var open by remember { mutableStateOf(false) }
    Box(modifier) {
        OutlinedButton(onClick = { open = true }, modifier = Modifier.fillMaxWidth(), contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp)) {
            MIcon(R.drawable.ic_m_branch, stringResource(R.string.proj_code_branch_pick), size = 16.dp)
            Spacer(Modifier.width(8.dp))
            Text(
                label,
                style = MaterialTheme.typography.labelLarge.copy(fontFamily = FontFamily.Monospace),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            MIcon(R.drawable.ic_m_chev_down, null, size = 16.dp)
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            if (all != null) {
                DropdownMenuItem(
                    text = { Text(all, fontWeight = if (selected.isEmpty()) FontWeight.Bold else FontWeight.Normal) },
                    leadingIcon = { MIcon(R.drawable.ic_m_commit, null, size = 18.dp) },
                    onClick = {
                        open = false
                        onPick("")
                    },
                )
                HorizontalDivider()
            }
            for (name in names) {
                DropdownMenuItem(
                    text = { Text(name, fontFamily = FontFamily.Monospace, fontWeight = if (name == selected) FontWeight.Bold else FontWeight.Normal) },
                    leadingIcon = { MIcon(if (name == selected) R.drawable.ic_m_check else R.drawable.ic_m_branch, null, size = 18.dp) },
                    onClick = {
                        open = false
                        onPick(name)
                    },
                )
            }
        }
    }
}

// ── Fichiers ────────────────────────────────────────────────────────────

/**
 * L'arborescence, un dossier à la fois : un dossier ne se lit qu'en s'ouvrant, à la branche choisie ; un fichier ouvre
 * sa page. Sans le droit sur ses fichiers, le serveur le dit avec ses mots.
 */
@Composable
private fun FilesList(code: CodeViewModel, s: CodeSummary, shell: Shell) {
    val names = code.branches.value?.items.orEmpty().map { it.name }
    val branch = code.filesBranch
    val rows = treeRows(
        "",
        read = { (code.trees[it] as? Load.Ready)?.value },
        failed = { (code.trees[it] as? Load.Failed)?.error?.message.orEmpty() },
        open = code.open,
    )
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
        item(key = "pick") {
            BranchPicker(branch.ifBlank { s.base }, names, branch, null, { code.pickFilesRef(if (it == s.base) "" else it) }, Modifier.padding(horizontal = 12.dp, vertical = 8.dp))
        }
        if (rows.isEmpty()) item(key = "empty") { Box(Modifier.padding(16.dp)) { Muted(stringResource(R.string.proj_code_dir_empty)) } }
        itemsIndexed(rows, key = { i, r -> "$i:${r.depth}" }) { _, row ->
            when (row) {
                is TreeRow.Node -> TreeNode(row) {
                    if (row.entry.kind == "dir") code.fold(row.entry.path) else shell.navigate(Route.ProjectCode(code.id, CodePages.FILE, row.entry.path, ref = code.filesRef))
                }
                is TreeRow.Pending -> TreeNote(row.depth, R.drawable.ic_m_refresh, row.error.ifBlank { stringResource(R.string.proj_code_reading) }, failed = row.error.isNotBlank()) {
                    code.loadTree(row.dir)
                }
                is TreeRow.Hidden -> TreeNote(row.depth, R.drawable.ic_m_lock, "${hiddenWords(row.count)} — ${stringResource(R.string.proj_code_hidden_why)}", failed = false, onRetry = null)
            }
        }
    }
}

@Composable
private fun TreeNode(row: TreeRow.Node, onClick: () -> Unit) {
    val e = row.entry
    val dir = e.kind == "dir"
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(start = 12.dp + 18.dp * row.depth, end = 16.dp, top = 10.dp, bottom = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (dir) {
            MIcon(if (row.open) R.drawable.ic_m_chev_down else R.drawable.ic_m_chev_right, null, size = 14.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            Spacer(Modifier.width(14.dp))
        }
        Spacer(Modifier.width(6.dp))
        MIcon(
            when (e.kind) {
                "dir" -> R.drawable.ic_m_folder
                "file" -> R.drawable.ic_m_file
                else -> R.drawable.ic_m_link
            },
            null,
            size = 18.dp,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.width(8.dp))
        Text(
            e.name,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = if (dir) FontWeight.SemiBold else FontWeight.Normal,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f, fill = false),
        )
        // un lien symbolique, un sous-module : dit, jamais suivi
        if (e.kind != "dir" && e.kind != "file" && e.kindLabel.isNotBlank()) {
            Spacer(Modifier.width(8.dp))
            MetaText(e.kindLabel)
        }
    }
}

/** Une ligne de l'arborescence qui n'est pas une entrée : un dossier qui se lit, qui ne se lit pas, ce qu'il tait. */
@Composable
private fun TreeNote(depth: Int, icon: Int, text: String, failed: Boolean, onRetry: (() -> Unit)?) {
    Row(
        Modifier.fillMaxWidth().then(if (failed && onRetry != null) Modifier.clickable(onClick = onRetry) else Modifier)
            .padding(start = 32.dp + 18.dp * depth, end = 16.dp, top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        MIcon(icon, null, size = 16.dp, tint = if (failed) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.width(8.dp))
        Text(text, style = MaterialTheme.typography.bodySmall, color = if (failed) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

// ── Commits ─────────────────────────────────────────────────────────────

/** La ligne de temps des commits, par jour : le filtre par branche, leur compte, et la suite à la demande. */
@Composable
private fun CommitsList(code: CodeViewModel, shell: Shell, now: Long) {
    val names = code.branches.value?.items.orEmpty().map { it.name }
    val all = stringResource(R.string.proj_code_all_branches)
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            BranchPicker(code.commitsRef.ifEmpty { all }, names, code.commitsRef, all, code::pickCommitsRef, Modifier.weight(1f))
            code.commits?.valueOrNull?.let {
                Spacer(Modifier.width(12.dp))
                MetaText(plural(it.total, "commit", "commits"))
            }
        }
        Listed(code.commits, { code.loadCommits() }) { _ ->
            val items = code.allCommits
            if (items.isEmpty()) {
                item(key = "none") { EmptyNote(R.drawable.ic_m_commit, stringResource(R.string.proj_code_commits_none), stringResource(R.string.proj_code_commits_none_sub)) }
            }
            // une clé par commit, unique dans toute la liste, quoi que rende le serveur
            byDay(keyed(items) { it.sha }, { it.value.at }, now).forEachIndexed { g, day ->
                item(key = "day$g", contentType = "day") { GroupLabel(day.label) }
                itemsIndexed(day.items, key = { _, row -> "c${row.key}" }, contentType = { _, _ -> "commit" }) { i, row ->
                    val c = row.value
                    CommitRow(c, last = i == day.items.lastIndex) { shell.navigate(Route.ProjectCode(code.id, CodePages.COMMIT, c.sha)) }
                }
            }
            val rest = code.commitsRest
            if (rest > 0) {
                item(key = "more") {
                    TextButton(onClick = code::more, enabled = !code.loadingMore, modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp)) {
                        MIcon(R.drawable.ic_m_chev_down, null, size = 16.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.proj_code_commits_more, rest))
                    }
                }
            }
        }
    }
}

// ── Pull requests ───────────────────────────────────────────────────────

/** Ses pull requests, les prêtes d'abord : son titre, son état en pastille, son numéro, depuis quand ; un point quand elle attend ta fusion. */
@Composable
private fun PullsList(code: CodeViewModel, shell: Shell, now: Long) {
    Listed(code.pulls.load, code.pulls::retry) { page ->
        item(key = "title") {
            ListTitle(stringResource(R.string.proj_code_tab_pulls), plural(page.items.count { pullLive(it) }, "ouverte", "ouvertes"))
        }
        if (page.items.isEmpty()) {
            item(key = "none") { EmptyNote(R.drawable.ic_m_pr, stringResource(R.string.proj_code_pulls_none), stringResource(R.string.proj_code_pulls_none_sub)) }
        }
        itemsIndexed(page.items, key = { i, p -> "${pullKey(p)}:$i" }) { _, p -> PullRow(p, now) { shell.navigate(Route.ProjectCode(code.id, CodePages.PULL, pullKey(p))) } }
        if (page.total > page.items.size) {
            item(key = "more") { Hint(plural(page.total - page.items.size, "autre pull request, plus ancienne.", "autres pull requests, plus anciennes."), modifier = Modifier.padding(12.dp)) }
        }
    }
}

@Composable
private fun PullRow(p: CodePull, now: Long, onClick: () -> Unit) {
    val tone = pullColor(p)
    ListRow(if (p.state == "merged") R.drawable.ic_m_merge else R.drawable.ic_m_pr, tone, pullTitle(p), onClick, yours = p.merge.can) {
        RowFacts(since(p.at, now)) {
            StatePill(tone, p.stateLabel)
            if (p.number > 0) MetaText(stringResource(R.string.proj_number, p.number))
        }
    }
}

// ── Branches ────────────────────────────────────────────────────────────

/** Ses branches, la base d'abord : pour quoi elle existe, son avance et son retard, son dernier commit, sa pull request. */
@Composable
private fun BranchesList(code: CodeViewModel, s: CodeSummary, shell: Shell, now: Long) {
    Listed(code.branches.load, code.branches::retry) { list ->
        if (list.items.isEmpty()) {
            item(key = "none") { EmptyNote(R.drawable.ic_m_branch, stringResource(R.string.proj_code_branches_none), stringResource(R.string.proj_code_branches_none_sub)) }
        }
        itemsIndexed(list.items, key = { i, b -> "${b.name}:$i" }) { _, b -> BranchRow(b, now) { shell.navigate(Route.ProjectCode(code.id, CodePages.BRANCH, b.name)) } }
        if (s.remote.byPulls && list.items.isNotEmpty()) {
            item(key = "flow") { Hint(stringResource(R.string.proj_code_by_pulls, list.base), modifier = Modifier.padding(12.dp)) }
        }
    }
}

@Composable
private fun BranchRow(b: Branch, now: Long, onClick: () -> Unit) {
    ListRow(R.drawable.ic_m_branch, if (b.base) StateTone.WAIT else StateTone.WORK, b.name, onClick, mono = true) {
        RowFacts("") {
            val pull = b.pull
            when {
                pull != null -> StatePill(pullColor(pull), pull.stateLabel)
                else -> MetaText(stringResource(if (b.base) R.string.proj_code_branch_default else R.string.proj_code_branch_no_pull))
            }
            MetaText(branchAbout(b))
            // son retard et son avance sur la base
            if (!b.base) MetaText("−${b.behind} · +${b.ahead}")
        }
        if (b.head.sha.isNotBlank()) {
            Gap(5.dp)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Code(b.head.short)
                Spacer(Modifier.width(8.dp))
                Text(b.head.title, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                Spacer(Modifier.width(8.dp))
                Text(since(b.head.at, now), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
            }
        }
    }
}

// ── Issues ──────────────────────────────────────────────────────────────

/** Les issues du dépôt, relues chez l'hôte, et celles que ses tickets connaissent ; si l'hôte ne répond pas, ses mots le disent. */
@Composable
private fun IssuesList(code: CodeViewModel, shell: Shell, now: Long) {
    Listed(code.issues.load, code.issues::retry) { page ->
        item(key = "title") {
            ListTitle(stringResource(R.string.proj_code_tab_issues), plural(page.items.count { it.state == "open" }, "ouverte", "ouvertes"))
        }
        if (page.error.isNotBlank()) item(key = "error") { Banner(StateTone.FAIL, R.drawable.ic_m_alert, page.error, Modifier.padding(horizontal = 12.dp, vertical = 4.dp)) }
        if (page.items.isEmpty()) {
            item(key = "none") { EmptyNote(R.drawable.ic_m_issue, stringResource(R.string.proj_code_issues_none), stringResource(R.string.proj_code_issues_none_sub)) }
        }
        itemsIndexed(page.items, key = { i, x -> "${x.number}:$i" }) { _, x -> IssueRow(x, now) { shell.navigate(Route.ProjectCode(code.id, CodePages.ISSUE, x.number.toString())) } }
    }
}

/** Une issue : son titre est celui de l'hôte, posé tel quel ; venue d'ailleurs, elle le dit. */
@Composable
private fun IssueRow(x: Issue, now: Long, onClick: () -> Unit) {
    val tone = issueTone(x.state)
    ListRow(R.drawable.ic_m_issue, tone, issueTitle(x), onClick, yours = x.ticket?.yours == true) {
        RowFacts(since(x.at, now)) {
            StatePill(tone, x.stateLabel)
            if (!x.fromHere) OutsideMark()
            MetaText(stringResource(R.string.proj_number, x.number))
        }
    }
}

// ── CI ──────────────────────────────────────────────────────────────────

/** Les vérifications que le moteur suit, par commit — celui de chaque pull request —, les plus récentes d'abord. */
@Composable
private fun ChecksListView(code: CodeViewModel, shell: Shell, now: Long) {
    Listed(code.checks.load, code.checks::retry) { list ->
        item(key = "title") { ListTitle(stringResource(R.string.proj_code_side_checks), "") }
        if (list.items.isEmpty()) {
            item(key = "none") { EmptyNote(R.drawable.ic_m_bolt, stringResource(R.string.proj_code_ci_none), stringResource(R.string.proj_code_ci_none_sub)) }
        }
        itemsIndexed(list.items, key = { i, x -> "${x.sha}:$i" }) { _, x -> ChecksRow(x, now) { shell.navigate(Route.ProjectCode(code.id, CodePages.CHECKS, x.sha)) } }
    }
}

@Composable
private fun ChecksRow(x: TrackedChecks, now: Long, onClick: () -> Unit) {
    val tone = checksTone(x.state)
    val title = x.commit?.title?.takeIf { it.isNotBlank() } ?: x.objective?.text?.takeIf { it.isNotBlank() } ?: x.branch
    ListRow(R.drawable.ic_m_bolt, tone, title, onClick) {
        RowFacts(since(x.at, now)) {
            StatePill(tone, x.stateLabel)
            Code(x.sha.take(7))
            if (x.commit?.outside == true) OutsideMark()
        }
    }
}
