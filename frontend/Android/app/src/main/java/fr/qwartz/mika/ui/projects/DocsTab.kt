package fr.qwartz.mika.ui.projects

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.projects.Coded
import fr.qwartz.mika.data.moi.projects.Decision
import fr.qwartz.mika.data.moi.projects.DocImage
import fr.qwartz.mika.data.moi.projects.DocNode
import fr.qwartz.mika.data.moi.projects.DocPage
import fr.qwartz.mika.data.moi.projects.DocSpace
import fr.qwartz.mika.data.moi.projects.DocTabs
import fr.qwartz.mika.data.moi.projects.Sheet
import fr.qwartz.mika.data.moi.projects.decisionOrder
import fr.qwartz.mika.data.moi.projects.decisionTone
import fr.qwartz.mika.data.moi.projects.docRows
import fr.qwartz.mika.data.moi.projects.folderPath
import fr.qwartz.mika.data.moi.projects.imageMarkdown
import fr.qwartz.mika.data.moi.projects.pagePath
import fr.qwartz.mika.data.moi.projects.plural
import fr.qwartz.mika.data.moi.projects.since
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.Shell

/*
 * L'onglet Documentation d'une fiche (ADR 0296), d'après la maquette validée en largeur de téléphone : trois volets en
 * pastilles — **Pages** (une recherche, l'arborescence qui se replie, « Nouvelle page »), **Images** (la grille,
 * téléverser, copier la référence à coller dans une page, retirer) et **Décisions** (la liste). Un espace à part du
 * dépôt : le code et son README restent dans Code › Fichiers. Une page, une décision s'ouvrent en page.
 */

@Composable
internal fun DocsTab(graph: AppGraph, vm: ProjectViewModel, sheet: Sheet, now: Long, sub: String) {
    val shell = LocalShell.current
    val docs = rememberDocsModel(graph, vm.id)
    val shown = DocTabs.of(sub)
    Toasts(docs.gestures)
    OnResume(docs) { docs.resume() }
    LaunchedEffect(docs, shown) { docs.show(shown) }
    LaunchedEffect(vm.refreshing) { if (vm.refreshing) docs.reload() }
    val space = docs.space.value
    Column(Modifier.fillMaxSize()) {
        ChipRow(
            listOf(
                Chip(DocTabs.PAGES, stringResource(R.string.proj_doc_tab_pages), space?.pages?.size),
                Chip(DocTabs.IMAGES, stringResource(R.string.proj_doc_tab_images), space?.images?.size),
                Chip(DocTabs.DECISIONS, stringResource(R.string.proj_doc_tab_decisions), docs.decisions.value?.inForce),
            ),
            selected = shown,
            onPick = { if (it != shown) shell.replace(Route.Project(vm.id, DocTabs.tab(it))) },
            modifier = Modifier.padding(top = 4.dp),
        )
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        when (shown) {
            DocTabs.IMAGES -> ImagesPane(graph, docs, now)
            DocTabs.DECISIONS -> DecisionsPane(docs, shell, now)
            else -> PagesPane(docs, sheet, shell, now)
        }
    }
}

// ── Pages ───────────────────────────────────────────────────────────────

