package fr.qwartz.mika.ui.projects

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import coil3.compose.AsyncImage
import coil3.compose.LocalPlatformContext
import coil3.request.ImageRequest
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.projects.DocBlock
import fr.qwartz.mika.data.moi.projects.DocImage
import fr.qwartz.mika.data.moi.projects.ProjectsApi
import fr.qwartz.mika.data.moi.projects.docBlocks
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.rememberSessionKey

/*
 * Ce que partagent les onglets Documentation, Activité, Dépendances et Listes et « Modifier le projet » (ADR 0296) :
 * leurs pages de détail (`Route.ProjectPage`), leurs modèles par projet et par session, une liste lue ou refusée, une
 * confirmation, et **le rendu d'une page de documentation** — son Markdown par le rendu de l'app (qui ne pose que du
 * texte : aucun balisage n'est interprété, rien ne s'exécute), ses images chargées **seulement** quand elles sont de
 * l'espace du projet, par l'adresse de l'API et sous la session de l'app ; une image d'une autre adresse se dit, sans
 * être chargée.
 */

/** Les pages de détail de ces onglets (`Route.ProjectPage.kind`). */
object SheetPages {
    const val PAGE = "page"
    const val EDIT = "ecrire"
    /** Une page nouvelle : [Route.ProjectPage.key] est son chemin, `ref` son titre. */
    const val NEW = "nouvelle"
    const val DECISION = "decision"
    const val RUN = "execution"
    const val LINK = "lien"
    const val ITEM = "element"
    const val SETTINGS = "reglages"
}

/** Une page de détail d'une fiche : celle que son adresse nomme. */
@Composable
fun SheetPageScreen(graph: AppGraph, route: Route.ProjectPage) {
    when (route.kind) {
        SheetPages.EDIT, SheetPages.NEW -> DocEditScreen(graph, route)
        SheetPages.DECISION -> DecisionScreen(graph, route)
        SheetPages.RUN -> RunScreen(graph, route)
        SheetPages.LINK -> LinkScreen(graph, route)
        SheetPages.ITEM -> ItemScreen(graph, route)
        SheetPages.SETTINGS -> SettingsScreen(graph, route)
        else -> DocPageScreen(graph, route)
    }
}

@Composable
internal fun rememberDocsModel(graph: AppGraph, id: Int): DocsViewModel {
    val session = rememberSessionKey(graph)
    return viewModel(key = "docs|$session|$id") { DocsViewModel(ProjectsDeps(graph), id) }
}

@Composable
internal fun rememberActivityModel(graph: AppGraph, id: Int): ActivityViewModel {
    val session = rememberSessionKey(graph)
    return viewModel(key = "activity|$session|$id") { ActivityViewModel(ProjectsDeps(graph), id) }
}

@Composable
internal fun rememberListsModel(graph: AppGraph, id: Int): ListsViewModel {
    val session = rememberSessionKey(graph)
    return viewModel(key = "lists|$session|$id") { ListsViewModel(ProjectsDeps(graph), id) }
}

/** Un volet sans liste (une lecture refusée, rien à montrer) : il défile quand même, pour qu'on puisse tirer et relire. */
@Composable
internal fun StillPane(content: @Composable () -> Unit) {
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { content() }
    }
}

/** Une liste d'un volet : en cours, refusée (avec les mots du serveur, et « Réessayer »), ou lue. */
@Composable
internal fun <T> ListedPane(load: Load<T>?, onRetry: () -> Unit, content: LazyListScope.(T) -> Unit) {
    when (load) {
        null, Load.Loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        is Load.Failed -> StillPane {
            RefusalNote(load.error.message)
            OutlinedButton(onClick = onRetry) { Text(stringResource(R.string.retry)) }
        }
        is Load.Ready -> LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) { content(load.value) }
    }
}

/** « Afficher la suite » d'une liste lue page par page. */
internal fun LazyListScope.moreRow(shown: Boolean, busy: Boolean, onMore: () -> Unit) {
    if (!shown) return
    item(key = "more") {
        TextButton(onClick = onMore, enabled = !busy, modifier = Modifier.fillMaxWidth().padding(8.dp)) {
            MIcon(R.drawable.ic_m_chev_down, null, size = 18.dp)
            Spacer(Modifier.width(6.dp))
            Text(stringResource(R.string.proj_x_more))
        }
    }
}

