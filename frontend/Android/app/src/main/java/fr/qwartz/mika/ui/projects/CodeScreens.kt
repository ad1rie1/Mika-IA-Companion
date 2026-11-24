package fr.qwartz.mika.ui.projects

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.projects.Blob
import fr.qwartz.mika.data.moi.projects.BranchDetail
import fr.qwartz.mika.data.moi.projects.CodePages
import fr.qwartz.mika.data.moi.projects.CodeTabs
import fr.qwartz.mika.data.moi.projects.CommitDetail
import fr.qwartz.mika.data.moi.projects.StateTone
import fr.qwartz.mika.data.moi.projects.aheadBehind
import fr.qwartz.mika.data.moi.projects.isMarkdown
import fr.qwartz.mika.data.moi.projects.languageOf
import fr.qwartz.mika.data.moi.projects.messageRest
import fr.qwartz.mika.data.moi.projects.moment
import fr.qwartz.mika.data.moi.projects.plural
import fr.qwartz.mika.data.moi.projects.sizeWords
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.rememberSessionKey

/*
 * Les pages de détail de ce que lit l'atelier (ADR 0296) : **un fichier** (en chasse fixe avec ses numéros de ligne ;
 * un fichier Markdown rendu, avec sa bascule Rendu et Source ; son dernier commit et son historique dans « Infos » ; un
 * fichier binaire, trop gros ou caché se dit avec les mots du serveur), **un commit** (son message, ses fichiers
 * changés avec leurs comptes, leur diff unifié replié fichier par fichier) et **une branche** (ce qu'elle a d'avance,
 * sa pull request, son objectif). Les pages de ce qui se joue avec l'hôte sont dans `CodeHostScreens.kt`.
 */

private const val PANE_MAIN = "contenu"
private const val PANE_INFOS = "infos"

/** Une page du code d'un projet : celle que son adresse nomme. */
@Composable
fun CodeScreen(graph: AppGraph, route: Route.ProjectCode) {
    when (route.kind) {
        CodePages.COMMIT -> CommitScreen(graph, route)
        CodePages.PULL -> PullScreen(graph, route)
        CodePages.BRANCH -> BranchScreen(graph, route)
        CodePages.ISSUE -> IssueScreen(graph, route)
        CodePages.CHECKS -> ChecksScreen(graph, route)
        else -> FileScreen(graph, route)
    }
}

// ── Un fichier ──────────────────────────────────────────────────────────

@Composable
private fun FileScreen(graph: AppGraph, route: Route.ProjectCode) {
    val frame = rememberCodeFrame(graph, route.id)
    val session = rememberSessionKey(graph)
    val vm: FileViewModel = viewModel(key = "code-file|$session|${route.id}|${route.ref}|${route.key}") {
        FileViewModel(ProjectsDeps(graph), route.id, route.ref, route.key)
    }
    Toasts(vm.gestures)
    OnResume(vm, project = route.id) { vm.resume() }
    var pane by rememberSaveable(route.id, route.key, route.ref) { mutableStateOf(PANE_MAIN) }
    var source by rememberSaveable(route.id, route.key, route.ref) { mutableStateOf(false) }
    val blob = vm.read.value
    // ses lignes telles qu'on les pose (tabulations en espaces, coupées au-delà de ce qu'une ligne montre) : le modèle
    // les a mises en place hors du fil principal, avant de montrer le fichier — ici, seule la plus large se mesure
    val laid = blob?.laid
    val lines = laid?.lines.orEmpty()
    val measure = rememberCodeMeasure()
    val width = remember(laid, measure) { measure.width(laid?.widest.orEmpty()) }
    val numbers = remember(lines.size, measure) { measure.numbers(maxOf(2, lines.size.toString().length)) }
    val scroll = rememberScrollState()
    val copy = rememberCopy()
    CodePage(
        home = CodeTabs.FILES,
        projectTitle = frame.project.sheet.valueOrNull?.project?.title,
        load = vm.read.load,
        onRetry = vm.read::retry,
        panes = { listOf(Pane(PANE_MAIN, stringResource(R.string.proj_code_pane_file)), Pane(PANE_INFOS, stringResource(R.string.proj_pane_infos))) },
        pane = pane,
        onPane = { pane = it },
        head = { f -> FileHead(f, source, onSource = { source = it }, onCopy = { copy(f.path) }) },
    ) { f ->
        when {
            pane == PANE_INFOS -> paneBlock("infos") { FileInfos(f, frame, route.id) }
            // binaire, trop gros, un lien symbolique, un sous-module : ce que c'est, et pourquoi il ne dit pas son contenu
            !f.readable -> item(key = "why") { EmptyNote(R.drawable.ic_m_file, f.kindLabel, f.why) }
            isMarkdown(f.path) && !source -> paneBlock("rendered") {
                Hint(stringResource(R.string.proj_code_md_note), R.drawable.ic_m_eye)
                RepoMarkdown(vm.rendered)
            }
            else -> {
                if (laid?.cut == true) paneBlock("cut") { Hint(stringResource(R.string.proj_code_lines_cut)) }
                sourceLines(lines, f.path, width, numbers, scroll)
            }
        }
    }
}

