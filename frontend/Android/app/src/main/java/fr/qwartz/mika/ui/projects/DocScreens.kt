package fr.qwartz.mika.ui.projects

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.projects.Decision
import fr.qwartz.mika.data.moi.projects.DocPage
import fr.qwartz.mika.data.moi.projects.DocVersion
import fr.qwartz.mika.data.moi.projects.SheetTabs
import fr.qwartz.mika.data.moi.projects.StateTone
import fr.qwartz.mika.data.moi.projects.decisionTone
import fr.qwartz.mika.data.moi.projects.docBlocks
import fr.qwartz.mika.data.moi.projects.folderOf
import fr.qwartz.mika.data.moi.projects.folderPath
import fr.qwartz.mika.data.moi.projects.headingsOf
import fr.qwartz.mika.data.moi.projects.moment
import fr.qwartz.mika.data.moi.projects.nameOf
import fr.qwartz.mika.data.moi.projects.optionLines
import fr.qwartz.mika.data.moi.projects.pagePath
import fr.qwartz.mika.data.moi.projects.since
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.BarMenu
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MenuEntry
import fr.qwartz.mika.ui.shell.rememberSessionKey

/*
 * Une page de documentation et une décision technique, en page (ADR 0296). La page : son chemin, « Modifier » selon le
 * droit servi (`can.write`), ses volets — **Page** (son Markdown rendu, ses images de l'espace) et **Infos** (son
 * sommaire, sa dernière modification, ses versions) ; une version gardée se relit à sa place, et l'on y revient (une
 * version de plus, rien n'est perdu) si le serveur le permet ; la renommer, la déplacer, la supprimer. La décision : le
 * choix, le contexte, la raison, les options écartées, ce qu'elle remplace — telle que le serveur la sert.
 */

private const val PANE_PAGE = "page"
private const val PANE_INFOS = "infos"

