package fr.qwartz.mika.ui.mail

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.levelTag
import fr.qwartz.mika.data.moi.mail.INBOX
import fr.qwartz.mika.data.moi.mail.MailBox
import fr.qwartz.mika.data.moi.mail.MailFolder
import fr.qwartz.mika.data.moi.mail.MailView
import fr.qwartz.mika.data.moi.mail.allUnseen
import fr.qwartz.mika.data.moi.mail.boxTitle
import fr.qwartz.mika.data.moi.mail.commonBoxes
import fr.qwartz.mika.data.moi.mail.inboxOf
import fr.qwartz.mika.data.moi.mail.inboxView
import fr.qwartz.mika.data.moi.mail.orderedFolders
import fr.qwartz.mika.data.moi.mail.unseenOf
import fr.qwartz.mika.data.moi.mail.viewOf
import fr.qwartz.mika.data.moi.mail.waitingYours
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.ListHead
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.SheetLine

/**
 * La feuille qui monte du titre de Mail (la maquette, `A.sheets.boites`) : toutes les réceptions, tes boîtes, celles
 * qu'on te partage à leur niveau, les dossiers de la boîte choisie et leurs non-lus, ses brouillons, et « Régler les
 * boîtes ». Une boîte partagée en lecture n'entre pas dans « Toutes les réceptions » : elle s'ouvre en la nommant
 * (ADR 0200).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun MailBoxesSheet(
    boxes: List<MailBox>,
    view: MailView,
    onView: (MailView) -> Unit,
    onDrafts: () -> Unit,
    onSettings: () -> Unit,
    onDismiss: () -> Unit,
) {
    val state = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val own = boxes.filter { it.own }
    val shared = boxes.filterNot { it.own }
    // les dossiers de la boîte de la vue ; sur toutes les réceptions, ceux de ta première boîte (comme la maquette)
    val folderBox = view.boxKey?.let { key -> boxes.firstOrNull { it.key == key } } ?: own.firstOrNull() ?: boxes.firstOrNull()
    fun choose(v: MailView) {
        onView(v)
        onDismiss()
    }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = state) {
        Column(Modifier.verticalScroll(rememberScrollState()).navigationBarsPadding().padding(bottom = 12.dp)) {
            Text(
                stringResource(R.string.mail_sheet_title),
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp),
            )
            SheetLine(
                icon = R.drawable.ic_m_inbox,
                title = stringResource(R.string.mail_all_inboxes),
                subtitle = commonBoxes(boxes).joinToString(", ") { boxTitle(it, boxes) },
                count = allUnseen(boxes),
                selected = view == MailView.All,
                onClick = { choose(MailView.All) },
            )
            for (b in own) {
                SheetLine(
                    icon = R.drawable.ic_m_mail,
                    title = boxTitle(b, boxes),
                    subtitle = b.error.ifBlank { b.address },
                    count = unseenOf(b),
                    selected = isInbox(view, b),
                    onClick = { choose(inboxView(b)) },
                )
            }
            if (shared.isNotEmpty()) {
                ListHead(pluralStringResource(R.plurals.mail_sheet_shared, shared.size), muted = true)
                for (b in shared) {
                    SheetLine(
                        icon = R.drawable.ic_m_users,
                        title = boxTitle(b, boxes),
                        subtitle = listOf(b.address, levelTag(b.level)).filter { it.isNotBlank() }.joinToString(" · "),
                        count = unseenOf(b),
                        selected = isInbox(view, b),
                        onClick = { choose(inboxView(b)) },
                    )
                }
            }
            if (folderBox != null && folderBox.folders.isNotEmpty()) {
                ListHead(stringResource(R.string.mail_sheet_folders, boxTitle(folderBox, boxes)), muted = true)
                for (f in orderedFolders(folderBox)) {
                    val target = viewOf(folderBox, f)
                    val unpolled = !f.polled && f.role != "sent" && f.role != "drafts"
                    SheetLine(
                        icon = folderIcon(f.role),
                        title = f.shown,
                        subtitle = if (unpolled) stringResource(R.string.mail_folder_unpolled) else "",
                        count = if (f.role == "drafts") folderBox.draftsWaiting else f.unseen,
                        pinkCount = f.role == "drafts",
                        selected = target != null && target == view,
                        onClick = {
                            if (target == null) {
                                onDismiss()
                                onDrafts()
                            } else {
                                choose(target)
                            }
                        },
                    )
                }
            }
            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            SheetLine(
                icon = R.drawable.ic_m_pen,
                title = stringResource(R.string.mail_her_drafts),
                subtitle = stringResource(R.string.mail_her_drafts_sheet),
                count = waitingYours(boxes),
                pink = true,
                pinkCount = true,
                selected = false,
                onClick = {
                    onDismiss()
                    onDrafts()
                },
            )
            SheetLine(
                icon = R.drawable.ic_m_settings,
                title = stringResource(R.string.mail_settings_boxes),
                subtitle = stringResource(R.string.mail_settings_boxes_where),
                count = 0,
                selected = false,
                onClick = {
                    onDismiss()
                    onSettings()
                },
            )
        }
    }
}

private fun isInbox(view: MailView, box: MailBox): Boolean =
    view is MailView.Folder && view.box == box.key && view.folder == (inboxOf(box)?.name ?: INBOX)

/** Choisir le dossier où ranger des mails d'une boîte (« Déplacer », ADR 0200). */
@Composable
internal fun FolderPicker(box: MailBox, folders: List<MailFolder>, onPick: (MailFolder) -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.mail_move_title)) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Text(boxTitle(box), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Gap(8.dp)
                if (folders.isEmpty()) Text(stringResource(R.string.mail_move_none))
                for (f in folders) {
                    Row(
                        Modifier.fillMaxWidth().clickable { onPick(f) }.padding(vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        MIcon(folderIcon(f.role), null, size = 20.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                        Spacer(Modifier.width(14.dp))
                        Text(f.shown, style = MaterialTheme.typography.bodyLarge)
                    }
                }
            }
        },
        confirmButton = {},
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}
