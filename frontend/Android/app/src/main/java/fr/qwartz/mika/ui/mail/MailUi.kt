package fr.qwartz.mika.ui.mail

import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.Context
import android.content.Intent
import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.files.DownloadStore
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.mail.MailApi
import fr.qwartz.mika.data.moi.mail.MailPiece
import fr.qwartz.mika.data.moi.mail.Triage
import fr.qwartz.mika.data.moi.mail.bodyBlocks
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.linked
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

/*
 * Ce que les écrans de Mail partagent (ADR 0235) : l'API, ce qu'un écran dit aux autres d'un geste, les petites formes
 * de la maquette (`maquette/ecrans/mail.js`) qui ne servent qu'à Mail — le point du non-lu, l'icône d'un dossier, le
 * texte d'un mail, ses pièces. Celles que Teams partage sont dans `ui/shell/Parts.kt`.
 */

/** Mail sur l'API du téléphone ; ses envois avec des pièces par le client sans délai global (un fichier lourd sur
 *  une 4G faible). Le jeton n'y part que vers son serveur, comme partout. */
internal fun AppGraph.mailApi(): MailApi =
    MailApi(moi, MoiApi(filesHttp, { auth.credentials() }, { auth.checkAfterUnauthorized() }))

/**
 * Ce qu'un écran de Mail dit aux autres d'un geste, pour qu'ils se mettent à jour sans tout relire : la liste efface
 * un mail rangé depuis la liseuse, relit ses brouillons après une décision. Rien n'y est gardé : des faits, pas des
 * données.
 */
internal object MailChanges {
    sealed interface Change {
        /** Un geste de « ranger » sur ces mails (`read`, `unread`, `flag`, `unflag`, `archive`, `trash`, `move`). */
        data class Tidied(val refs: List<String>, val gesture: String) : Change
        /** Ses brouillons ont changé (une décision, une réponse partie, une demande). */
        data object Drafts : Change
    }

    private val changes = MutableSharedFlow<Change>(extraBufferCapacity = 32)
    val flow: SharedFlow<Change> = changes.asSharedFlow()

    fun tell(change: Change) {
        changes.tryEmit(change)
    }
}

/**
 * Le sort d'un geste de Mail à dire où qu'on soit : un envoi qui finit après qu'on a quitté « Écrire » (←, une
 * notification touchée) se dit quand même. Le cadre de la session le montre en toast ; ce que personne n'a encore lu
 * (une rotation) attend, et tout s'efface à la déconnexion : le compte suivant n'en hérite pas.
 */
class MailNotices {
    private val channel = Channel<String>(Channel.BUFFERED)
    val flow: Flow<String> = channel.receiveAsFlow()

    fun say(text: String) {
        if (text.isNotBlank()) channel.trySend(text)
    }

    fun clear() {
        while (channel.tryReceive().isSuccess) Unit
    }
}

/**
 * Ce qu'un modèle de session demande à l'écran qu'il sert (revenir, ouvrir un brouillon) : chaque ordre porte la
 * visite où son geste a commencé, et seul l'écran de cette visite le suit. Un geste qui répond après qu'on a quitté
 * son écran ne referme ni n'emmène l'écran ouvert ensuite, même sur le même mail ; une visite nouvelle jette ce qui
 * attendait pour l'ancienne. Une rotation garde sa visite : l'ordre arrivé entre-temps la suit encore.
 */
internal class VisitOrders<T> {
    private val channel = Channel<Pair<String, T>>(Channel.BUFFERED)

    /** La visite de l'écran servi. */
    var visit: String = ""
        private set

    /** Un écran s'ouvre ; le même revenu (une rotation) ne perd rien. */
    fun open(visit: String) {
        if (visit == this.visit) return
        this.visit = visit
        while (channel.tryReceive().isSuccess) Unit
    }

    /** [from] : la visite où le geste a commencé ; un autre écran ouvert depuis, l'ordre ne vaut plus. */
    fun send(from: String, order: T) {
        if (from.isNotEmpty() && from == visit) channel.trySend(from to order)
    }

    /** Ce que l'écran de [visit] doit suivre. */
    fun of(visit: String): Flow<T> = channel.receiveAsFlow().filter { it.first == visit }.map { it.second }
}

/** Le point indigo de ton non-lu. */
@Composable
internal fun UnreadDot() {
    Box(Modifier.size(8.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primary))
}

/** Où en est son tri, en mots : la marque d'une ligne, et le titre du cadre « Ce qu'elle en sait ». */
@StringRes
internal fun triageLabel(t: Triage): Int = when (t) {
    Triage.READ -> R.string.mail_triage_read
    Triage.WAITING -> R.string.mail_triage_waiting
    Triage.GUESSED -> R.string.mail_triage_guessed
    Triage.BULK -> R.string.mail_triage_bulk
}

/** Ce que le cadre « Ce qu'elle en sait » en dit de plus ([triageNote] : pas encore lu, ou deviné). */
@StringRes
internal fun triageNoteText(t: Triage): Int = when (t) {
    Triage.WAITING -> R.string.mail_triage_waiting_note
    else -> R.string.mail_triage_guessed_note
}

