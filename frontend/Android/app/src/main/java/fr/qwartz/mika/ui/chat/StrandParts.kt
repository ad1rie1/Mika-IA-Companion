package fr.qwartz.mika.ui.chat

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.data.chat.Strands
import fr.qwartz.mika.data.net.MikaProtocol
import fr.qwartz.mika.data.net.StrandInfo

/** Le nom d'un fil à l'écran : son titre, sinon le début de son premier message, sinon « Nouveau fil ». */
@Composable
private fun strandName(strand: StrandInfo?): String = Strands.label(strand) ?: stringResource(R.string.strand_new)

/**
 * En mode pro (ADR 0164), au-dessus du fil : le fil de travail ouvert — son nom, sa description, archivé ou non — et
 * de quoi ouvrir la liste des fils ou un fil neuf. Toucher le nom le règle.
 */
@Composable
internal fun StrandBar(strand: StrandInfo?, onList: () -> Unit, onEdit: () -> Unit, onNew: () -> Unit) {
    val editLabel = stringResource(R.string.strand_edit_desc)
    Surface(tonalElevation = 1.dp) {
        Row(
            Modifier.fillMaxWidth().padding(start = 16.dp, end = 4.dp, top = 4.dp, bottom = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(
                Modifier
                    .weight(1f)
                    .heightIn(min = 48.dp)
                    .clickable(onClickLabel = editLabel, onClick = onEdit)
                    .padding(vertical = 4.dp),
                verticalArrangement = Arrangement.Center,
            ) {
                val archived = if (strand?.archived == true) " · " + stringResource(R.string.strand_archived) else ""
                Text(
                    strandName(strand) + archived,
                    style = MaterialTheme.typography.titleSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.semantics { heading() },
                )
                val description = strand?.description.orEmpty()
                if (description.isNotBlank()) {
                    Text(
                        description,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            TextButton(onClick = onList) { Text(stringResource(R.string.strand_list)) }
            TextButton(onClick = onNew) { Text(stringResource(R.string.strand_new_short)) }
        }
    }
}

/**
 * La liste de ses fils de travail (ADR 0164) : un fil neuf, ses fils en cours du plus récemment actif au plus ancien,
 * puis ses fils archivés, repliés.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun StrandSheet(
    strands: List<StrandInfo>,
    active: String?,
    onDismiss: () -> Unit,
    onOpen: (String) -> Unit,
    onNew: () -> Unit,
) {
    var showArchived by rememberSaveable { mutableStateOf(false) }
    val (archived, current) = strands.partition { it.archived }
    ModalBottomSheet(onDismissRequest = onDismiss) {
        LazyColumn(Modifier.navigationBarsPadding().padding(bottom = 16.dp)) {
            item(key = "title") {
                Text(
                    stringResource(R.string.strand_list_title),
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp).semantics { heading() },
                )
            }
            item(key = "new") {
                Surface(onClick = onNew) {
                    ListItem(
                        headlineContent = { Text(stringResource(R.string.strand_new)) },
                        supportingContent = { Text(stringResource(R.string.strand_new_desc)) },
                    )
                }
            }
            items(current, key = { "s" + it.id }) { s -> StrandRow(s, s.id == active) { onOpen(s.id) } }
            if (archived.isNotEmpty()) {
                item(key = "archived") {
                    HorizontalDivider()
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .heightIn(min = 48.dp)
                            .toggleable(value = showArchived, role = Role.Switch) { showArchived = it }
                            .padding(horizontal = 16.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            (if (showArchived) "▾ " else "▸ ") +
                                stringResource(R.string.strand_archived_section, archived.size),
                            style = MaterialTheme.typography.labelLarge,
                        )
                    }
                }
                if (showArchived) {
                    items(archived, key = { "a" + it.id }) { s -> StrandRow(s, s.id == active) { onOpen(s.id) } }
                }
            }
        }
    }
}

@Composable
private fun StrandRow(strand: StrandInfo, current: Boolean, onClick: () -> Unit) {
    val details = buildList {
        if (strand.description.isNotBlank()) add(strand.description.trim())
        if (strand.count > 0) add(pluralStringResource(R.plurals.strand_messages, strand.count, strand.count))
    }.joinToString(" · ")
    Surface(onClick = onClick) {
        ListItem(
            headlineContent = { Text(strandName(strand), maxLines = 1, overflow = TextOverflow.Ellipsis) },
            supportingContent = if (details.isNotEmpty()) {
                { Text(details, maxLines = 2, overflow = TextOverflow.Ellipsis) }
            } else {
                null
            },
            trailingContent = if (current) {
                { Text(stringResource(R.string.strand_current), style = MaterialTheme.typography.labelMedium) }
            } else {
                null
            },
            colors = if (current) {
                ListItemDefaults.colors(containerColor = MaterialTheme.colorScheme.secondaryContainer)
            } else {
                ListItemDefaults.colors()
            },
        )
    }
}

/**
 * Régler un fil de travail (ADR 0164) : son titre, sa petite description — ce que Mika relit en tête de ce fil, à
 * chaque message —, archivé ou non. Le réglage entier part d'un coup.
 */
@Composable
internal fun StrandEditDialog(
    strand: StrandInfo,
    onDismiss: () -> Unit,
    onSave: (title: String, description: String, archived: Boolean) -> Unit,
) {
    var title by rememberSaveable(strand.id) { mutableStateOf(strand.title) }
    var description by rememberSaveable(strand.id) { mutableStateOf(strand.description) }
    var archived by rememberSaveable(strand.id) { mutableStateOf(strand.archived) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.strand_edit_title)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = title,
                    onValueChange = { title = it.take(MikaProtocol.MAX_STRAND_TITLE_CHARS) },
                    label = { Text(stringResource(R.string.strand_title_label)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = description,
                    onValueChange = { description = it.take(MikaProtocol.MAX_STRAND_DESCRIPTION_CHARS) },
                    label = { Text(stringResource(R.string.strand_description_label)) },
                    supportingText = { Text(stringResource(R.string.strand_description_help)) },
                    minLines = 3,
                    maxLines = 8,
                    modifier = Modifier.fillMaxWidth(),
                )
                Row(
                    Modifier
                        .fillMaxWidth()
                        .heightIn(min = 48.dp)
                        .toggleable(value = archived, role = Role.Checkbox) { archived = it },
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Checkbox(checked = archived, onCheckedChange = null)
                    Text(stringResource(R.string.strand_archive_label), modifier = Modifier.padding(start = 8.dp))
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { onSave(title.trim(), description.trim(), archived) }) {
                Text(stringResource(R.string.strand_save))
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}