/** L'en-tête d'un fichier : son chemin en chasse fixe, ses lignes, copier son chemin ; pour un Markdown, Rendu ou Source. */
@Composable
private fun FileHead(f: Blob, source: Boolean, onSource: (Boolean) -> Unit, onCopy: () -> Unit) {
    Column(Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, top = 12.dp, bottom = 8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                f.path,
                style = MaterialTheme.typography.titleSmall.copy(fontFamily = FontFamily.Monospace),
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f),
            )
            SmallAction(R.drawable.ic_m_copy, stringResource(R.string.proj_code_copy_path), onClick = onCopy)
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (f.readable) MetaText(plural(f.lines, "ligne", "lignes"))
            MetaText(sizeWords(f.size))
            if (f.readable && isMarkdown(f.path)) {
                Spacer(Modifier.weight(1f))
                FilterChip(selected = !source, onClick = { onSource(false) }, label = { Text(stringResource(R.string.proj_code_md_rendered)) })
                FilterChip(selected = source, onClick = { onSource(true) }, label = { Text(stringResource(R.string.proj_code_md_source)) })
                Spacer(Modifier.width(8.dp))
            }
        }
    }
}

/** « Infos » d'un fichier : son dernier commit, ce qu'il est (sa branche, ses lignes, son poids, son langage), son historique. */
@Composable
private fun FileInfos(f: Blob, frame: CodeFrame, project: Int) {
    val open: (String) -> Unit = { sha -> frame.shell.navigate(Route.ProjectCode(project, CodePages.COMMIT, sha)) }
    Column {
        SideTitle(stringResource(R.string.proj_code_last_commit))
        val last = f.lastCommit
        if (last == null) Muted(stringResource(R.string.proj_code_last_commit_none)) else CommitLine(last, frame.now) { open(last.sha) }
        SideTitle(stringResource(R.string.proj_code_the_file))
        Fact(stringResource(R.string.proj_code_fact_branch)) { BranchChip(f.ref) }
        if (f.readable) Fact(stringResource(R.string.proj_code_fact_lines), f.lines.toString())
        Fact(stringResource(R.string.proj_code_fact_size), sizeWords(f.size))
        Fact(stringResource(R.string.proj_code_fact_language), if (f.readable) languageOf(f.path) else f.kindLabel)
        Gap(8.dp)
        HostButton(f.url)
        val older = f.history.drop(1)
        if (older.isNotEmpty()) {
            SideTitle("${stringResource(R.string.proj_code_history)} · ${f.historyTotal}")
            for (c in older) CommitLine(c, frame.now) { open(c.sha) }
        }
    }
}

// ── Un commit ───────────────────────────────────────────────────────────

