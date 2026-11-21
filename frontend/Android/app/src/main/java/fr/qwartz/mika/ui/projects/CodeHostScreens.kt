package fr.qwartz.mika.ui.projects

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledIconButton
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.projects.AskFor
import fr.qwartz.mika.data.moi.projects.COMMENT_MAX
import fr.qwartz.mika.data.moi.projects.ChecksList
import fr.qwartz.mika.data.moi.projects.CodePages
import fr.qwartz.mika.data.moi.projects.CodePull
import fr.qwartz.mika.data.moi.projects.CodeTabs
import fr.qwartz.mika.data.moi.projects.HostChecks
import fr.qwartz.mika.data.moi.projects.Issue
import fr.qwartz.mika.data.moi.projects.MergeStage
import fr.qwartz.mika.data.moi.projects.MilestoneCan
import fr.qwartz.mika.data.moi.projects.PullDetail
import fr.qwartz.mika.data.moi.projects.PullHost
import fr.qwartz.mika.data.moi.projects.PullPanes
import fr.qwartz.mika.data.moi.projects.StateTone
import fr.qwartz.mika.data.moi.projects.TrackedChecks
import fr.qwartz.mika.data.moi.projects.byDay
import fr.qwartz.mika.data.moi.projects.checksLinked
import fr.qwartz.mika.data.moi.projects.checksShown
import fr.qwartz.mika.data.moi.projects.checksTail
import fr.qwartz.mika.data.moi.projects.checksTone
import fr.qwartz.mika.data.moi.projects.conflictsWords
import fr.qwartz.mika.data.moi.projects.hostText
import fr.qwartz.mika.data.moi.projects.issueSource
import fr.qwartz.mika.data.moi.projects.issueTitle
import fr.qwartz.mika.data.moi.projects.issueTone
import fr.qwartz.mika.data.moi.projects.mergeStage
import fr.qwartz.mika.data.moi.projects.moment
import fr.qwartz.mika.data.moi.projects.pullBranchWords
import fr.qwartz.mika.data.moi.projects.pullColor
import fr.qwartz.mika.data.moi.projects.pullLive
import fr.qwartz.mika.data.moi.projects.pullTitle
import fr.qwartz.mika.data.moi.projects.pullWhen
import fr.qwartz.mika.data.moi.projects.reviewTone
import fr.qwartz.mika.data.moi.projects.runsPassed
import fr.qwartz.mika.data.moi.projects.since
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.AskDialog
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.rememberSessionKey

/*
 * Les pages de détail de ce qui se joue avec l'hôte du dépôt (ADR 0296) : **une pull request** (ses volets Résumé —
 * les jalons et leurs preuves —, Commits, Fichiers, Échanges ; « Infos » : sa fusion, sa relecture, ses vérifications
 * une à une, ses conflits, sa branche, le ticket et l'objectif liés ; Modifier, répondre, **Fusionner**), **une issue**
 * (Description, Échanges ; « Infos » : son état chez l'hôte, le ticket lié et son étape, l'accepter ou l'écarter quand
 * le serveur le permet, l'accord en attente sur une réponse) et **les vérifications d'un commit** (une à une, la fin du
 * journal d'un échec).
 *
 * Aucune règle n'est refaite ici : Fusionner n'est actif que si le serveur le dit (`merge.can`), sinon sa raison se lit
 * telle quelle (`merge.why`, `merge.refused`) ; Modifier et répondre demandent `rights.pull_write`. **Tout texte de
 * l'hôte** — un titre, un texte, un commentaire, une étiquette, le nom d'une vérification, la fin d'un journal, un
 * compte — est posé tel quel, présenté comme venu d'ailleurs, jamais mis en forme ni rendu cliquable.
 */

private const val PANE_MAIN = "contenu"
private const val PANE_TALK = "echanges"
private const val PANE_LOG = "journal"
private const val PANE_INFOS = "infos"

// ── Une pull request ────────────────────────────────────────────────────

