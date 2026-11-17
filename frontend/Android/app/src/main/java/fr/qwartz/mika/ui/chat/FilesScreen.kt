package fr.qwartz.mika.ui.chat

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil3.compose.AsyncImage
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.files.MikaFileRefs
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.FileActions
import fr.qwartz.mika.ui.components.rememberFileActions
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.ListHead
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.time.ZoneId

/** Trois images par rangée. */
private const val GRID_COLUMNS = 3

/**
 * « Fichiers échangés » (`Route.Files`, ADR 0215) : ce qu'elle t'a envoyé et ce que tu lui as envoyé, tant que le serveur
 * le garde — dans les messages gardés sur ce téléphone, fils de travail compris. Puces Tout · Les siens · Les tiens ; les
 * images en grille (bord rose : les siennes ; touchée, elle s'ouvre en grand ; un appui long, ses gestes), les documents
 * en liste. Chacun : « Enregistrer » (Téléchargements/Mika), « Ouvrir avec… », « Voir dans la conversation ».
 */
@Composable
fun FilesScreen(graph: AppGraph) {
    val shell = LocalShell.current
    val chat = rememberChatModel(graph)
    val messages by graph.chat.observe().collectAsStateWithLifecycle(emptyList())
    var chip by rememberSaveable { mutableStateOf(FilesChip.ALL) }
    val files = rememberFileActions(graph, shell.snackbar)
    val zone = remember { ZoneId.systemDefault() }
    val now = graph.clock.wallMs()
    val all = remember(messages) { ExchangedFiles.of(messages) }
    val shown = ExchangedFiles.filter(all, chip)
    val images = shown.filter { it.image }
    val documents = shown.filter { !it.image }
    val showInChat: (ExchangedFile) -> Unit = { f ->
        chat.showMessage(f.message)
        shell.open(Route.Chat)
    }
    val enlarge: (ExchangedFile) -> Unit = { f ->
        val path = MikaFileRefs.path(f.att)
        val id = f.att.id
        if (path != null && id != null) shell.navigate(Route.Viewer(id, f.att.name, path, f.att.mime, f.att.size))
    }

    SectionScaffold(topBar = { MikaTopBar(stringResource(R.string.files_title), BarNav.BACK) }) { modifier ->
        Column(modifier) {
            Row(
                Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                for ((c, label) in listOf(FilesChip.ALL to R.string.files_chip_all, FilesChip.HERS to R.string.files_chip_hers, FilesChip.YOURS to R.string.files_chip_yours)) {
                    FilterChip(selected = chip == c, onClick = { chip = c }, label = { Text(stringResource(label)) })
                }
            }
            if (shown.isEmpty()) {
                Column(Modifier.fillMaxSize().padding(32.dp), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
                    MIcon(R.drawable.ic_m_clip, null, size = 32.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.size(12.dp))
                    Text(stringResource(R.string.files_empty_title), style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.size(6.dp))
                    Text(stringResource(R.string.files_empty_text), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                return@Column
            }
            LazyColumn(Modifier.fillMaxWidth().weight(1f)) {
                if (images.isNotEmpty()) {
                    item(key = "h-images") { ListHead(stringResource(R.string.files_images, images.size)) }
                    items(images.chunked(GRID_COLUMNS), key = { row -> "r" + row.first().key }) { row ->
                        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            for (f in row) ImageTile(graph, f, files, enlarge, showInChat, Modifier.weight(1f))
                            repeat(GRID_COLUMNS - row.size) { Spacer(Modifier.weight(1f)) }
                        }
                    }
                }
                if (documents.isNotEmpty()) {
                    item(key = "h-docs") { ListHead(stringResource(R.string.files_documents, documents.size)) }
                    items(documents, key = { it.key }) { f -> DocumentRow(f, files, now, zone, showInChat) }
                }
                item(key = "note") {
                    Text(
                        stringResource(R.string.files_note),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(16.dp),
                    )
                }
            }
        }
    }
}

/** Une image : sa vignette (celle du serveur, ou la tienne encore sur ce téléphone), son nom ; bord rose : la sienne. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ImageTile(
    graph: AppGraph,
    f: ExchangedFile,
    files: FileActions,
    onEnlarge: (ExchangedFile) -> Unit,
    onShowInChat: (ExchangedFile) -> Unit,
    modifier: Modifier = Modifier,
) {
    var menu by remember { mutableStateOf(false) }
    val url = if (f.fetchable) graph.downloads.absoluteUrl(f.att) else null
    val cid = f.message.cid
    val local = f.att.local
    val file by produceState<File?>(null, cid, local, f.local) {
        value = if (f.local && cid != null && local != null) withContext(Dispatchers.IO) { graph.files.locate(cid, local) } else null
    }
    val name = f.att.name
    val described = stringResource(if (f.hers) R.string.file_image_of_mika else R.string.file_image_sent, name)
    val enlargeLabel = stringResource(R.string.file_enlarge)
    val actionsLabel = stringResource(R.string.files_actions, name)
    val showLabel = stringResource(R.string.files_show_in_chat)
    val shape = RoundedCornerShape(12.dp)
    Box(modifier) {
        Column(
            Modifier
                .fillMaxWidth()
                .clip(shape)
                .then(if (f.hers) Modifier.border(BorderStroke(2.dp, mika.line), shape) else Modifier)
                .combinedClickable(
                    role = Role.Button,
                    onClickLabel = if (f.fetchable) enlargeLabel else actionsLabel,
                    onLongClickLabel = actionsLabel,
                    onClick = { if (f.fetchable) onEnlarge(f) else menu = true },
                    onLongClick = { menu = true },
                )
                .semantics {
                    contentDescription = described
                    customActions = listOf(CustomAccessibilityAction(showLabel) { onShowInChat(f); true })
                },
        ) {
            Box(Modifier.fillMaxWidth().aspectRatio(1f).background(MaterialTheme.colorScheme.surfaceContainerHigh), contentAlignment = Alignment.Center) {
                val model: Any? = file ?: url
                if (model != null && !f.removed) {
                    AsyncImage(
                        model = model,
                        contentDescription = null,
                        contentScale = ContentScale.Crop,
                        placeholder = painterResource(R.drawable.ic_image),
                        error = painterResource(R.drawable.ic_image),
                        modifier = Modifier.fillMaxSize(),
                    )
                } else {
                    MIcon(R.drawable.ic_m_image, null, size = 28.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            Text(
                name,
                style = MaterialTheme.typography.labelSmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                color = if (f.removed) MaterialTheme.colorScheme.onSurfaceVariant else Color.Unspecified,
                modifier = Modifier.padding(horizontal = 6.dp, vertical = 4.dp),
            )
        }
        FileMenu(menu, f, files, onDismiss = { menu = false }, onEnlarge = onEnlarge.takeIf { f.fetchable }, onShowInChat = onShowInChat)
    }
}

/** Un document : son icône (rose : le sien), son nom, sa taille, de qui, quand ; ⋮ ses gestes. */
@Composable
private fun DocumentRow(f: ExchangedFile, files: FileActions, now: Long, zone: ZoneId, onShowInChat: (ExchangedFile) -> Unit) {
    var menu by remember { mutableStateOf(false) }
    val busy = files.busy != null && files.busy == f.att.id
    Row(
        Modifier.fillMaxWidth().heightIn(min = 64.dp).padding(start = 16.dp, end = 4.dp, top = 6.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Surface(
            shape = RoundedCornerShape(12.dp),
            color = if (f.hers) mika.soft else MaterialTheme.colorScheme.surfaceContainerHigh,
            modifier = Modifier.size(40.dp),
        ) {
            Box(contentAlignment = Alignment.Center) {
                MIcon(R.drawable.ic_m_file, null, size = 20.dp, tint = if (f.hers) mika.accent else MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(f.att.name, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                ExchangedFiles.detail(f, now, zone),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Box {
            IconButton(onClick = { menu = true }, enabled = !busy) {
                MIcon(R.drawable.ic_m_more, stringResource(R.string.files_actions, f.att.name))
            }
            FileMenu(menu, f, files, onDismiss = { menu = false }, onEnlarge = null, onShowInChat = onShowInChat)
        }
    }
}

/** Les gestes d'un fichier : l'agrandir (une image), l'enregistrer, l'ouvrir avec…, le voir dans la conversation. */
@Composable
private fun FileMenu(
    open: Boolean,
    f: ExchangedFile,
    files: FileActions,
    onDismiss: () -> Unit,
    onEnlarge: ((ExchangedFile) -> Unit)?,
    onShowInChat: (ExchangedFile) -> Unit,
) {
    DropdownMenu(expanded = open, onDismissRequest = onDismiss) {
        if (onEnlarge != null) {
            DropdownMenuItem(
                text = { Text(stringResource(R.string.file_enlarge)) },
                leadingIcon = { MIcon(R.drawable.ic_m_eye, null, size = 20.dp) },
                onClick = { onDismiss(); onEnlarge(f) },
            )
        }
        DropdownMenuItem(
            text = { Text(stringResource(R.string.file_save)) },
            leadingIcon = { MIcon(R.drawable.ic_m_download, null, size = 20.dp) },
            enabled = f.fetchable && files.busy == null,
            onClick = { onDismiss(); files.save(f.att) },
        )
        DropdownMenuItem(
            text = { Text(stringResource(R.string.file_open_with)) },
            leadingIcon = { MIcon(R.drawable.ic_m_external, null, size = 20.dp) },
            enabled = f.fetchable && files.busy == null,
            onClick = { onDismiss(); files.open(f.att) },
        )
        DropdownMenuItem(
            text = { Text(stringResource(R.string.files_show_in_chat)) },
            leadingIcon = { MIcon(R.drawable.ic_m_chat, null, size = 20.dp) },
            onClick = { onDismiss(); onShowInChat(f) },
        )
    }
}
