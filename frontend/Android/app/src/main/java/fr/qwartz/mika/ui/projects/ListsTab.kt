package fr.qwartz.mika.ui.projects

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.FilledTonalIconButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.projects.Coded
import fr.qwartz.mika.data.moi.projects.Entry
import fr.qwartz.mika.data.moi.projects.EntryDetail
import fr.qwartz.mika.data.moi.projects.Listing
import fr.qwartz.mika.data.moi.projects.Sheet
import fr.qwartz.mika.data.moi.projects.SheetTabs
import fr.qwartz.mika.data.moi.projects.StateTone
import fr.qwartz.mika.data.moi.projects.addActor
import fr.qwartz.mika.data.moi.projects.followLists
import fr.qwartz.mika.data.moi.projects.keyed
import fr.qwartz.mika.data.moi.projects.listGroups
import fr.qwartz.mika.data.moi.projects.listStatusTone
import fr.qwartz.mika.data.moi.projects.moment
import fr.qwartz.mika.data.moi.projects.plural
import fr.qwartz.mika.data.moi.projects.since
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.rememberSessionKey

/*
 * L'onglet Listes d'une fiche (ADR 0296) — il n'existe que pour un projet qui a une liste de suivi. Sur téléphone : une
 * pastille par liste, puis ses éléments rangés par statut, chacun en carte ; **son statut se touche** pour le changer
 * (`rights.status`), à qui il est aussi (`can.assign`) ; « Ajouter » selon `can.add`. Un élément s'ouvre en page : ce
 * qu'il faut en savoir, **son fil** — ses notes et ce qui lui est arrivé : c'est son historique, tel que le serveur le
 * sert —, de quoi y écrire, son statut, à qui il est. Les statuts et leurs mots sont ceux de la liste.
 */

private const val PANE_THREAD = "fil"
private const val PANE_INFOS = "infos"

@Composable
internal fun ListsTab(graph: AppGraph, vm: ProjectViewModel, sheet: Sheet, now: Long, sub: String) {
    val shell = LocalShell.current
    val lists = followLists(sheet)
    val list = lists.firstOrNull { it.name == sub } ?: lists.firstOrNull()
    val model = rememberListsModel(graph, vm.id)
    Toasts(model.gestures)
    OnResume(model) { model.resume() }
    // quitté avant la réponse d'un ajout, l'onglet n'ouvre rien à son retour
    OnLeave(model) { model.leave() }
    LaunchedEffect(model, list?.name) { list?.let { model.show(it.name) } }
    LaunchedEffect(model.revision) { if (model.revision > 0) vm.reload() }
    LaunchedEffect(vm.refreshing) { if (vm.refreshing) model.resume() }
    // l'élément qui vient d'être ajouté s'ouvre
    LaunchedEffect(model.added) {
        model.added?.let { (l, key) ->
            model.addedSeen()
            shell.navigate(Route.ProjectPage(vm.id, SheetPages.ITEM, key, l))
        }
    }
    if (list == null) {
        StillPane { EmptyNote(R.drawable.ic_m_board, stringResource(R.string.proj_list_none), stringResource(R.string.proj_list_none_sub)) }
        return
    }
    var adding by rememberSaveable { mutableStateOf(false) }
    val where = ListsViewModel.where(list.name)
    // la liste s'ouvre : ce qu'on y avait dit avant de la quitter ne vaut plus
    FreshEntry(model.gestures, where)
    // ce qu'on montre se relit (un retour sur l'écran, un geste abouti ou refusé) : d'ici là, rien ne s'y décide
    val stale = list.name in model.stale
    Column(Modifier.fillMaxSize()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            ChipRow(
                lists.map { Chip(it.name, it.title, it.total) },
                selected = list.name,
                onPick = { if (it != list.name) shell.replace(Route.Project(vm.id, "${SheetTabs.LISTS}/$it")) },
                modifier = Modifier.weight(1f).padding(top = 4.dp),
            )
            if (list.can.add) {
                FilledTonalIconButton(onClick = { adding = true }, modifier = Modifier.padding(end = 8.dp)) { MIcon(R.drawable.ic_m_plus, stringResource(R.string.proj_add)) }
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        ListedPane(model.pages[list.name], { model.load(list.name) }) { page ->
            item(key = "head") {
                Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(stringResource(R.string.proj_list_living, list.living, list.total), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    RefusalNote(model.gestures.refusalAt(where))
                    StaleNote(model.staleErrors[list.name], { model.load(list.name) })
                    if (!list.can.add && list.can.why.isNotBlank()) Hint(list.can.why, R.drawable.ic_m_lock)
                }
            }
            // une clé par élément, unique dans toute la liste : deux éléments voilés n'ont ni clé ni nom
            val rows = keyed(page.items) { "e${it.key}:${it.handle}" }
            listGroups(list, page.items).forEachIndexed { n, g ->
                item(key = "s$n") { StatusLabel(list, g.status, g.count) }
                if (g.items.isEmpty()) {
                    item(key = "n$n") { Text(stringResource(R.string.proj_list_nothing), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) }
                }
                items(rows.filter { it.value.status == g.status.code }, key = { it.key }) { row ->
                    val e = row.value
                    ItemCard(
                        e, list, sheet.rights.status, now, model.gestures.busy.isNotEmpty() || stale,
                        onOpen = { shell.navigate(Route.ProjectPage(vm.id, SheetPages.ITEM, e.key, list.name)) },
                        onStatus = { model.setStatus(e, it) },
                        onAssign = { model.assign(e, it) },
                    )
                }
            }
            if (page.total > page.items.size) item(key = "partial") { Hint(stringResource(R.string.proj_list_partial, page.items.size.toString(), page.total.toString()), modifier = Modifier.padding(12.dp)) }
        }
    }
    if (adding) AddItemSheet(model, list) { adding = false }
}

/** Le titre d'un statut : son point à sa couleur, ses mots, son compte. */
@Composable
private fun StatusLabel(list: Listing, status: Coded, count: Int) {
    Row(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceContainerLow).padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(9.dp).background(toneOf(listStatusTone(list, status.code)).ink, CircleShape))
        Spacer(Modifier.width(8.dp))
        Text(status.label, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
        CountChip(count.toString())
    }
}

