package fr.qwartz.mika.ui.components

import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.Context
import android.content.Intent
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.chat.MessageAttachment
import fr.qwartz.mika.data.files.DownloadStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/**
 * « Enregistrer » et « Ouvrir avec… » pour un fichier de Mika, avec ce qu'il faut en dire dans une
 * barre d'information. Un 401 fait vérifier la session (elle a peut-être été révoquée).
 */
class FileActions(
    private val context: Context,
    private val graph: AppGraph,
    private val scope: CoroutineScope,
    private val snackbar: SnackbarHostState,
) {
    /** L'identifiant du fichier en cours de téléchargement, pour griser ses boutons. */
    var busy by mutableStateOf<String?>(null)
        private set

    fun save(att: MessageAttachment) = run(att) {
        when (val outcome = graph.downloads.saveToDownloads(att)) {
            is DownloadStore.Outcome.Saved -> snackbar.showSnackbar(context.getString(R.string.file_saved, outcome.folder))
            is DownloadStore.Outcome.Failed -> failed(outcome)
            is DownloadStore.Outcome.Ready -> Unit
        }
    }

    fun open(att: MessageAttachment) = run(att) {
        when (val outcome = graph.downloads.prepareOpen(att)) {
            is DownloadStore.Outcome.Ready -> launchViewer(outcome)
            is DownloadStore.Outcome.Failed -> failed(outcome)
            is DownloadStore.Outcome.Saved -> Unit
        }
    }

    private fun run(att: MessageAttachment, block: suspend () -> Unit) {
        if (busy != null) return
        busy = att.id
        scope.launch {
            try {
                block()
            } finally {
                busy = null
            }
        }
    }

    private suspend fun failed(outcome: DownloadStore.Outcome.Failed) {
        if (outcome.sessionExpired) graph.scope.launch { graph.auth.checkAfterUnauthorized() }
        snackbar.showSnackbar(outcome.message)
    }

    private suspend fun launchViewer(ready: DownloadStore.Outcome.Ready) {
        val view = Intent(Intent.ACTION_VIEW)
            .setDataAndType(ready.uri, ready.mime)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        // Le ClipData porte le droit de lecture jusqu'à l'application choisie, à travers le sélecteur.
        view.clipData = ClipData.newRawUri("", ready.uri)
        val chooser = Intent.createChooser(view, context.getString(R.string.file_open_with))
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        try {
            context.startActivity(chooser)
        } catch (_: ActivityNotFoundException) {
            snackbar.showSnackbar(context.getString(R.string.file_no_app))
        }
    }
}

@Composable
fun rememberFileActions(graph: AppGraph, snackbar: SnackbarHostState): FileActions {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    return remember(graph, snackbar) { FileActions(context, graph, scope, snackbar) }
}
