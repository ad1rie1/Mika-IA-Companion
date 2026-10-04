package fr.qwartz.mika.ui.chat

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import fr.qwartz.mika.R
import fr.qwartz.mika.data.files.AttachmentPolicy
import fr.qwartz.mika.data.files.StagedFile
import fr.qwartz.mika.data.net.MikaProtocol
import java.io.File
import java.text.NumberFormat
import java.util.Locale

/**
 * La barre de saisie : ce qu'il faut dire des fichiers (refus, réductions), les puces des pièces
 * jointes avec « ✕ », le compteur à l'approche de la limite, le champ (Entrée = retour à la ligne)
 * et l'envoi.
 */
@Composable
internal fun Composer(
    input: String,
    onInput: (String) -> Unit,
    attachments: List<StagedFile>,
    notices: List<String>,
    staging: Boolean,
    canSend: Boolean,
    onRemove: (StagedFile) -> Unit,
    onAttach: () -> Unit,
    onSend: () -> Unit,
) {
    val count = input.length
    val format = remember { NumberFormat.getIntegerInstance(Locale.FRANCE) }
    Surface(tonalElevation = 2.dp) {
        Column(
            Modifier.fillMaxWidth().navigationBarsPadding().imePadding().padding(horizontal = 8.dp, vertical = 6.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            for (notice in notices) {
                Text(
                    notice,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 8.dp).semantics { liveRegion = LiveRegionMode.Polite },
                )
            }
            if (attachments.isNotEmpty() || staging) {
                LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(horizontal = 4.dp)) {
                    items(attachments, key = { it.path }) { file -> StagedChip(file, onRemove) }
                    if (staging) {
                        item(key = "staging") {
                            CircularProgressIndicator(Modifier.padding(12.dp).size(24.dp), strokeWidth = 2.dp)
                        }
                    }
                }
            }
            if (count >= MikaProtocol.COUNTER_FROM) {
                val atLimit = count >= MikaProtocol.MAX_MESSAGE_CHARS
                Text(
                    stringResource(
                        if (atLimit) R.string.chat_counter_limit else R.string.chat_counter,
                        format.format(count),
                        format.format(MikaProtocol.MAX_MESSAGE_CHARS),
                    ),
                    style = MaterialTheme.typography.bodySmall,
                    color = if (atLimit) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier
                        .padding(horizontal = 8.dp)
                        .then(if (atLimit) Modifier.semantics { liveRegion = LiveRegionMode.Polite } else Modifier),
                )
            }
            Row(verticalAlignment = Alignment.Bottom) {
                IconButton(onClick = onAttach, enabled = !staging && attachments.size < MikaProtocol.MAX_ATTACHMENTS) {
                    Icon(painterResource(R.drawable.ic_attach_file), stringResource(R.string.chat_attach))
                }
                OutlinedTextField(
                    value = input,
                    onValueChange = onInput,
                    placeholder = { Text(stringResource(R.string.chat_input_hint)) },
                    maxLines = 6,
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
                    modifier = Modifier.weight(1f),
                )
                IconButton(onClick = onSend, enabled = canSend) {
                    Icon(painterResource(R.drawable.ic_send), stringResource(R.string.chat_send))
                }
            }
        }
    }
}

@Composable
private fun StagedChip(file: StagedFile, onRemove: (StagedFile) -> Unit) {
    val image = file.mime.startsWith("image/")
    Surface(shape = RoundedCornerShape(12.dp), color = MaterialTheme.colorScheme.surfaceVariant) {
        Row(Modifier.heightIn(min = 48.dp).padding(start = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            if (image) {
                AsyncImage(
                    model = File(file.path),
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.size(36.dp).clip(RoundedCornerShape(6.dp)),
                )
            } else {
                Icon(painterResource(R.drawable.ic_description), contentDescription = null, modifier = Modifier.size(24.dp))
            }
            Column(Modifier.padding(start = 8.dp).widthIn(max = 140.dp)) {
                Text(file.name, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall)
                Text(AttachmentPolicy.humanSize(file.size), style = MaterialTheme.typography.labelSmall)
            }
            IconButton(onClick = { onRemove(file) }) {
                Icon(painterResource(R.drawable.ic_close), stringResource(R.string.chat_remove_file, file.name))
            }
        }
    }
}

/** La feuille « Joindre » : Photos, Appareil photo (s'il y en a un), Fichier. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun AttachSheet(
    cameraAvailable: Boolean,
    onDismiss: () -> Unit,
    onPhotos: () -> Unit,
    onCamera: () -> Unit,
    onDocuments: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(Modifier.navigationBarsPadding().padding(bottom = 16.dp)) {
            SheetEntry(R.drawable.ic_image, R.string.attach_photos, onPhotos)
            if (cameraAvailable) SheetEntry(R.drawable.ic_photo_camera, R.string.attach_camera, onCamera)
            SheetEntry(R.drawable.ic_description, R.string.attach_file, onDocuments)
        }
    }
}

@Composable
private fun SheetEntry(icon: Int, label: Int, onClick: () -> Unit) {
    Surface(onClick = onClick) {
        ListItem(
            headlineContent = { Text(stringResource(label)) },
            leadingContent = { Icon(painterResource(icon), contentDescription = null) },
        )
    }
}