/** Un choix dans un petit menu, ouvert depuis une pastille : un statut, une personne. */
@Composable
private fun PickMenu(open: Boolean, options: List<Coded>, onDismiss: () -> Unit, onPick: (String) -> Unit) {
    DropdownMenu(expanded = open, onDismissRequest = onDismiss) {
        for (o in options) {
            DropdownMenuItem(text = { Text(o.label) }, onClick = {
                onDismiss()
                onPick(o.code)
            })
        }
    }
}

/**
 * Un élément en carte : son nom, sa clé, ses notes ; en pied à qui il est, depuis quand, et son statut — une pastille
 * qu'on touche pour le changer, quand le serveur l'ouvre. Un élément qu'elle ne peut pas lire dit pourquoi, sans nom.
 */
@Composable
private fun ItemCard(e: Entry, list: Listing, canStatus: Boolean, now: Long, busy: Boolean, onOpen: () -> Unit, onStatus: (String) -> Unit, onAssign: (String) -> Unit) {
    var statuses by remember { mutableStateOf(false) }
    var actors by remember { mutableStateOf(false) }
    val readable = e.veiled.isEmpty()
    Surface(
        shape = RoundedCornerShape(14.dp),
        border = BorderStroke(1.dp, if (e.yours) toneOf(StateTone.YOU).bar else MaterialTheme.colorScheme.outlineVariant),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 5.dp).clip(RoundedCornerShape(14.dp)).clickable(enabled = readable, onClick = onOpen),
    ) {
        Column(Modifier.padding(12.dp)) {
            Text(e.title.ifBlank { e.veiledLabel }, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
            if (e.key.isNotBlank()) Text(e.key, style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace), color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (e.notes > 0) Text(stringResource(R.string.proj_list_notes, plural(e.notes, "note", "notes")), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Gap(8.dp)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box {
                    val assign = list.can.assign && readable && list.actors.isNotEmpty()
                    Row(
                        Modifier.clip(RoundedCornerShape(8.dp)).then(if (assign) Modifier.clickable(enabled = !busy) { actors = true } else Modifier).padding(vertical = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        MIcon(R.drawable.ic_m_user, null, size = 14.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                        Spacer(Modifier.width(4.dp))
                        Text(e.actorLabel, style = MaterialTheme.typography.bodySmall, maxLines = 1)
                        if (assign) MIcon(R.drawable.ic_m_chev_down, stringResource(R.string.proj_list_assign), size = 12.dp)
                    }
                    PickMenu(actors, list.actors, { actors = false }, onAssign)
                }
                Spacer(Modifier.width(10.dp))
                Text(since(if (e.updatedAt > 0) e.updatedAt else e.at, now), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, modifier = Modifier.weight(1f))
                Box {
                    val change = canStatus && readable
                    Row(Modifier.clip(RoundedCornerShape(50)).then(if (change) Modifier.clickable(enabled = !busy) { statuses = true } else Modifier), verticalAlignment = Alignment.CenterVertically) {
                        StatePill(listStatusTone(list, e.status), e.statusLabel)
                        if (change) MIcon(R.drawable.ic_m_chev_down, stringResource(R.string.proj_list_change_status), size = 14.dp)
                    }
                    PickMenu(statuses, (list.open + list.closed).filter { it.code != e.status }, { statuses = false }, onStatus)
                }
            }
        }
    }
}

/** « Ajouter à une liste » : son nom, son statut et à qui il est (ceux que la liste sert), ce qu'il faut en savoir. */
@Composable
private fun AddItemSheet(model: ListsViewModel, list: Listing, onDismiss: () -> Unit) {
    val statuses = list.open + list.closed
    var title by rememberSaveable { mutableStateOf("") }
    var text by rememberSaveable { mutableStateOf("") }
    var status by rememberSaveable { mutableStateOf(statuses.firstOrNull()?.code.orEmpty()) }
    // à qui il est : un de ceux que la liste sert, sinon rien n'est choisi et la liste lui donne le sien
    var actor by rememberSaveable { mutableStateOf(addActor(list, list.actor)) }
    val where = ListsViewModel.ADD
    DoneCloses(model.gestures, where, onDismiss)
    val errors = model.gestures.fieldsAt(where)
    FormSheet(
        title = stringResource(R.string.proj_list_add_title, list.title),
        sub = "",
        submit = stringResource(R.string.proj_add),
        busy = model.gestures.busy == where,
        error = model.gestures.refusalAt(where),
        onDismiss = onDismiss,
        onSubmit = { model.add(list.name, title, text, status, addActor(list, actor)) },
        enabled = title.isNotBlank(),
    ) {
        FormText(stringResource(R.string.proj_list_add_name), title, { title = it }, error = errors["title"])
        FormChoice(stringResource(R.string.proj_fact_status), statuses, status, { status = it }, error = errors["status"])
        FormChoice(stringResource(R.string.proj_fact_actor), list.actors, actor, { actor = it }, error = errors["actor"])
        FormLong(stringResource(R.string.proj_list_add_text), text, { text = it }, rows = 3, error = errors["text"])
    }
}

// ── Un élément, en page ─────────────────────────────────────────────────

@Composable
internal fun ItemScreen(graph: AppGraph, route: Route.ProjectPage) {
    val session = rememberSessionKey(graph)
    val project = rememberProjectModel(graph, route.id)
    val lists = rememberListsModel(graph, route.id)
    val vm: ItemViewModel = viewModel(key = "item|$session|${route.id}|${route.ref}|${route.key}") { ItemViewModel(ProjectsDeps(graph), route.id, route.ref, route.key) }
    val now = rememberNow(wallMs = graph.clock::wallMs)
    Toasts(vm.gestures)
    // l'élément s'ouvre : ce qu'on y avait dit avant de le quitter ne vaut plus
    FreshEntry(vm.gestures, ItemViewModel.HERE)
    OnResume(vm) {
        project.resume()
        vm.resume()
    }
    LaunchedEffect(vm.revision) {
        if (vm.revision > 0) {
            lists.load(route.ref)
            project.reload()
        }
    }
    // par route : un autre élément s'ouvre sur son premier volet
    var pane by rememberSaveable(route.id, route.ref, route.key) { mutableStateOf(PANE_THREAD) }
    val list = project.sheet.valueOrNull?.lists?.firstOrNull { it.name == route.ref }
    // il se relit (un retour sur l'écran, un geste abouti ou refusé) : d'ici là, rien ne s'y décide
    val busy = vm.gestures.busy.isNotEmpty() || vm.stale
    DetailPage(
        title = list?.title ?: tabLabel(SheetTabs.LISTS),
        projectTitle = project.sheet.valueOrNull?.project?.title,
        load = vm.element,
        onRetry = vm::retry,
        panes = { x -> listOf(Pane(PANE_THREAD, stringResource(R.string.proj_pane_thread), x.more.thread.size.takeIf { it > 0 }?.toString().orEmpty()), Pane(PANE_INFOS, stringResource(R.string.proj_pane_infos))) },
        pane = pane,
        onPane = { pane = it },
        head = { x ->
            val tone = list?.let { listStatusTone(it, x.line.status) } ?: StateTone.WAIT
            CodeHead(R.drawable.ic_m_board, tone, list?.title.orEmpty(), x.line.title.ifBlank { x.line.veiledLabel }, meta = {
                StatePill(tone, x.line.statusLabel)
                MetaText(x.line.actorLabel)
                MetaText(since(if (x.line.updatedAt > 0) x.line.updatedAt else x.line.at, now))
                if (x.line.outside) OutsideMark()
            })
        },
        bottomBar = { x -> if (pane == PANE_THREAD && x.more.can.note && x.line.veiled.isEmpty()) ItemNoteBar(vm, busy) },
        notice = {
            val refusal = vm.gestures.refusalAt(ItemViewModel.HERE)
            if (refusal.isNotBlank() || vm.staleError != null) {
                Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    RefusalNote(refusal)
                    StaleNote(vm.staleError, vm::reread)
                }
            }
        },
    ) { x ->
        when {
            x.line.veiled.isNotEmpty() -> item(key = "veiled") { EmptyNote(R.drawable.ic_m_lock, stringResource(R.string.proj_list_veiled), x.line.veiledLabel) }
            pane == PANE_INFOS -> paneBlock("infos") { ItemInfos(x, list, vm, busy, now) }
            else -> paneBlock("thread") {
                // ce qu'il faut en savoir : venu d'ailleurs, il reste du texte brut
                when {
                    x.more.body.isBlank() -> Unit
                    x.line.outside -> OutsideBlock(x.line.author, x.more.body)
                    else -> MdText(x.more.body)
                }
                if (x.more.link.isNotBlank()) Code(x.more.link)
                if (x.more.thread.isEmpty()) Muted(stringResource(R.string.proj_thread_none))
                for (n in x.more.thread) ThreadNoteView(n, now)
            }
        }
    }
}

/** « Infos » d'un élément : son statut et à qui il est — à changer, quand le serveur l'ouvre —, qui l'a ajouté, quand. */
@Composable
private fun ItemInfos(x: EntryDetail, list: Listing?, vm: ItemViewModel, busy: Boolean, now: Long) {
    val statuses = x.more.statuses.ifEmpty { list?.let { it.open + it.closed }.orEmpty() }
    if (x.more.can.status && statuses.isNotEmpty()) {
        FormChoice(stringResource(R.string.proj_fact_status), statuses, x.line.status, { if (!busy && it != x.line.status) vm.setStatus(it) })
    } else {
        Fact(stringResource(R.string.proj_fact_status), x.line.statusLabel)
    }
    val actors = list?.actors.orEmpty()
    if (x.more.can.assign && actors.isNotEmpty()) {
        FormChoice(stringResource(R.string.proj_fact_actor), actors, x.line.actor, { if (!busy && it != x.line.actor) vm.assign(it) })
    } else {
        Fact(stringResource(R.string.proj_fact_actor), x.line.actorLabel)
    }
    SideTitle(stringResource(R.string.proj_side_brief))
    Fact(stringResource(R.string.proj_fact_opened_by), x.line.author)
    Fact(stringResource(R.string.proj_fact_since), moment(x.line.at, now))
    Fact(stringResource(R.string.proj_fact_updated), moment(x.line.updatedAt, now))
    Fact(stringResource(R.string.proj_list_fact_key), x.line.key)
}

/** Le champ du fil, en bas : une note sur cet élément. */
@Composable
private fun ItemNoteBar(vm: ItemViewModel, busy: Boolean) {
    Surface(color = MaterialTheme.colorScheme.surface, tonalElevation = 3.dp, shadowElevation = 6.dp) {
        Row(Modifier.fillMaxWidth().navigationBarsPadding().imePadding().padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.Bottom) {
            OutlinedTextField(
                value = vm.note,
                onValueChange = { vm.note = it },
                placeholder = { Text(stringResource(R.string.proj_note_hint)) },
                maxLines = 5,
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(8.dp))
            FilledIconButton(onClick = vm::sendNote, enabled = vm.note.isNotBlank() && !busy) { MIcon(R.drawable.ic_m_send, stringResource(R.string.proj_note_add)) }
        }
    }
}