/** Une feuille se ferme quand son geste a abouti. */
@Composable
internal fun DoneCloses(runner: GestureRunner, where: String, onDismiss: () -> Unit) {
    LaunchedEffect(runner.finished) {
        if (runner.finished == where) {
            runner.acknowledge()
            onDismiss()
        }
    }
}

/** Une confirmation avant un geste qui ne se défait pas d'un appui (supprimer, archiver, retirer). */
@Composable
internal fun ConfirmDialog(title: String, text: String, confirm: String, onDismiss: () -> Unit, onConfirm: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Text(text) },
        confirmButton = {
            TextButton(onClick = {
                onDismiss()
                onConfirm()
            }) { Text(confirm, color = MaterialTheme.colorScheme.error) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

// ── Une page de documentation, rendue ───────────────────────────────────

/** L'adresse d'une image de l'espace : la route de l'API, que le chargeur d'images de l'app lit sous sa session. */
internal fun docImageUrl(graph: AppGraph, project: Int, name: String): String? = ProjectsApi(graph.moi).docImageUrl(project, name)

/**
 * Une image de l'espace de documentation. Sa clé de cache porte l'instant de son ajout ([stamp]) : une image retirée
 * puis remise sous le même nom ne ressort pas du cache. Introuvable (retirée, oubliée), elle le dit.
 */
@Composable
internal fun DocPicture(graph: AppGraph, project: Int, name: String, alt: String, stamp: Long, modifier: Modifier = Modifier, crop: Boolean = false) {
    val url = remember(project, name) { docImageUrl(graph, project, name) }
    var failed by remember(url, stamp) { mutableStateOf(false) }
    if (url == null || failed) {
        ImageNote(stringResource(R.string.proj_doc_image_missing, name), modifier)
        return
    }
    val context = LocalPlatformContext.current
    val key = "doc|$project|$name|$stamp"
    AsyncImage(
        model = remember(url, key) { ImageRequest.Builder(context).data(url).memoryCacheKey(key).diskCacheKey(key).build() },
        contentDescription = alt.ifBlank { null },
        contentScale = if (crop) ContentScale.Crop else ContentScale.FillWidth,
        onError = { failed = true },
        modifier = modifier.clip(RoundedCornerShape(10.dp)).background(MaterialTheme.colorScheme.surfaceContainerHigh),
    )
}

/** Une image qui ne se montre pas : introuvable dans l'espace, ou d'une autre adresse — dite, jamais chargée. */
@Composable
internal fun ImageNote(text: String, modifier: Modifier = Modifier) {
    Row(
        modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(MaterialTheme.colorScheme.surfaceContainerHigh).padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        MIcon(R.drawable.ic_m_image, null, size = 18.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.width(8.dp))
        Text(text, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** Un morceau d'une page : son texte mis en forme, une image de l'espace, ou ce qu'on dit d'une image d'ailleurs. */
@Composable
internal fun DocBlockView(graph: AppGraph, project: Int, block: DocBlock, images: Map<String, DocImage>?) {
    when (block) {
        is DocBlock.Text -> MdText(block.markdown, Modifier.fillMaxWidth())
        is DocBlock.Image -> if (images != null && block.name !in images) {
            ImageNote(stringResource(R.string.proj_doc_image_missing, block.name))
        } else {
            Column {
                DocPicture(graph, project, block.name, block.alt, images?.get(block.name)?.at ?: 0, Modifier.fillMaxWidth())
                if (block.alt.isNotBlank()) {
                    Text(block.alt, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp))
                }
            }
        }
        is DocBlock.Elsewhere -> ImageNote(stringResource(R.string.proj_doc_image_elsewhere, block.src))
    }
}

/** Une page rendue, dans une liste : un élément par morceau. [images] : celles de l'espace, par leur nom (`null` : pas lues). */
internal fun LazyListScope.docBody(graph: AppGraph, project: Int, blocks: List<DocBlock>, images: Map<String, DocImage>?) {
    itemsIndexed(blocks, key = { i, _ -> "doc$i" }, contentType = { _, b -> b::class }) { _, block ->
        Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp)) { DocBlockView(graph, project, block, images) }
    }
}

/** Une page rendue, d'un bloc (l'aperçu de l'éditeur, une version relue). */
@Composable
internal fun DocText(graph: AppGraph, project: Int, text: String, images: Map<String, DocImage>?, modifier: Modifier = Modifier) {
    val blocks = remember(text) { docBlocks(text) }
    Column(modifier, verticalArrangement = Arrangement.spacedBy(12.dp)) {
        for (b in blocks) DocBlockView(graph, project, b, images)
    }
}