/** L'icône de la marque de son tri : l'œil quand il l'a lu. */
@DrawableRes
internal fun triageIcon(t: Triage): Int = when (t) {
    Triage.READ -> R.drawable.ic_m_eye
    Triage.WAITING -> R.drawable.ic_m_clock
    else -> R.drawable.ic_m_alert
}

/** La marque discrète de son tri, sur une ligne (sans fond, en gris : presque toutes en ont une). */
@Composable
internal fun TriageMark(t: Triage) {
    val tint = MaterialTheme.colorScheme.onSurfaceVariant
    Row(verticalAlignment = Alignment.CenterVertically) {
        MIcon(triageIcon(t), null, size = 13.dp, tint = tint)
        Spacer(Modifier.width(3.dp))
        Text(stringResource(triageLabel(t)), color = tint, style = MaterialTheme.typography.labelSmall, maxLines = 1)
    }
}

/** L'icône d'un dossier, d'après son rôle. */
@DrawableRes
internal fun folderIcon(role: String): Int = when (role) {
    "inbox" -> R.drawable.ic_m_inbox
    "sent" -> R.drawable.ic_m_send
    "drafts" -> R.drawable.ic_m_file
    "archive" -> R.drawable.ic_m_archive
    "junk" -> R.drawable.ic_m_alert
    "trash" -> R.drawable.ic_m_trash
    else -> R.drawable.ic_m_folder
}

// ── Le texte ────────────────────────────────────────────────────────────

/** Le texte d'un mail : ses paragraphes, et ce qu'il cite en retrait, d'un filet à gauche par niveau. */
@Composable
internal fun MailBodyText(body: String, modifier: Modifier = Modifier) {
    val blocks = remember(body) { bodyBlocks(body) }
    val link = MaterialTheme.colorScheme.primary
    val line = MaterialTheme.colorScheme.outlineVariant
    Column(modifier, verticalArrangement = Arrangement.spacedBy(12.dp)) {
        for (b in blocks) {
            val text = remember(b, link) { linked(b.text, link) }
            if (b.depth == 0) {
                Text(text, style = MaterialTheme.typography.bodyLarge.copy(lineHeight = 23.sp))
            } else {
                Text(
                    text,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier
                        .padding(start = ((b.depth - 1) * 8).dp)
                        .drawBehind { drawRect(line, size = Size(3.dp.toPx(), size.height)) }
                        .padding(start = 12.dp),
                )
            }
        }
    }
}

/** Une ligne de lecture seule à deux colonnes (« De », « À »…), comme l'en-tête de ce qui partira. */
@Composable
internal fun HeadLine(label: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.width(56.dp))
        Text(value, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f), maxLines = 3, overflow = TextOverflow.Ellipsis)
    }
}

// ── Les pièces reçues ───────────────────────────────────────────────────

/**
 * « Enregistrer » (Téléchargements/Mika) et « Ouvrir avec… » pour une pièce d'un mail : téléchargée avec le jeton,
 * seulement depuis le serveur de la session (`DownloadStore`). Le sort se dit par [say].
 */
internal class MailFiles(private val context: Context, private val graph: AppGraph, private val say: (String) -> Unit) {
    private val api = graph.mailApi()

    private fun served(ref: String, p: MailPiece): DownloadStore.ServedFile? {
        val url = api.fileUrl(ref, p.part) ?: return null
        return DownloadStore.ServedFile(url, p.name, p.mime.ifBlank { null }, "$ref|${p.part}")
    }

    suspend fun save(ref: String, p: MailPiece) {
        val file = served(ref, p) ?: return say(context.getString(R.string.mail_signed_out))
        when (val got = graph.downloads.saveToDownloads(file)) {
            is DownloadStore.Outcome.Saved -> say(context.getString(R.string.file_saved, got.folder))
            is DownloadStore.Outcome.Failed -> failed(got)
            is DownloadStore.Outcome.Ready -> Unit
        }
    }

    suspend fun open(ref: String, p: MailPiece) {
        val file = served(ref, p) ?: return say(context.getString(R.string.mail_signed_out))
        when (val got = graph.downloads.prepareOpen(file)) {
            is DownloadStore.Outcome.Ready -> {
                val view = Intent(Intent.ACTION_VIEW).setDataAndType(got.uri, got.mime).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                view.clipData = ClipData.newRawUri("", got.uri)
                val chooser = Intent.createChooser(view, context.getString(R.string.file_open_with))
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                try {
                    context.startActivity(chooser)
                } catch (_: ActivityNotFoundException) {
                    say(context.getString(R.string.file_no_app))
                }
            }
            is DownloadStore.Outcome.Failed -> failed(got)
            is DownloadStore.Outcome.Saved -> Unit
        }
    }

    private fun failed(got: DownloadStore.Outcome.Failed) {
        if (got.sessionExpired) graph.refreshSession()
        say(got.message)
    }
}

private fun AppGraph.refreshSession() {
    scope.launch { auth.checkAfterUnauthorized() }
}
