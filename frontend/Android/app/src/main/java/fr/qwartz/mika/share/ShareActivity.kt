package fr.qwartz.mika.share

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.core.content.IntentCompat
import androidx.lifecycle.lifecycleScope
import fr.qwartz.mika.MainActivity
import fr.qwartz.mika.data.files.ComposerDraft
import fr.qwartz.mika.graph
import fr.qwartz.mika.ui.DeepLinks
import kotlinx.coroutines.launch

/**
 * « Partager vers Mika ». Rien à montrer (thème translucide) : les fichiers partagés sont copiés tout
 * de suite dans la préparation — le droit de les lire ne survit pas à cette activité —, le texte et
 * les fichiers sont déposés dans la boîte aux lettres de la barre de saisie, puis la conversation
 * s'ouvre. Hors session, le dépôt attend la connexion.
 */
class ShareActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (savedInstanceState != null) {
            // Recréée au milieu d'une copie : la première instance a déjà tout pris en main.
            finish()
            return
        }
        val input = ShareInput(
            action = intent.action,
            type = intent.type,
            text = intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString(),
            subject = intent.getStringExtra(Intent.EXTRA_SUBJECT),
            streams = streamsOf(intent).map(Uri::toString),
        )
        val request = ShareParser.parse(input, ownAuthorities = setOf("$packageName.files"))
        if (request == null) {
            finish()
            return
        }
        val graph = graph
        lifecycleScope.launch {
            val staged = graph.stager.stage(request.streams.map(Uri::parse), already = emptyList())
            graph.shareInbox.deposit(
                ComposerDraft(request.text.orEmpty(), staged.files, request.notices + staged.notices),
            )
            startActivity(
                Intent(this@ShareActivity, MainActivity::class.java)
                    .putExtra(DeepLinks.EXTRA_OPEN, DeepLinks.CHAT)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            )
            finish()
        }
    }

    private fun streamsOf(intent: Intent): List<Uri> {
        val out = mutableListOf<Uri>()
        when (intent.action) {
            Intent.ACTION_SEND ->
                IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java)?.let(out::add)
            Intent.ACTION_SEND_MULTIPLE ->
                IntentCompat.getParcelableArrayListExtra(intent, Intent.EXTRA_STREAM, Uri::class.java)?.let(out::addAll)
        }
        // Certaines applications ne passent leurs fichiers que par le ClipData (avec le droit de lecture).
        intent.clipData?.let { clip ->
            for (i in 0 until clip.itemCount) clip.getItemAt(i).uri?.let(out::add)
        }
        return out
    }
}