@Composable
private fun CommitScreen(graph: AppGraph, route: Route.ProjectCode) {
    val frame = rememberCodeFrame(graph, route.id)
    val session = rememberSessionKey(graph)
    val vm: CommitViewModel = viewModel(key = "code-commit|$session|${route.id}|${route.key}") { CommitViewModel(ProjectsDeps(graph), route.id, route.key) }
    Toasts(vm.gestures)
    OnResume(vm, project = route.id) { vm.resume() }
    var pane by rememberSaveable(route.id, route.key, route.ref) { mutableStateOf(PANE_MAIN) }
    val diffUi = rememberDiffUi()
    val copy = rememberCopy()
    CodePage(
        home = CodeTabs.COMMITS,
        projectTitle = frame.project.sheet.valueOrNull?.project?.title,
        load = vm.detail.load,
        onRetry = vm.detail::retry,
        panes = { d ->
            listOf(
                Pane(PANE_MAIN, stringResource(R.string.proj_code_pane_diff), if (d.diff.filesReadable && d.diff.files.isNotEmpty()) d.diff.files.size.toString() else ""),
                Pane(PANE_INFOS, stringResource(R.string.proj_pane_infos)),
            )
        },
        pane = pane,
        onPane = { pane = it },
        head = { d -> CommitHead(d, frame.now) { copy(d.commit.sha) } },
    ) { d ->
        if (pane == PANE_INFOS) {
            paneBlock("infos") { CommitInfos(d, frame, route.id) }
        } else {
            val rest = messageRest(d.commit)
            if (rest.isNotBlank()) {
                paneBlock("message") {
                    // le message d'un commit venu du dépôt distant n'est pas d'elle : cité, en texte brut
                    if (d.commit.outside) OutsideBlock(stringResource(R.string.proj_code_commit_outside), rest, mono = true) else Text(rest, style = MaterialTheme.typography.bodyMedium)
                }
            }
            diffZone(d.diff, diffUi, vm.whole.files, vm.whole::read)
        }
    }
}

/** L'en-tête d'un commit : son message, qui l'a signé et quand, sa branche, d'où il vient ; son empreinte, à copier. */
@Composable
private fun CommitHead(d: CommitDetail, now: Long, onCopy: () -> Unit) {
    val c = d.commit
    CodeHead(
        icon = if (c.merge) R.drawable.ic_m_merge else R.drawable.ic_m_commit,
        tone = if (c.merge) StateTone.DONE else StateTone.WORK,
        over = stringResource(if (c.merge) R.string.proj_code_commit_merge else R.string.proj_code_commit),
        title = c.title,
        meta = {
            MetaText(c.author)
            MetaText(moment(c.at, now))
            BranchChip(c.branch)
            if (c.outside) OutsideMark()
        },
        actions = {
            OutlinedButton(onClick = onCopy) {
                MIcon(R.drawable.ic_m_copy, stringResource(R.string.proj_code_copy_sha), size = 16.dp)
                Spacer(Modifier.width(6.dp))
                Text(c.sha.take(12), fontFamily = FontFamily.Monospace)
            }
        },
    )
}

/** « Infos » d'un commit : qui, quand, sa branche, son empreinte, sa page chez l'hôte ; et ce qui lui est lié. */
@Composable
private fun CommitInfos(d: CommitDetail, frame: CodeFrame, project: Int) {
    val c = d.commit
    Column {
        SideTitle(stringResource(R.string.proj_code_the_commit))
        Fact(stringResource(R.string.proj_code_fact_author), c.author)
        Fact(stringResource(R.string.proj_code_fact_when), moment(c.at, frame.now))
        if (c.branch.isNotBlank()) Fact(stringResource(R.string.proj_code_fact_branch)) { BranchChip(c.branch) }
        Fact(stringResource(R.string.proj_code_fact_sha)) { Code(c.short) }
        Gap(8.dp)
        HostButton(c.url)
        SideTitle(stringResource(R.string.proj_side_linked))
        LinkedCode(project, d.linked, frame.now)
    }
}