@Composable
private fun PagesPane(docs: DocsViewModel, sheet: Sheet, shell: Shell, now: Long) {
    var creating by rememberSaveable { mutableStateOf(false) }
    val open: (String) -> Unit = { shell.navigate(Route.ProjectPage(docs.id, SheetPages.PAGE, it)) }
    ListedPane(docs.space.load, docs.space::retry) { space ->
        item(key = "tools") {
            Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(
                    value = docs.query,
                    onValueChange = { docs.search(it) },
                    placeholder = { Text(stringResource(R.string.proj_doc_search)) },
                    leadingIcon = { MIcon(R.drawable.ic_m_search, null, size = 20.dp) },
                    singleLine = true,
                    modifier = Modifier.weight(1f),
                )
                if (space.rights.write) {
                    Spacer(Modifier.width(8.dp))
                    FilledIconButton(onClick = { creating = true }) { MIcon(R.drawable.ic_m_plus, stringResource(R.string.proj_doc_new)) }
                }
            }
        }
        val found = docs.found
        when {
            found != null -> when (found) {
                Load.Loading -> item(key = "searching") { Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() } }
                is Load.Failed -> item(key = "refused") { RefusalNote(found.error.message, Modifier.padding(16.dp)) }
                is Load.Ready -> {
                    if (found.value.items.isEmpty()) {
                        item(key = "nothing") { EmptyNote(R.drawable.ic_m_search, stringResource(R.string.proj_doc_found_none), stringResource(R.string.proj_doc_found_none_sub)) }
                    }
                    items(found.value.items, key = { "f${it.path}" }) { p -> FoundRow(p, now) { open(p.path) } }
                }
            }
            space.pages.isEmpty() -> item(key = "none") {
                EmptyNote(
                    R.drawable.ic_m_book,
                    stringResource(R.string.proj_doc_none),
                    stringResource(if (space.rights.write) R.string.proj_doc_none_sub else R.string.proj_doc_none_read),
                ) {
                    if (space.rights.write) Button(onClick = { creating = true }) { Text(stringResource(R.string.proj_doc_new)) }
                }
            }
            else -> items(docRows(space.pages, docs.closed), key = { (if (it.page == null) "d" else "p") + it.path }) { node ->
                TreeRow(node, node.path in docs.closed) { if (node.page == null) docs.fold(node.path) else open(node.path) }
            }
        }
    }
    val space = docs.space.value
    if (creating && space != null) {
        NewPageSheet(sheet, space, onDismiss = { creating = false }) { path, title ->
            creating = false
            // une page qui existe déjà s'ouvre ; sinon elle s'écrit, et naît à son premier enregistrement
            if (space.pages.any { it.path == path }) open(path) else shell.navigate(Route.ProjectPage(docs.id, SheetPages.NEW, path, title))
        }
    }
}