@Composable
internal fun DocPageScreen(graph: AppGraph, route: Route.ProjectPage) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val project = rememberProjectModel(graph, route.id)
    val docs = rememberDocsModel(graph, route.id)
    val vm: DocPageViewModel = viewModel(key = "doc-page|$session|${route.id}|${route.key}") { DocPageViewModel(ProjectsDeps(graph), route.id, route.key) }
    val now = rememberNow(wallMs = graph.clock::wallMs)
    Toasts(vm.gestures)
    OnResume(vm) {
        project.resume()
        docs.space.open()
        vm.resume()
    }
    LaunchedEffect(vm.revision) { if (vm.revision > 0) docs.reload() }
    // la page a changé de chemin : l'écran la suit ; supprimée : il revient à l'arborescence
    LaunchedEffect(vm.moved, vm.removed) {
        val to = vm.moved
        when {
            vm.removed -> {
                vm.gone()
                shell.back()
            }
            to.isNotEmpty() -> {
                vm.gone()
                shell.replace(Route.ProjectPage(route.id, SheetPages.PAGE, to))
            }
        }
    }
    var pane by rememberSaveable { mutableStateOf(PANE_PAGE) }
    var moving by rememberSaveable { mutableStateOf(false) }
    var removing by rememberSaveable { mutableStateOf(false) }
    var restoring by rememberSaveable { mutableIntStateOf(0) }
    LaunchedEffect(pane) { if (pane == PANE_INFOS) vm.openHistory() }
    val shownVersion = vm.version
    BackHandler(enabled = shownVersion != null) { vm.showVersion(0) }
    val images = docs.space.value?.images?.associateBy { it.name }
    val page = vm.page.value
    val seen = (shownVersion as? Load.Ready)?.value
    val blocks = remember(page?.text, seen?.text, shownVersion == null) { docBlocks(if (shownVersion == null) page?.text.orEmpty() else seen?.text.orEmpty()) }
    val busy = vm.gestures.busy.isNotEmpty()
    DetailPage(
        title = tabLabel(SheetTabs.DOCS),
        projectTitle = project.sheet.valueOrNull?.project?.title,
        load = vm.page.load,
        onRetry = vm.page::retry,
        panes = { p ->
            listOf(
                Pane(PANE_PAGE, if (seen != null) stringResource(R.string.proj_doc_version_n, seen.n) else stringResource(R.string.proj_doc_pane_page)),
                Pane(PANE_INFOS, stringResource(R.string.proj_pane_infos), p.version.takeIf { it > 1 }?.toString().orEmpty()),
            )
        },
        pane = pane,
        onPane = { pane = it },
        head = { p ->
            PageHead(p, shownVersion != null, onEdit = { shell.navigate(Route.ProjectPage(route.id, SheetPages.EDIT, p.path)) }, onBack = { vm.showVersion(0) })
        },
        notice = { RefusalNote(vm.gestures.refusalAt(DocPageViewModel.HERE), Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) },
        actions = {
            if (page?.can?.write == true) {
                BarMenu(
                    listOf(
                        MenuEntry(stringResource(R.string.proj_doc_move), R.drawable.ic_m_folder) { moving = true },
                        MenuEntry(stringResource(R.string.proj_doc_delete), R.drawable.ic_m_trash) { removing = true },
                    ),
                )
            }
        },
    ) { p ->
        when {
            pane == PANE_INFOS -> paneBlock("infos") { PageInfos(p, vm, now) { n -> if (n == p.version) vm.showVersion(0) else vm.showVersion(n); pane = PANE_PAGE } }
            shownVersion != null -> when (shownVersion) {
                Load.Loading -> paneBlock("version-wait") { Muted(stringResource(R.string.proj_doc_version_reading)) }
                is Load.Failed -> paneBlock("version-no") { RefusalNote(shownVersion.error.message) }
                is Load.Ready -> {
                    val v = shownVersion.value
                    paneBlock("version") { VersionCard(v, p, now, busy) { restoring = v.n } }
                    if (v.forgotten) paneBlock("forgotten") { Hint(stringResource(R.string.proj_doc_forgotten), R.drawable.ic_m_lock) } else docBody(graph, route.id, blocks, images)
                }
            }
            p.forgotten -> paneBlock("forgotten") { Hint(stringResource(R.string.proj_doc_forgotten), R.drawable.ic_m_lock) }
            p.text.isBlank() -> item(key = "empty") { EmptyNote(R.drawable.ic_m_file, stringResource(R.string.proj_doc_empty), stringResource(R.string.proj_doc_empty_sub)) }
            else -> docBody(graph, route.id, blocks, images)
        }
    }
    if (moving && page != null) MoveSheet(page, vm) { moving = false }
    if (removing && page != null) {
        ConfirmDialog(
            stringResource(R.string.proj_doc_delete_title),
            stringResource(R.string.proj_doc_delete_text, page.path),
            stringResource(R.string.proj_doc_delete),
            onDismiss = { removing = false },
            onConfirm = vm::remove,
        )
    }
    if (restoring > 0) {
        ConfirmDialog(
            stringResource(R.string.proj_doc_restore_title, restoring),
            stringResource(R.string.proj_doc_restore_text),
            stringResource(R.string.proj_doc_restore),
            onDismiss = { restoring = 0 },
        ) { vm.restore(restoring) }
    }
}

/** L'en-tête d'une page : son dossier et son nom, puis « Modifier » — seulement si le serveur dit qu'elle peut l'écrire. */
@Composable
private fun PageHead(p: DocPage, version: Boolean, onEdit: () -> Unit, onBack: () -> Unit) {
    Column(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (p.folder.isNotEmpty()) {
                Text("${p.folder} / ", style = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Text(p.name.ifEmpty { nameOf(p.path) }, style = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace), fontWeight = FontWeight.Bold)
        }
        Gap(8.dp)
        when {
            version -> OutlinedButton(onClick = onBack) {
                MIcon(R.drawable.ic_m_chev_left, null, size = 18.dp)
                Spacer(Modifier.width(6.dp))
                Text(stringResource(R.string.proj_doc_version_back))
            }
            p.can.write -> Button(onClick = onEdit) {
                MIcon(R.drawable.ic_m_pen, null, size = 18.dp)
                Spacer(Modifier.width(6.dp))
                Text(stringResource(R.string.proj_edit))
            }
        }
    }
}