@Composable
internal fun PullScreen(graph: AppGraph, route: Route.ProjectCode) {
    val frame = rememberCodeFrame(graph, route.id)
    val session = rememberSessionKey(graph)
    val vm: PullViewModel = viewModel(key = "code-pull|$session|${route.id}|${route.key}") { PullViewModel(ProjectsDeps(graph), route.id, route.key) }
    Toasts(vm.gestures)
    OnResume(vm) { vm.resume() }
    val summary = frame.code.summary.value
    val remote = summary?.remote?.has == true
    val detail = vm.detail.value
    // ce que l'hôte en dit maintenant : dès qu'on la sait chez lui (un numéro, un dépôt distant)
    LaunchedEffect(vm, detail?.pull?.number, remote) { if (remote) vm.openHost() }
    // un geste abouti ou refusé change ce que l'onglet et la fiche en disent : ils se relisent
    LaunchedEffect(vm.revision) {
        if (vm.revision > 0) {
            frame.code.reload()
            frame.project.reload()
        }
    }
    var pane by rememberSaveable(route.key) { mutableStateOf(PullPanes.of(route.pane)) }
    var editing by remember { mutableStateOf(false) }
    val diffUi = rememberDiffUi()
    val p = detail?.pull
    // modifier et répondre : le droit servi, sur une pull request encore ouverte chez l'hôte
    val writes = p != null && frame.project.sheet.valueOrNull?.rights?.pullWrite == true && pullLive(p) && p.number > 0
    val canMerge = summary?.rights?.merge == true
    val busy = vm.gestures.busy.isNotEmpty() || vm.merge.reading
    val refusal = vm.gestures.refusalAt(PullViewModel.MERGE)
    CodePage(
        home = CodeTabs.PULLS,
        projectTitle = frame.project.sheet.valueOrNull?.project?.title,
        load = vm.detail.load,
        onRetry = vm.detail::retry,
        panes = { d ->
            listOf(
                Pane(PullPanes.SUMMARY, stringResource(R.string.proj_code_pane_summary)),
                Pane(PullPanes.COMMITS, stringResource(R.string.proj_code_tab_commits), d.commits.size.toString()),
                Pane(PullPanes.FILES, stringResource(R.string.proj_code_tab_files), if (d.diff.filesReadable) d.diff.files.size.toString() else ""),
                Pane(PullPanes.TALK, stringResource(R.string.proj_code_pane_talk), vm.host.value?.talk?.size?.toString().orEmpty()),
                Pane(PullPanes.INFOS, stringResource(R.string.proj_pane_infos)),
            )
        },
        pane = pane,
        onPane = { pane = it },
        head = { d -> PullHead(d.pull, frame.now, writes) { editing = true } },
        bottomBar = { d ->
            when {
                pane == PullPanes.TALK -> if (writes) ReplyBar(vm, busy)
                // prête, et c'est à elle : son bouton est sous la main ; « Infos » le porte aussi, avec son état
                pane != PullPanes.INFOS && canMerge && mergeStage(d.pull) == MergeStage.READY -> BottomBar { MergeButton(d.pull, busy, vm::askMerge) }
            }
        },
        // un refus de la fusion se dit là où était le bouton, avec les mots du serveur (« Infos » le dit dans « Fusion »)
        notice = { if (pane != PullPanes.INFOS && refusal.isNotBlank()) RefusalNote(refusal, Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp)) },
    ) { d ->
        when (pane) {
            PullPanes.COMMITS -> {
                if (d.commits.isEmpty()) paneBlock("none") { Muted(stringResource(R.string.proj_code_pull_no_commit)) }
                byDay(d.commits, { it.at }, frame.now).forEachIndexed { g, day ->
                    item(key = "day$g", contentType = "day") { GroupLabel(day.label) }
                    itemsIndexed(day.items, key = { _, c -> c.sha }, contentType = { _, _ -> "commit" }) { i, c ->
                        CommitRow(c, last = i == day.items.lastIndex) { frame.shell.navigate(Route.ProjectCode(route.id, CodePages.COMMIT, c.sha)) }
                    }
                }
            }
            PullPanes.FILES -> diffZone(d.diff, diffUi, vm.whole.files, vm.whole::read)
            PullPanes.TALK -> paneBlock("talk") { PullTalk(d.pull, vm, remote, frame.now) }
            PullPanes.INFOS -> paneBlock("infos") { PullInfos(d, vm, frame, canMerge, busy, route.id) }
            else -> paneBlock("summary") { PullSummary(d, frame) }
        }
    }
    vm.merge.asking?.let { MergeDialog(it, onConfirm = vm::confirmMerge, onDismiss = vm.merge::cancel) }
    if (editing && p != null) PullEditSheet(vm, p, remote) { editing = false }
}

/** Une barre de bas d'écran : le geste du moment, sous la main. */
@Composable
internal fun BottomBar(content: @Composable () -> Unit) {
    Surface(color = MaterialTheme.colorScheme.surface, tonalElevation = 3.dp, shadowElevation = 6.dp) {
        Box(Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 16.dp, vertical = 10.dp)) { content() }
    }
}