// ── Une branche ─────────────────────────────────────────────────────────

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun BranchScreen(graph: AppGraph, route: Route.ProjectCode) {
    val frame = rememberCodeFrame(graph, route.id)
    val session = rememberSessionKey(graph)
    val vm: CodeReadViewModel<BranchDetail> = viewModel(key = "code-branch|$session|${route.id}|${route.key}") { branchModel(ProjectsDeps(graph), route.id, route.key) }
    Toasts(vm.gestures)
    OnResume(vm, project = route.id) { vm.resume() }
    val base = frame.code.summary.value?.base.orEmpty()
    // « Ses fichiers », « Ses commits » : le volet de l'onglet s'ouvre sur cette branche
    val aim: (String) -> Unit = { sub ->
        frame.code.aim(sub, route.key)
        frame.shell.navigate(Route.Project(route.id, CodeTabs.tab(sub)))
    }
    CodePage(
        home = CodeTabs.BRANCHES,
        projectTitle = frame.project.sheet.valueOrNull?.project?.title,
        load = vm.read.load,
        onRetry = vm.read::retry,
        panes = { listOf(Pane(PANE_MAIN, stringResource(R.string.proj_code_branch))) },
        pane = PANE_MAIN,
        onPane = {},
        head = { d ->
            val b = d.branch
            CodeHead(
                icon = R.drawable.ic_m_branch,
                tone = if (b.base) StateTone.WAIT else StateTone.WORK,
                over = stringResource(R.string.proj_code_branch),
                title = b.name,
                mono = true,
                meta = { MetaText(aheadBehind(b, base)) },
                actions = {
                    OutlinedButton(onClick = { aim(CodeTabs.FILES) }, modifier = Modifier.weight(1f)) {
                        MIcon(R.drawable.ic_m_folder, null, size = 18.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.proj_code_branch_files), maxLines = 1)
                    }
                    OutlinedButton(onClick = { aim(CodeTabs.COMMITS) }, modifier = Modifier.weight(1f)) {
                        MIcon(R.drawable.ic_m_commit, null, size = 18.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.proj_code_branch_commits), maxLines = 1)
                    }
                },
            )
        },
    ) { d ->
        val b = d.branch
        paneBlock("branch") {
            Column {
                if (b.pull != null || !b.base) {
                    SideTitle(stringResource(R.string.proj_code_side_pull))
                    if (b.pull == null) Muted(stringResource(R.string.proj_code_pull_not_yet)) else PullLinked(route.id, b.pull, b.objective)
                }
                if (b.objective != null || b.ticket != null) {
                    SideTitle(stringResource(R.string.proj_code_side_for))
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        ObjectiveLinked(route.id, b.objective)
                        TicketLinked(route.id, b.ticket)
                    }
                }
                val commits = if (b.base) listOfNotNull(b.head.takeIf { it.sha.isNotBlank() }) else d.commits
                SideTitle(if (b.base) stringResource(R.string.proj_code_side_head) else "${stringResource(R.string.proj_code_side_ahead)} · ${d.commits.size}")
                for (c in commits) CommitLine(c, frame.now) { frame.shell.navigate(Route.ProjectCode(route.id, CodePages.COMMIT, c.sha)) }
                // ses fichiers changés avec leurs comptes, sans leurs passages : son diff se lit dans sa pull request, ou commit par commit
                if (d.diff.filesReadable && d.diff.files.isNotEmpty()) {
                    SideTitle("${stringResource(R.string.proj_code_side_changed)} · ${d.diff.files.size}")
                    for (f in d.diff.files) {
                        Row(Modifier.fillMaxWidth().padding(vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
                            MIcon(R.drawable.ic_m_file, null, size = 16.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                            Spacer(Modifier.width(8.dp))
                            Text(f.path, style = codeStyle(), modifier = Modifier.weight(1f))
                            if (f.status != "modified" && f.statusLabel.isNotBlank()) {
                                Spacer(Modifier.width(8.dp))
                                MetaText(f.statusLabel)
                            }
                            Spacer(Modifier.width(10.dp))
                            PlusMinus(f.insertions, f.deletions)
                        }
                    }
                } else if (!d.diff.filesReadable && d.commits.isNotEmpty()) {
                    SideTitle(stringResource(R.string.proj_code_side_changed))
                    Hint(d.diff.filesWhy, R.drawable.ic_m_lock)
                }
            }
        }
    }
}