/** Une version gardée, relue : qui l'a écrite, quand, son mot ; et y revenir, si elle peut écrire la page. */
@Composable
private fun VersionCard(v: DocVersion, p: DocPage, now: Long, busy: Boolean, onRestore: () -> Unit) {
    Banner(
        if (v.current) StateTone.DONE else StateTone.WAIT,
        R.drawable.ic_m_history,
        listOf(
            stringResource(R.string.proj_doc_version_n, v.n),
            listOf(v.author, v.viaLabel).filter { it.isNotBlank() }.joinToString(", "),
            moment(v.at, now),
        ).filter { it.isNotBlank() }.joinToString(" · ") + if (v.word.isBlank()) "" else " — « ${v.word} »",
    )
    when {
        v.current -> Muted(stringResource(R.string.proj_doc_version_current))
        p.can.write && !v.forgotten -> OutlinedButton(onClick = onRestore, enabled = !busy) {
            MIcon(R.drawable.ic_m_history, null, size = 18.dp)
            Spacer(Modifier.width(6.dp))
            Text(stringResource(R.string.proj_doc_restore))
        }
    }
}

/** « Infos » d'une page : son sommaire, sa dernière modification, ses versions gardées (toucher l'une la relit). */
@Composable
private fun PageInfos(p: DocPage, vm: DocPageViewModel, now: Long, onVersion: (Int) -> Unit) {
    val titles = remember(p.text) { headingsOf(p.text) }
    if (titles.isNotEmpty()) {
        SideTitle(stringResource(R.string.proj_doc_side_outline))
        for ((level, text) in titles) {
            Text(text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(start = (12 * (level - 1)).coerceAtLeast(0).dp, top = 2.dp, bottom = 2.dp))
        }
    }
    SideTitle(stringResource(R.string.proj_doc_side_last))
    Text(p.author, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold)
    Text(listOf(p.viaLabel, moment(p.at, now)).filter { it.isNotBlank() }.joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    Fact(stringResource(R.string.proj_doc_fact_path), p.path)
    Fact(stringResource(R.string.proj_doc_fact_created), moment(p.createdAt, now))
    SideTitle(stringResource(R.string.proj_doc_side_versions))
    when (val load = vm.history.load) {
        null, Load.Loading -> Muted(stringResource(R.string.proj_doc_version_reading))
        is Load.Failed -> RefusalNote(load.error.message)
        is Load.Ready -> {
            for (v in load.value.versions) {
                Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).clickable { onVersion(v.n) }.padding(vertical = 8.dp)) {
                    Text(
                        stringResource(R.string.proj_doc_version_n, v.n) + if (v.current) " · " + stringResource(R.string.proj_doc_version_is_current) else "",
                        style = MaterialTheme.typography.bodyLarge,
                        fontWeight = FontWeight.SemiBold,
                    )
                    if (v.word.isNotBlank()) Text("« ${v.word} »", style = MaterialTheme.typography.bodyMedium)
                    Text(listOf(v.author, since(v.at, now)).filter { it.isNotBlank() }.joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            if (load.value.kept > 0) Hint(stringResource(R.string.proj_doc_versions_kept, load.value.kept.toString()))
        }
    }
}

/** Renommer ou déplacer une page : son nom et son dossier ; ses versions la suivent, les liens des autres pages ne sont pas réécrits. */
@Composable
private fun MoveSheet(p: DocPage, vm: DocPageViewModel, onDismiss: () -> Unit) {
    var name by rememberSaveable { mutableStateOf(nameOf(p.path).removeSuffix(".md")) }
    var folder by rememberSaveable { mutableStateOf(folderOf(p.path)) }
    val where = DocPageViewModel.MOVE
    val to = pagePath(folderPath(folder), name)
    LaunchedEffect(Unit) { vm.gestures.forget(where) }
    FormSheet(
        title = stringResource(R.string.proj_doc_move),
        sub = p.path,
        submit = stringResource(R.string.proj_doc_move_ok),
        busy = vm.gestures.busy == where,
        error = vm.gestures.refusalAt(where),
        onDismiss = onDismiss,
        onSubmit = { vm.move(to) },
        enabled = to.isNotEmpty() && to != p.path,
    ) {
        FormText(stringResource(R.string.proj_doc_move_name), name, { name = it }, error = vm.gestures.fieldsAt(where)["to"])
        FormText(stringResource(R.string.proj_doc_move_folder), folder, { folder = it }, help = stringResource(R.string.proj_doc_move_folder_help))
        if (to.isNotEmpty()) Hint(stringResource(R.string.proj_doc_new_path, to), R.drawable.ic_m_file)
        Hint(stringResource(R.string.proj_doc_move_note))
    }
}

// ── Une décision technique ──────────────────────────────────────────────

private const val PANE_DECISION = "decision"
private const val PANE_OPTIONS = "options"

@Composable
internal fun DecisionScreen(graph: AppGraph, route: Route.ProjectPage) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val project = rememberProjectModel(graph, route.id)
    val number = route.key.toIntOrNull() ?: 0
    val vm: CodeReadViewModel<Decision> = viewModel(key = "decision|$session|${route.id}|$number") {
        CodeReadViewModel(ProjectsDeps(graph)) { it.decision(route.id, number) }
    }
    val now = rememberNow(wallMs = graph.clock::wallMs)
    Toasts(vm.gestures)
    OnResume(vm) {
        project.resume()
        vm.resume()
    }
    var pane by rememberSaveable { mutableStateOf(PANE_DECISION) }
    DetailPage(
        title = stringResource(R.string.proj_doc_tab_decisions),
        projectTitle = project.sheet.valueOrNull?.project?.title,
        load = vm.read.load,
        onRetry = vm.read::retry,
        panes = { d ->
            listOf(
                Pane(PANE_DECISION, stringResource(R.string.proj_doc_pane_decision)),
                Pane(PANE_OPTIONS, stringResource(R.string.proj_doc_pane_options), optionLines(d.options).size.takeIf { it > 0 }?.toString().orEmpty()),
                Pane(PANE_INFOS, stringResource(R.string.proj_pane_infos)),
            )
        },
        pane = pane,
        onPane = { pane = it },
        head = { d ->
            CodeHead(R.drawable.ic_m_shield_check, decisionTone(d.status), stringResource(R.string.proj_doc_decision_n, d.number), d.title, meta = {
                StatePill(decisionTone(d.status), d.statusLabel)
                MetaText(d.author)
                MetaText(since(d.at, now))
            })
        },
    ) { d ->
        val open: (Int) -> Unit = { shell.navigate(Route.ProjectPage(route.id, SheetPages.DECISION, it.toString())) }
        when (pane) {
            PANE_OPTIONS -> paneBlock("options") {
                val options = optionLines(d.options)
                if (options.isEmpty()) Muted(stringResource(R.string.proj_doc_options_none))
                for ((title, why) in options) {
                    Row(verticalAlignment = Alignment.Top) {
                        MIcon(R.drawable.ic_m_x, null, size = 16.dp, tint = MaterialTheme.colorScheme.error, modifier = Modifier.padding(top = 3.dp))
                        Spacer(Modifier.width(10.dp))
                        Column {
                            Text(title, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold)
                            if (why.isNotBlank()) Text(why, style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                }
            }
            PANE_INFOS -> paneBlock("infos") {
                Fact(stringResource(R.string.proj_fact_state)) { StatePill(decisionTone(d.status), d.statusLabel) }
                Fact(stringResource(R.string.proj_doc_fact_author), d.author)
                Fact(stringResource(R.string.proj_fact_when), moment(d.at, now))
                if (d.replaces > 0) LinkedLine(R.drawable.ic_m_shield_check, StateTone.WAIT, stringResource(R.string.proj_doc_decision_n, d.replaces), stringResource(R.string.proj_doc_replaces), onClick = { open(d.replaces) })
                if (d.replacedBy > 0) LinkedLine(R.drawable.ic_m_shield_check, StateTone.DONE, stringResource(R.string.proj_doc_decision_n, d.replacedBy), stringResource(R.string.proj_doc_replaced_by), onClick = { open(d.replacedBy) })
                if (d.objective > 0) {
                    LinkedLine(R.drawable.ic_m_target, StateTone.WORK, stringResource(R.string.proj_goal_n, d.objective), stringResource(R.string.proj_goal_concerned), onClick = { shell.navigate(Route.ProjectGoal(route.id, "o${d.objective}")) })
                }
            }
            else -> paneBlock("decision") {
                SideTitle(stringResource(R.string.proj_doc_choice))
                if (d.choice.isBlank()) Muted(stringResource(R.string.proj_doc_text_none)) else MdText(d.choice)
                if (d.context.isNotBlank()) {
                    SideTitle(stringResource(R.string.proj_doc_context))
                    MdText(d.context)
                }
                if (d.reason.isNotBlank()) {
                    SideTitle(stringResource(R.string.proj_doc_reason))
                    MdText(d.reason)
                }
            }
        }
    }
}