/** L'en-tête d'une pull request : son numéro, son titre, son état, sa branche vers sa base, depuis quand ; Modifier, Voir chez l'hôte. */
@Composable
private fun PullHead(p: CodePull, now: Long, writes: Boolean, onEdit: () -> Unit) {
    val tone = pullColor(p)
    val actions: (@Composable RowScope.() -> Unit)? = if (!writes && p.url.isBlank()) {
        null
    } else {
        {
            if (writes) {
                OutlinedButton(onClick = onEdit, modifier = Modifier.weight(1f)) {
                    MIcon(R.drawable.ic_m_pen, null, size = 18.dp)
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.proj_edit), maxLines = 1)
                }
            }
            HostButton(p.url, Modifier.weight(1f))
        }
    }
    CodeHead(
        icon = if (p.state == "merged") R.drawable.ic_m_merge else R.drawable.ic_m_pr,
        tone = tone,
        over = if (p.number > 0) stringResource(R.string.proj_pull_n, p.number) else stringResource(R.string.proj_code_pull),
        title = pullTitle(p),
        meta = {
            StatePill(tone, p.stateLabel)
            BranchChip(p.branch)
            if (p.base.isNotBlank()) {
                MIcon(R.drawable.ic_m_chev_right, null, size = 14.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                BranchChip(p.base)
            }
            MetaText(pullWhen(p, now))
        },
        actions = actions,
    )
}

/** « Résumé » : où en est sa fusion, ce qui la dit finie, ce qu'elle en dit, les jalons de son objectif et leurs preuves, le dernier mot de l'hôte. */
@Composable
private fun PullSummary(d: PullDetail, frame: CodeFrame) {
    val p = d.pull
    // l'état qui suit une demande de fusion (demandée, fusionnée, refusée avec les mots du serveur) se lit ici aussi
    MergeStatus(p, frame.now, held = false)
    if (p.doneWhen.isNotBlank()) {
        Column {
            SideTitle(stringResource(R.string.proj_code_done_when))
            MdText(p.doneWhen)
        }
    }
    if (p.result.isNotBlank()) {
        Column {
            SideTitle(stringResource(R.string.proj_code_her_word))
            MdText(p.result)
        }
    }
    Column {
        SideTitle(stringResource(R.string.proj_code_milestones))
        if (p.milestones.isEmpty()) Muted(stringResource(R.string.proj_code_milestones_none))
        // les jalons se lisent ici ; ils se valident et se changent dans leur objectif
        p.milestones.forEachIndexed { i, m ->
            StepView(m.copy(can = MilestoneCan()), last = i == p.milestones.lastIndex, settle = false, now = frame.now, shell = frame.shell, busy = false)
        }
    }
    hostText(p.said).takeIf { it.isNotBlank() }?.let { OutsideBlock(stringResource(R.string.proj_host_last_word), it) }
}

/** « Échanges » : ce que l'hôte en dit maintenant — son texte, ses commentaires —, cité tel quel. */
@Composable
private fun PullTalk(p: CodePull, vm: PullViewModel, remote: Boolean, now: Long) {
    RefusalNote(vm.gestures.refusalAt(PullViewModel.TALK))
    when {
        p.number <= 0 -> Muted(stringResource(R.string.proj_code_talk_not_there))
        !remote -> Muted(stringResource(R.string.proj_code_talk_no_remote))
        else -> when (val load: Load<PullHost>? = vm.host.load) {
            null, Load.Loading -> Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            is Load.Failed -> {
                RefusalNote(load.error.message)
                OutlinedButton(onClick = vm.host::retry) { Text(stringResource(R.string.retry)) }
            }
            is Load.Ready -> {
                val host = load.value
                Banner(StateTone.FAIL, R.drawable.ic_m_alert, host.error)
                hostText(host.body).takeIf { it.isNotBlank() }?.let { OutsideBlock(stringResource(R.string.proj_code_talk_body), it) }
                for (x in host.talk) RemarkView(x, now)
                if (host.talk.isEmpty() && host.error.isBlank()) Muted(stringResource(R.string.proj_code_talk_none))
                Hint(stringResource(R.string.proj_code_talk_quoted), R.drawable.ic_m_shield_check)
            }
        }
    }
}