/** Une ligne de l'arborescence : un dossier (qui se replie) ou une page, en retrait selon sa profondeur. */
@Composable
private fun TreeRow(node: DocNode, closed: Boolean, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(start = (12 + 20 * node.depth).dp, end = 16.dp, top = 11.dp, bottom = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (node.page == null) {
            MIcon(if (closed) R.drawable.ic_m_chev_right else R.drawable.ic_m_chev_down, null, size = 16.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.width(6.dp))
            MIcon(R.drawable.ic_m_folder, null, size = 18.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.width(10.dp))
            Text(node.name, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
        } else {
            Spacer(Modifier.width(22.dp))
            MIcon(R.drawable.ic_m_file, null, size = 18.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.width(10.dp))
            Text(node.name, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}

/** Une page trouvée : son titre, son chemin, le passage. */
@Composable
private fun FoundRow(p: DocPage, now: Long, onClick: () -> Unit) {
    Column(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(Modifier.padding(horizontal = 16.dp, vertical = 10.dp)) {
            Text(p.title.ifBlank { p.name }, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                listOf(p.path, since(p.at, now)).filter { it.isNotBlank() }.joinToString(" · "),
                style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            if (p.excerpt.isNotBlank()) {
                Gap(4.dp)
                Text(p.excerpt, style = MaterialTheme.typography.bodyMedium, maxLines = 3, overflow = TextOverflow.Ellipsis)
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    }
}

/**
 * « Nouvelle page » : son titre, son dossier (un de ceux de l'espace, ou un nouveau). Son chemin se replie comme le
 * serveur l'attend — lui seul juge s'il vaut ; la page naît à son premier enregistrement.
 */
@Composable
private fun NewPageSheet(sheet: Sheet, space: DocSpace, onDismiss: () -> Unit, onCreate: (path: String, title: String) -> Unit) {
    var title by rememberSaveable { mutableStateOf("") }
    var folder by rememberSaveable { mutableStateOf("") }
    var fresh by rememberSaveable { mutableStateOf("") }
    val root = stringResource(R.string.proj_doc_root)
    val path = pagePath(folderPath(fresh).ifEmpty { folder }, title)
    FormSheet(
        title = stringResource(R.string.proj_doc_new),
        sub = stringResource(R.string.proj_doc_new_sub, sheet.project.title),
        submit = stringResource(R.string.proj_doc_new_ok),
        busy = false,
        error = "",
        onDismiss = onDismiss,
        onSubmit = { onCreate(path, title.trim()) },
        enabled = path.isNotEmpty(),
    ) {
        FormText(stringResource(R.string.proj_doc_new_title), title, { title = it }, hint = stringResource(R.string.proj_doc_new_title_hint))
        FormChoice(stringResource(R.string.proj_doc_new_folder), listOf(Coded("", root)) + space.folders.map { Coded(it, it) }, folder, { folder = it })
        FormText(stringResource(R.string.proj_doc_new_folder_fresh), fresh, { fresh = it }, hint = stringResource(R.string.proj_doc_new_folder_hint))
        if (path.isNotEmpty()) Hint(stringResource(R.string.proj_doc_new_path, path), R.drawable.ic_m_file)
    }
}

// ── Images ──────────────────────────────────────────────────────────────

/** Un poids en mots : « 18 Ko », « 1,2 Mo ». */
internal fun weight(bytes: Long): String = when {
    bytes < 1024 -> "$bytes o"
    bytes < 1024 * 1024 -> "${(bytes + 512) / 1024} Ko"
    else -> "%.1f Mo".format(java.util.Locale.FRANCE, bytes / (1024.0 * 1024.0))
}

@Composable
private fun ImagesPane(graph: AppGraph, docs: DocsViewModel, now: Long) {
    val shell = LocalShell.current
    var picked by rememberSaveable { mutableStateOf("") }
    val unreadable = stringResource(R.string.proj_doc_image_unreadable)
    when (val load = docs.space.load) {
        null, Load.Loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        is Load.Failed -> StillPane {
            RefusalNote(load.error.message)
            OutlinedButton(onClick = docs.space::retry) { Text(stringResource(R.string.retry)) }
        }
        is Load.Ready -> {
            val space = load.value
            val pick = rememberImagePicker(space.limits.imageBytes, onPicked = { docs.upload(it) }, onUnreadable = { shell.toast(unreadable) })
            LazyVerticalGrid(
                GridCells.Fixed(2),
                Modifier.fillMaxSize(),
                contentPadding = PaddingValues(start = 12.dp, end = 12.dp, top = 12.dp, bottom = 24.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                item(key = "head", span = { GridItemSpan(maxLineSpan) }) {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(stringResource(R.string.proj_doc_images_title), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                        Text(stringResource(R.string.proj_doc_images_sub), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        RefusalNote(docs.gestures.refusalAt(DocsViewModel.IMAGES))
                        if (space.rights.write) {
                            Button(onClick = pick, enabled = !docs.uploading) {
                                if (docs.uploading) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp) else MIcon(R.drawable.ic_m_plus, null, size = 18.dp)
                                Spacer(Modifier.width(8.dp))
                                Text(stringResource(if (docs.uploading) R.string.proj_doc_image_sending else R.string.proj_doc_image_upload))
                            }
                        }
                        if (space.limits.spaceBytes > 0) {
                            Text(
                                stringResource(R.string.proj_doc_space_used, weight(space.spaceUsed), weight(space.limits.spaceBytes)),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
                if (space.images.isEmpty()) {
                    item(key = "none", span = { GridItemSpan(maxLineSpan) }) {
                        EmptyNote(R.drawable.ic_m_image, stringResource(R.string.proj_doc_images_none), stringResource(R.string.proj_doc_images_none_sub))
                    }
                }
                items(space.images, key = { "i${it.name}" }) { image -> ImageCard(graph, docs.id, image) { picked = image.name } }
            }
            space.images.firstOrNull { it.name == picked }?.let { image ->
                ImageSheet(graph, docs, image, space.rights.write, now) { picked = "" }
            }
        }
    }
}

/** Une image de la grille : sa vignette, son nom, son poids et les pages qui la citent. */
@Composable
private fun ImageCard(graph: AppGraph, project: Int, image: DocImage, onClick: () -> Unit) {
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(14.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Column {
            DocPicture(graph, project, image.name, image.name, image.at, Modifier.fillMaxWidth().aspectRatio(4f / 3f), crop = true)
            Column(Modifier.padding(horizontal = 10.dp, vertical = 8.dp)) {
                Text(image.name, style = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace), fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(
                    weight(image.size) + " · " + if (image.usedBy.isEmpty()) stringResource(R.string.proj_doc_image_unused) else plural(image.usedBy.size, "page", "pages"),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                )
            }
        }
    }
}

/** Une image ouverte : elle en grand, ce qu'on en sait, la référence à coller dans une page, et la retirer selon le droit servi. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ImageSheet(graph: AppGraph, docs: DocsViewModel, image: DocImage, write: Boolean, now: Long, onDismiss: () -> Unit) {
    val copy = rememberCopy()
    var removing by rememberSaveable { mutableStateOf(false) }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(
            Modifier.fillMaxWidth().navigationBarsPadding().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(bottom = 16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(image.name, style = MaterialTheme.typography.titleMedium.copy(fontFamily = FontFamily.Monospace), fontWeight = FontWeight.Bold)
            DocPicture(graph, docs.id, image.name, image.name, image.at, Modifier.fillMaxWidth())
            Fact(stringResource(R.string.proj_doc_fact_weight), listOf(weight(image.size), image.mime).filter { it.isNotBlank() }.joinToString(" · "))
            Fact(stringResource(R.string.proj_doc_fact_added), listOf(image.author, image.viaLabel, since(image.at, now)).filter { it.isNotBlank() }.joinToString(" · "))
            Fact(stringResource(R.string.proj_doc_fact_used), if (image.usedBy.isEmpty()) stringResource(R.string.proj_doc_image_unused) else image.usedBy.joinToString(", "))
            Text(stringResource(R.string.proj_doc_image_ref), style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold)
            MonoLine(imageMarkdown(image.name))
            RefusalNote(docs.gestures.refusalAt(DocsViewModel.IMAGES))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { copy(imageMarkdown(image.name)) }) {
                    MIcon(R.drawable.ic_m_copy, null, size = 18.dp)
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.proj_doc_image_copy))
                }
                if (write) {
                    OutlinedButton(onClick = { removing = true }, enabled = docs.gestures.busy.isEmpty()) {
                        MIcon(R.drawable.ic_m_trash, null, size = 18.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.proj_remove))
                    }
                }
            }
        }
    }
    if (removing) {
        ConfirmDialog(
            stringResource(R.string.proj_doc_image_remove_title),
            stringResource(R.string.proj_doc_image_remove_text, image.name),
            stringResource(R.string.proj_remove),
            onDismiss = { removing = false },
        ) { docs.removeImage(image.name) }
    }
}

/** Une ligne en chasse fixe sur un fond léger (une référence à copier). */
@Composable
internal fun MonoLine(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
        modifier = Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceContainerHigh, RoundedCornerShape(8.dp)).padding(10.dp),
    )
}

// ── Décisions ───────────────────────────────────────────────────────────

@Composable
private fun DecisionsPane(docs: DocsViewModel, shell: Shell, now: Long) {
    ListedPane(docs.decisions.load, docs.decisions::retry) { list ->
        item(key = "title") {
            Text(
                stringResource(R.string.proj_doc_decisions_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 14.dp, bottom = 6.dp),
            )
        }
        if (list.items.isEmpty()) {
            item(key = "none") { EmptyNote(R.drawable.ic_m_shield_check, stringResource(R.string.proj_doc_decisions_none), stringResource(R.string.proj_doc_decisions_none_sub)) }
        }
        items(decisionOrder(list.items), key = { "d${it.number}" }) { d ->
            DecisionRow(d, now) { shell.navigate(Route.ProjectPage(docs.id, SheetPages.DECISION, d.number.toString())) }
        }
    }
}

@Composable
private fun DecisionRow(d: Decision, now: Long, onClick: () -> Unit) {
    Column(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Row(Modifier.padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.Top) {
            Tile(R.drawable.ic_m_shield_check, decisionTone(d.status))
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(d.title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Gap(6.dp)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    StatePill(decisionTone(d.status), d.statusLabel)
                    Spacer(Modifier.width(10.dp))
                    Text(stringResource(R.string.proj_number, d.number), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.weight(1f))
                    Text(since(d.at, now), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                }
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    }
}
