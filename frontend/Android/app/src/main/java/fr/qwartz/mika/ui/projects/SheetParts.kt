package fr.qwartz.mika.ui.projects

import androidx.activity.compose.LocalActivity
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
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
import coil3.network.HttpException
import coil3.request.ImageRequest
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.projects.DocBlock
import fr.qwartz.mika.data.moi.projects.DocImage
import fr.qwartz.mika.data.moi.projects.ProjectsApi
import fr.qwartz.mika.data.moi.projects.docBlocks
import fr.qwartz.mika.data.moi.projects.keyed
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.rememberSessionKey
import kotlinx.coroutines.withContext
import kotlinx.coroutines.Dispatchers
import androidx.compose.runtime.produceState
import fr.qwartz.mika.ui.components.ProMarkdownBlocks
import fr.qwartz.mika.ui.components.ProMarkdown

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
        SheetPages.EDIT -> DocEditScreen(graph, route)
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

/**
 * Les lignes d'une liste, chacune sous sa clé — unique quoi que rende le serveur ([keyed]) : deux clés égales feraient
 * tomber la liste.
 */
internal fun <T> LazyListScope.keyedItems(rows: List<T>, key: (T) -> String, row: @Composable (T) -> Unit) {
    items(keyed(rows, key), key = { it.key }) { row(it.value) }
}

/**
 * Ce qu'un écran fait quand on le quitte pour de bon — pas à une rotation, où il revient aussitôt : son modèle baisse
 * ce qui ne vaut qu'une fois (suivre une page déplacée, revenir après un enregistrement), pour qu'un geste abouti après
 * le départ ne referme ni ne déplace l'écran à son retour. [block] est celui de l'écran qu'on quitte : quand [keys]
 * change (une autre page dans le même écran), c'est l'ancienne qui est quittée.
 */
@Composable
internal fun OnLeave(vararg keys: Any?, block: () -> Unit) {
    val activity = LocalActivity.current
    DisposableEffect(*keys) {
        onDispose { if (activity?.isChangingConfigurations != true) block() }
    }
}

/**
 * Une feuille se ferme quand son geste a abouti — celui qu'elle a envoyé : en s'ouvrant, elle oublie ce qu'on avait dit
 * à son endroit, une fois par ouverture (une rotation n'efface pas le refus qu'on est en train de lire).
 */
@Composable
internal fun DoneCloses(runner: GestureRunner, where: String, onDismiss: () -> Unit) {
    FreshEntry(runner, where)
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
                // le geste d'abord : il lit ce que la fenêtre montrait (un numéro de version), que la fermer efface
                onConfirm()
                onDismiss()
            }) { Text(confirm, color = MaterialTheme.colorScheme.error) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

// ── Une page de documentation, rendue ───────────────────────────────────

/** L'adresse d'une image de l'espace : la route de l'API, que le chargeur d'images de l'app lit sous sa session. */
internal fun docImageUrl(graph: AppGraph, project: Int, name: String): String? = ProjectsApi(graph.moi).docImageUrl(project, name)

private const val PICTURE_OK = 0
private const val PICTURE_GONE = 1
private const val PICTURE_UNLOADED = 2

/**
 * Une image de l'espace de documentation. Sa clé de cache porte l'instant de son ajout ([stamp]) : une image retirée
 * puis remise sous le même nom ne ressort pas du cache. Introuvable (retirée, oubliée : le serveur répond 404), elle le
 * dit ; pas chargée pour une autre raison (hors ligne, une panne), elle le dit aussi, et se recharge quand on la touche.
 */
@Composable
internal fun DocPicture(graph: AppGraph, project: Int, name: String, alt: String, stamp: Long, modifier: Modifier = Modifier, crop: Boolean = false) {
    val url = remember(project, name) { docImageUrl(graph, project, name) }
    var state by remember(url, stamp) { mutableIntStateOf(PICTURE_OK) }
    var attempt by remember(url, stamp) { mutableIntStateOf(0) }
    when {
        url == null || state == PICTURE_GONE -> {
            ImageNote(stringResource(R.string.proj_doc_image_missing, name), modifier)
            return
        }
        state == PICTURE_UNLOADED -> {
            ImageNote(stringResource(R.string.proj_doc_image_unloaded, name), modifier.clickable {
                attempt++
                state = PICTURE_OK
            })
            return
        }
    }
    val context = LocalPlatformContext.current
    val key = "doc|$project|$name|$stamp"
    AsyncImage(
        model = remember(url, key, attempt) { ImageRequest.Builder(context).data(url).memoryCacheKey(key).diskCacheKey(key).build() },
        contentDescription = alt.ifBlank { null },
        contentScale = if (crop) ContentScale.Crop else ContentScale.FillWidth,
        onError = { failure -> state = if ((failure.result.throwable as? HttpException)?.response?.code == 404) PICTURE_GONE else PICTURE_UNLOADED },
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

/**
 * Un morceau d'une page prêt à poser : **un** bloc de son Markdown, déjà lu par le rendu de l'app, une image de
 * l'espace, ou ce qu'on dit d'une image d'ailleurs. Une page se découpe une fois, hors du fil principal ([docPieces],
 * par le modèle) : l'écran pose un élément par morceau — une longue page ne se lit ni ne se compose d'un bloc.
 */
sealed interface DocPiece {
    class Md(val block: ProMarkdown.Block) : DocPiece
    class Picture(val image: DocBlock) : DocPiece
}

/** Une page en morceaux prêts à poser : son texte coupé là où elle cite une image ([docBlocks]), puis son Markdown lu bloc par bloc. */
internal fun docPieces(text: String): List<DocPiece> = docBlocks(text).flatMap { b ->
    when (b) {
        is DocBlock.Text -> ProMarkdown.parse(b.markdown).map { DocPiece.Md(it) }
        else -> listOf(DocPiece.Picture(b))
    }
}

/** Un morceau d'une page, posé : un bloc de Markdown (ses liens http(s) s'ouvrent, comme dans une page), ou une image. */
@Composable
internal fun DocPieceView(graph: AppGraph, project: Int, piece: DocPiece, images: Map<String, DocImage>?) {
    when (piece) {
        is DocPiece.Md -> ProMarkdownBlocks(listOf(piece.block), MaterialTheme.colorScheme.onSurface, Modifier.fillMaxWidth())
        is DocPiece.Picture -> DocBlockView(graph, project, piece.image, images)
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

/**
 * Une page rendue, dans une liste : un élément par morceau ([pieces], découpés par le modèle hors du fil principal).
 * [images] : celles de l'espace, par leur nom (`null` : pas lues).
 */
internal fun LazyListScope.docBody(graph: AppGraph, project: Int, pieces: List<DocPiece>, images: Map<String, DocImage>?) {
    itemsIndexed(pieces, key = { i, _ -> "doc$i" }, contentType = { _, p -> if (p is DocPiece.Md) p.block::class else p::class }) { _, piece ->
        Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = if (piece is DocPiece.Md) 3.dp else 6.dp)) { DocPieceView(graph, project, piece, images) }
    }
}

/**
 * Une page rendue, d'un bloc (l'aperçu de l'éditeur, la version actuelle d'un conflit) : découpée hors du fil principal,
 * à chaque texte — le temps de la découpe, rien n'est posé.
 */
@Composable
internal fun DocText(graph: AppGraph, project: Int, text: String, images: Map<String, DocImage>?, modifier: Modifier = Modifier) {
    val pieces by produceState(emptyList<DocPiece>(), text) { value = withContext(Dispatchers.Default) { docPieces(text) } }
    Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        for (p in pieces) DocPieceView(graph, project, p, images)
    }
}