/** Le champ d'Échanges, en bas : sa réponse part chez l'hôte, signée de son nom. */
@Composable
private fun ReplyBar(vm: PullViewModel, busy: Boolean) {
    Surface(color = MaterialTheme.colorScheme.surface, tonalElevation = 3.dp, shadowElevation = 6.dp) {
        Column(Modifier.fillMaxWidth().navigationBarsPadding().imePadding().padding(horizontal = 12.dp, vertical = 8.dp)) {
            Text(stringResource(R.string.proj_code_reply_word), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Gap(6.dp)
            Row(verticalAlignment = Alignment.Bottom) {
                OutlinedTextField(
                    value = vm.reply,
                    onValueChange = { vm.reply = it.take(COMMENT_MAX) },
                    placeholder = { Text(stringResource(R.string.proj_code_reply_hint)) },
                    maxLines = 5,
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(8.dp))
                FilledIconButton(onClick = vm::comment, enabled = vm.reply.isNotBlank() && !busy) { MIcon(R.drawable.ic_m_send, stringResource(R.string.proj_code_reply_send)) }
            }
        }
    }
}

/**
 * « Infos » d'une pull request (ce que le web met dans son panneau latéral) : sa fusion — son état, et son bouton s'il
 * est servi —, sa relecture, ses vérifications une à une, ses conflits, sa branche, le ticket et l'objectif liés.
 */
@Composable
private fun PullInfos(d: PullDetail, vm: PullViewModel, frame: CodeFrame, canMerge: Boolean, busy: Boolean, project: Int) {
    val p = d.pull
    val shell = frame.shell
    Column {
        SideTitle(stringResource(R.string.proj_code_side_merge))
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            RefusalNote(vm.gestures.refusalAt(PullViewModel.MERGE))
            MergeStatus(p, frame.now)
            val stage = mergeStage(p)
            if (canMerge && stage != MergeStage.MERGED && stage != MergeStage.ASKED) {
                MergeButton(p, busy, vm::askMerge)
                Hint(stringResource(R.string.proj_code_merge_yours))
            }
        }

        SideTitle(stringResource(R.string.proj_code_side_review))
        val review = p.review
        if (review == null) {
            Muted(stringResource(R.string.proj_code_review_none))
        } else {
            StateLine(R.drawable.ic_m_eye, reviewTone(review), review.label) {
                if (review.text.isNotBlank()) Text(review.text, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (review.lastRefusal.isNotBlank()) {
                    Text(stringResource(R.string.proj_code_review_refusal, review.lastRefusal), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }

        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.weight(1f)) { SideTitle(stringResource(R.string.proj_code_side_checks)) }
            p.checks?.let { StatePill(checksTone(it.state), it.stateLabel) }
        }
        val checks = vm.host.value?.checks
        val toChecks: (String) -> Unit = { sha -> shell.navigate(Route.ProjectCode(project, CodePages.CHECKS, sha)) }
        when {
            checks != null && checks.runs.isNotEmpty() -> {
                // leurs noms viennent de l'hôte : posés tels quels
                OutsideMark()
                RunsList(checks.runs)
                MoreLink(stringResource(R.string.proj_code_checks_detail)) { toChecks(checks.sha) }
            }
            checks != null && checks.error.isNotBlank() -> Hint(checks.error, R.drawable.ic_m_alert)
            p.checks != null && p.checks.sha.isNotBlank() -> MoreLink(stringResource(R.string.proj_code_checks_last)) { toChecks(p.checks.sha) }
            else -> Muted(stringResource(R.string.proj_code_checks_never))
        }

        SideTitle(stringResource(R.string.proj_code_side_conflicts))
        StateLine(R.drawable.ic_m_merge, if (p.conflicts) StateTone.FAIL else StateTone.DONE, stringResource(if (p.conflicts) R.string.proj_code_conflicts_yes else R.string.proj_code_conflicts_no)) {
            Text(conflictsWords(p), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }

        SideTitle(stringResource(R.string.proj_code_side_branch))
        LinkedLine(R.drawable.ic_m_branch, StateTone.WORK, p.branch, pullBranchWords(d)) { shell.navigate(Route.ProjectCode(project, CodePages.BRANCH, p.branch)) }

        SideTitle(stringResource(R.string.proj_side_linked))
        if (p.ticket == null && p.objective == null) Muted(stringResource(R.string.proj_linked_none))
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            TicketLinked(project, p.ticket)
            ObjectiveLinked(project, p.objective)
        }
    }
}

/** Un état en une ligne : sa tuile à sa couleur, ses mots, et ce qu'on en dit dessous. */
@Composable
private fun StateLine(icon: Int, tone: StateTone, label: String, more: @Composable () -> Unit = {}) {
    Row(verticalAlignment = Alignment.Top) {
        Tile(icon, tone, 32.dp)
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(label, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
            more()
        }
    }
}

/** Un lien vers une page de l'écran : ses mots, et un chevron. */
@Composable
private fun MoreLink(text: String, onClick: () -> Unit) {
    OutlinedButton(onClick = onClick, modifier = Modifier.padding(top = 6.dp)) {
        Text(text)
        Spacer(Modifier.width(6.dp))
        MIcon(R.drawable.ic_m_chev_right, null, size = 16.dp)
    }
}

/**
 * « Modifier » une pull request, en feuille : son titre et son texte chez l'hôte, relus avant de s'ouvrir à la
 * modification ; seul ce qui change part. L'hôte muet, on le dit, et son titre connu du moteur sert de départ.
 */
@Composable
private fun PullEditSheet(vm: PullViewModel, p: CodePull, remote: Boolean, onDismiss: () -> Unit) {
    val host = vm.host.load
    val read = !remote || host is Load.Ready || host is Load.Failed
    var title by remember(read) { mutableStateOf(vm.editable().first) }
    var body by remember(read) { mutableStateOf(vm.editable().second) }
    val where = PullViewModel.EDIT
    val errors = vm.gestures.fieldsAt(where)
    LaunchedEffect(Unit) { vm.gestures.forget(where) }
    LaunchedEffect(vm.gestures.finished) {
        if (vm.gestures.finished == where) {
            vm.gestures.acknowledge()
            onDismiss()
        }
    }
    FormSheet(
        title = stringResource(R.string.proj_code_pull_edit, p.number),
        sub = stringResource(R.string.proj_code_pull_edit_sub),
        submit = stringResource(R.string.proj_save),
        busy = vm.gestures.busy == where,
        error = vm.gestures.refusalAt(where),
        onDismiss = onDismiss,
        onSubmit = { vm.edit(title, body) },
        enabled = read && title.isNotBlank(),
    ) {
        if (!read) {
            Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        } else {
            if (host is Load.Failed || (host as? Load.Ready)?.value?.error?.isNotBlank() == true) {
                Hint(stringResource(R.string.proj_code_pull_edit_host_down), R.drawable.ic_m_alert)
            }
            FormText(stringResource(R.string.proj_code_field_title), title, { title = it }, error = errors["title"])
            FormLong(stringResource(R.string.proj_code_field_body), body, { body = it }, rows = 8, help = stringResource(R.string.proj_code_field_body_help), error = errors["body"])
        }
    }
}

// ── Une issue ───────────────────────────────────────────────────────────

/** Un verdict sur le ticket d'une issue, qui demande un mot avant de partir. */
private data class IssueAsk(val verdict: String, val title: String, val ask: AskFor)

@Composable
internal fun IssueScreen(graph: AppGraph, route: Route.ProjectCode) {
    val frame = rememberCodeFrame(graph, route.id)
    val session = rememberSessionKey(graph)
    val number = route.key.toIntOrNull() ?: 0
    val vm: IssueViewModel = viewModel(key = "code-issue|$session|${route.id}|$number") { IssueViewModel(ProjectsDeps(graph), route.id, number) }
    Toasts(vm.gestures)
    // ce qui attend son accord ne se demande que pour qui peut le donner (`rights.approve`)
    val approve = frame.project.sheet.valueOrNull?.rights?.approve == true
    OnResume(vm to approve) { vm.resume(approve) }
    LaunchedEffect(vm.revision) {
        if (vm.revision > 0) {
            frame.code.reload()
            frame.project.reload()
        }
    }
    var pane by rememberSaveable { mutableStateOf(PANE_MAIN) }
    var asking by remember { mutableStateOf<IssueAsk?>(null) }
    CodePage(
        home = CodeTabs.ISSUES,
        projectTitle = frame.project.sheet.valueOrNull?.project?.title,
        load = vm.issue.load,
        onRetry = vm.issue::retry,
        panes = { x ->
            listOf(
                Pane(PANE_MAIN, stringResource(R.string.proj_pane_description)),
                Pane(PANE_TALK, stringResource(R.string.proj_code_pane_talk), if (x.veiled.isNotEmpty()) "" else maxOf(x.talk.size, x.comments).takeIf { it > 0 }?.toString().orEmpty()),
                Pane(PANE_INFOS, stringResource(R.string.proj_pane_infos)),
            )
        },
        pane = pane,
        onPane = { pane = it },
        head = { x -> IssueHead(x, frame.now) },
    ) { x ->
        when {
            pane == PANE_INFOS -> paneBlock("infos") {
                IssueInfos(x, vm, frame, route.id, vm.gestures.busy.isNotEmpty()) { verdict, title, ask -> if (ask == AskFor.NOTHING) vm.settle(verdict) else asking = IssueAsk(verdict, title, ask) }
            }
            x.veiled.isNotEmpty() -> item(key = "veiled") { EmptyNote(R.drawable.ic_m_lock, stringResource(R.string.proj_code_issue_veiled), x.veiledLabel) }
            pane == PANE_TALK -> paneBlock("talk") {
                Banner(StateTone.FAIL, R.drawable.ic_m_alert, x.error)
                for (r in x.talk) RemarkView(r, frame.now)
                if (x.talk.isEmpty()) Muted(stringResource(R.string.proj_code_issue_no_talk))
                Hint(stringResource(R.string.proj_code_talk_quoted), R.drawable.ic_m_shield_check)
            }
            else -> paneBlock("body") {
                Banner(StateTone.FAIL, R.drawable.ic_m_alert, x.error)
                // le texte d'une issue est celui de quelqu'un chez l'hôte : cité, jamais lu comme une mise en forme
                val body = hostText(x.body)
                if (body.isBlank()) Muted(stringResource(R.string.proj_code_issue_no_text)) else OutsideBlock(issueSource(x), body)
            }
        }
    }
    asking?.let { a ->
        AskDialog(
            title = a.title,
            lede = vm.issue.value?.ticket?.title.orEmpty(),
            label = askLabel(a.ask),
            placeholder = "",
            confirm = a.title,
            required = a.ask.required,
            max = 2000,
            danger = true,
            onDismiss = { asking = null },
            onConfirm = { reason ->
                asking = null
                vm.settle(a.verdict, reason)
            },
        )
    }
}

/** L'en-tête d'une issue : son titre est celui de l'hôte, posé tel quel ; venue d'ailleurs, elle le dit. */
@Composable
private fun IssueHead(x: Issue, now: Long) {
    val tone = issueTone(x.state)
    val who = hostText(x.account)
    val actions: (@Composable RowScope.() -> Unit)? = if (x.url.isBlank()) null else ({ HostButton(x.url, Modifier.weight(1f)) })
    CodeHead(
        icon = R.drawable.ic_m_issue,
        tone = tone,
        over = stringResource(R.string.proj_issue_n, x.number),
        title = issueTitle(x),
        meta = {
            StatePill(tone, x.stateLabel)
            if (who.isNotBlank()) MetaText(stringResource(R.string.proj_code_issue_by, who))
            MetaText(moment(x.at, now))
            if (!x.fromHere) OutsideMark()
        },
        actions = actions,
    )
}

/**
 * « Infos » d'une issue : son état chez l'hôte, le ticket lié et son étape — l'accepter ou l'écarter quand son registre
 * le dit (`can`) —, la pull request liée avec son statut, et ce qui attend son accord à son sujet.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun IssueInfos(x: Issue, vm: IssueViewModel, frame: CodeFrame, project: Int, busy: Boolean, onSettle: (verdict: String, title: String, ask: AskFor) -> Unit) {
    val shell = frame.shell
    val tone = issueTone(x.state)
    val who = hostText(x.account)
    Column {
        SideTitle(stringResource(R.string.proj_code_side_host))
        Fact(stringResource(R.string.proj_fact_state)) { StatePill(tone, x.stateLabel) }
        if (who.isNotBlank()) {
            Fact(stringResource(R.string.proj_code_fact_opened_by)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(who, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f, fill = false))
                    if (!x.fromHere) {
                        Spacer(Modifier.width(8.dp))
                        OutsideMark()
                    }
                }
            }
        }
        Fact(stringResource(R.string.proj_code_fact_touched), moment(x.at, frame.now))
        Fact(stringResource(R.string.proj_code_fact_comments), x.comments.toString())
        Fact(stringResource(R.string.proj_code_fact_labels)) {
            if (x.labels.isEmpty()) {
                Muted(stringResource(R.string.proj_code_labels_none))
            } else {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) { for (l in x.labels) KindChip(hostText(l)) }
            }
        }

        val t = x.ticket
        SideTitle(stringResource(if (t != null && t.status == "proposed") R.string.proj_code_side_ticket_proposed else R.string.proj_code_side_ticket))
        if (t == null) {
            Muted(stringResource(R.string.proj_code_ticket_none))
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                RefusalNote(vm.gestures.refusalAt(IssueViewModel.TICKET))
                TicketLinked(project, t)
                if (t.handLabel.isNotBlank()) Muted(stringResource(R.string.proj_code_ticket_hand, t.handLabel))
                // le ticket proposé se tranche ici quand son registre le dit (`can`) : les gestes du ticket lui-même
                val can = vm.entry?.more?.can
                if (can?.accept == true) {
                    val accept = stringResource(R.string.proj_do_accept_ticket)
                    val dismiss = stringResource(R.string.proj_do_dismiss)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = { onSettle("accept", accept, AskFor.NOTHING) }, enabled = !busy) { Text(accept) }
                        if (can.dismiss) {
                            OutlinedButton(
                                onClick = { onSettle("dismiss", dismiss, if (can.dismissNeedsReason) AskFor.WHY else AskFor.WHY_OPTIONAL) },
                                enabled = !busy,
                                colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
                            ) { Text(dismiss) }
                        }
                    }
                    Hint(stringResource(R.string.proj_code_ticket_untouched))
                } else if (t.yours) {
                    OutlinedButton(onClick = { shell.navigate(Route.ProjectTicket(project, t.number)) }) {
                        MIcon(R.drawable.ic_m_ticket, null, size = 18.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.proj_code_ticket_settle))
                    }
                }
            }
        }

        val linked = vm.entry?.more?.linked
        linked?.pull?.let { pull ->
            SideTitle(stringResource(R.string.proj_code_side_issue_pull))
            PullCard(pull, linked.checks, null, frame.now) { shell.navigate(pullPage(project, pull.number, linked.objective?.id ?: 0)) }
        }

        // ce qu'elle voudrait publier sur cette issue et qui attend son accord : il se lit et se décide dans « À faire »
        val waiting = vm.waiting
        if (waiting.isNotEmpty()) {
            SideTitle(stringResource(R.string.proj_code_side_accord))
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                for (a in waiting) {
                    Text(stringResource(R.string.proj_code_accord_waits, listOf(a.label, a.summary).filter { it.isNotBlank() }.joinToString(" — ")), style = MaterialTheme.typography.bodyMedium)
                    Button(onClick = { shell.navigate(Route.ProjectTodo(project, "accord-${a.id}")) }) {
                        MIcon(R.drawable.ic_m_shield_check, null, size = 18.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.proj_code_accord_read))
                    }
                }
            }
        }
    }
}

// ── Les vérifications d'un commit ───────────────────────────────────────

@Composable
internal fun ChecksScreen(graph: AppGraph, route: Route.ProjectCode) {
    val frame = rememberCodeFrame(graph, route.id)
    val session = rememberSessionKey(graph)
    val vm: ChecksViewModel = viewModel(key = "code-ci|$session|${route.id}|${route.key}") { ChecksViewModel(ProjectsDeps(graph), route.id, route.key) }
    Toasts(vm.gestures)
    // ce que l'hôte en dit maintenant ne se demande que s'il y a un dépôt distant à relire
    val remote = frame.code.summary.value?.remote?.has == true
    OnResume(vm to remote) { vm.resume(remote) }
    var pane by rememberSaveable { mutableStateOf(PANE_MAIN) }
    val tracked = vm.tracked
    val live = vm.live.value
    val tail = checksTail(tracked, live)
    val logName = hostText(live?.log?.name)
    CodePage<ChecksList>(
        home = CodeTabs.CI,
        projectTitle = frame.project.sheet.valueOrNull?.project?.title,
        load = vm.list.load,
        onRetry = vm.list::retry,
        panes = {
            listOfNotNull(
                Pane(PANE_MAIN, stringResource(R.string.proj_code_side_checks), runsPassed(live?.runs.orEmpty())),
                if (tail.isNotBlank()) Pane(PANE_LOG, stringResource(R.string.proj_code_ci_log)) else null,
                Pane(PANE_INFOS, stringResource(R.string.proj_pane_infos)),
            )
        },
        pane = pane,
        onPane = { pane = it },
        head = { ChecksHead(tracked, live, route.key, frame.now) },
    ) {
        when {
            pane == PANE_INFOS -> paneBlock("infos") { ChecksInfos(tracked, live, route.key, frame, route.id) }
            // la fin d'un journal vient de l'hôte : citée, en chasse fixe, jamais lue comme une mise en forme
            pane == PANE_LOG && tail.isNotBlank() -> paneBlock("log") {
                OutsideBlock(if (logName.isBlank()) stringResource(R.string.proj_code_ci_log_from) else stringResource(R.string.proj_code_ci_log_from_named, logName), tail, mono = true)
            }
            else -> paneBlock("runs") {
                if (remote) {
                    when (val load: Load<HostChecks>? = vm.live.load) {
                        null, Load.Loading -> Hint(stringResource(R.string.proj_code_ci_reading), R.drawable.ic_m_clock)
                        is Load.Failed -> {
                            RefusalNote(load.error.message)
                            OutlinedButton(onClick = vm.live::retry) { Text(stringResource(R.string.retry)) }
                        }
                        is Load.Ready -> Banner(StateTone.FAIL, R.drawable.ic_m_alert, load.value.error)
                    }
                }
                val runs = live?.runs.orEmpty()
                if (runs.isNotEmpty()) {
                    // leurs noms viennent de l'hôte : posés tels quels
                    OutsideMark()
                    RunsList(runs, big = true)
                } else if (live != null && live.error.isBlank()) {
                    Muted(stringResource(R.string.proj_code_ci_no_run))
                }
                if (tail.isNotBlank()) {
                    LinkedLine(
                        R.drawable.ic_m_terminal, StateTone.FAIL,
                        if (logName.isBlank()) stringResource(R.string.proj_code_ci_log) else stringResource(R.string.proj_code_ci_log_of, logName),
                        stringResource(R.string.proj_code_ci_log_sub),
                    ) { pane = PANE_LOG }
                }
            }
        }
    }
}

/** L'en-tête des vérifications d'un commit : le commit, leur état — ce que l'hôte en dit maintenant, sinon ce que le moteur suit —, quand. */
@Composable
private fun ChecksHead(tracked: TrackedChecks?, live: HostChecks?, sha: String, now: Long) {
    val commit = live?.commit ?: tracked?.commit
    val shown = checksShown(tracked, live)
    val tone = checksTone(shown.state)
    val url = commit?.url.orEmpty()
    val actions: (@Composable RowScope.() -> Unit)? = if (url.isBlank()) null else ({ HostButton(url, Modifier.weight(1f)) })
    CodeHead(
        icon = R.drawable.ic_m_bolt,
        tone = tone,
        over = stringResource(R.string.proj_code_side_checks),
        title = commit?.title?.takeIf { it.isNotBlank() } ?: stringResource(R.string.proj_code_ci_commit, sha.take(7)),
        meta = {
            StatePill(tone, shown.label)
            MetaText(moment(shown.at, now))
            if (live != null && live.readAt > 0) MetaText(stringResource(R.string.proj_code_ci_read_at, since(live.readAt, now)))
            if (commit?.outside == true) OutsideMark()
        },
        actions = actions,
    )
}

/** « Infos » des vérifications : le commit vérifié, sa pull request, pour quoi, et en bref. */
@Composable
private fun ChecksInfos(tracked: TrackedChecks?, live: HostChecks?, sha: String, frame: CodeFrame, project: Int) {
    val commit = live?.commit ?: tracked?.commit
    val shown = checksShown(tracked, live)
    val linked = checksLinked(tracked, live)
    Column {
        SideTitle(stringResource(R.string.proj_code_side_checked))
        if (commit == null) {
            Code((live?.sha ?: tracked?.sha ?: sha).take(12))
        } else {
            CommitLine(commit, frame.now) { frame.shell.navigate(Route.ProjectCode(project, CodePages.COMMIT, commit.sha)) }
            if (commit.branch.isNotBlank()) BranchChip(commit.branch)
        }
        if (linked?.pull != null) {
            SideTitle(stringResource(R.string.proj_code_side_issue_pull))
            PullLinked(project, linked.pull, linked.objective)
        }
        if (linked?.objective != null || linked?.ticket != null) {
            SideTitle(stringResource(R.string.proj_code_side_for))
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                ObjectiveLinked(project, linked.objective)
                TicketLinked(project, linked.ticket)
            }
        }
        SideTitle(stringResource(R.string.proj_side_brief))
        if (shown.label.isNotBlank()) Fact(stringResource(R.string.proj_fact_state)) { StatePill(checksTone(shown.state), shown.label) }
        Fact(stringResource(R.string.proj_code_fact_on), moment(shown.at, frame.now))
        if (live != null) Fact(stringResource(R.string.proj_code_fact_read_at), moment(live.readAt, frame.now))
    }
}
