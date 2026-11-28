package fr.qwartz.mika.ui.mail

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.graphics.Color as AndroidColor
import android.view.View
import android.view.ViewGroup
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.mail.MailFramePage
import fr.qwartz.mika.data.moi.mail.MailFull
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.shell.toneColors
import kotlin.math.roundToInt

/** Le HTML d'un mail, prêt pour sa WebView ([MailFramePage.of]) : de quel mail, et si ses images distantes s'y
 *  chargent. */
data class MailHtml(val ref: String, val page: String, val remote: Boolean)

/** Ce que la liseuse fait des images distantes d'un mail HTML (`images` du mail, ADR 0175). */
enum class ImagesGesture { ONCE, ALWAYS, NEVER }

/** Ce que la liseuse passe au corps d'un mail HTML ([MailHtmlBody]). */
internal class ReaderHtml(
    val frame: Load<MailHtml>?,
    val imagesOnce: Boolean,
    val always: Boolean,
    val busy: Boolean,
    val onImages: (ImagesGesture) -> Unit,
    val onRetry: () -> Unit,
)

/**
 * Le corps d'un mail HTML, comme le client web (`frontend/Web`, `readerMail`) : le bandeau de ses images distantes
 * masquées (les afficher cette fois ; toujours pour cet expéditeur, seulement une propriétaire qui écrit dans la
 * boîte), puis sa mise en page dans son cadre. Un cadre qui ne se charge pas rend son texte, s'il en a un.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun MailHtmlBody(
    m: MailFull,
    frame: Load<MailHtml>?,
    imagesOnce: Boolean,
    always: Boolean,
    busy: Boolean,
    onImages: (ImagesGesture) -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val scheme = MaterialTheme.colorScheme
    Column(modifier.padding(horizontal = 16.dp)) {
        val masked = m.images.remote && !m.images.shown && !imagesOnce
        if (masked) {
            val (bg, fg) = toneColors(Tone.WARN)
            Surface(shape = RoundedCornerShape(12.dp), color = bg, modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(start = 12.dp, end = 12.dp, top = 10.dp, bottom = 4.dp)) {
                    Row {
                        MIcon(R.drawable.ic_m_image, null, size = 20.dp, tint = fg)
                        Spacer(Modifier.width(10.dp))
                        Text(stringResource(R.string.mail_images_masked), style = MaterialTheme.typography.bodyMedium, color = fg)
                    }
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        TextButton(onClick = { onImages(ImagesGesture.ONCE) }) { Text(stringResource(R.string.mail_images_once)) }
                        if (always) {
                            TextButton(onClick = { onImages(ImagesGesture.ALWAYS) }, enabled = !busy) {
                                Text(stringResource(R.string.mail_images_always))
                            }
                        }
                    }
                }
            }
            Gap(8.dp)
        } else if (m.images.shown && always) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                MIcon(R.drawable.ic_m_image, null, size = 16.dp, tint = scheme.onSurfaceVariant)
                Spacer(Modifier.width(6.dp))
                Text(stringResource(R.string.mail_images_on), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, modifier = Modifier.weight(1f))
                TextButton(onClick = { onImages(ImagesGesture.NEVER) }, enabled = !busy) {
                    Text(stringResource(R.string.mail_images_never), style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        // un renderer de WebView perdu (mémoire) rend le texte, comme un cadre qui ne s'est pas chargé
        var gone by remember(frame) { mutableStateOf(false) }
        val ready = (frame as? Load.Ready)?.value?.takeIf { it.ref == m.ref && !gone }
        when {
            ready != null -> Surface(
                shape = RoundedCornerShape(12.dp),
                // la page blanche d'une messagerie, comme le cadre du web (`.rd-frame`) : ses couleurs sont les siennes
                color = Color.White,
                border = BorderStroke(1.dp, scheme.outlineVariant),
                modifier = Modifier.fillMaxWidth(),
            ) {
                MailFrame(ready, onGone = { gone = true }, modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 10.dp))
            }
            frame == null || frame is Load.Loading -> Box(Modifier.fillMaxWidth().height(120.dp), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            else -> {
                val why = (frame as? Load.Failed)?.error?.message
                NoteBox(
                    listOfNotNull(stringResource(if (m.body.isNotBlank()) R.string.mail_frame_failed_text else R.string.mail_frame_failed), why).joinToString(" "),
                    R.drawable.ic_m_info,
                )
                OutlinedButton(onClick = onRetry, modifier = Modifier.padding(top = 6.dp)) { Text(stringResource(R.string.retry)) }
                if (m.body.isNotBlank()) {
                    Gap(6.dp)
                    MailBodyText(m.body, Modifier.padding(vertical = 6.dp))
                }
            }
        }
    }
}

/**
 * La WebView d'un mail (ADR 0242) : aucun script, aucun accès aux fichiers, aucun chargement du réseau sauf ses images
 * distantes quand elles sont permises (et sa politique le redit, [MailFramePage]) ; elle ne navigue jamais, un lien
 * touché s'ouvre dehors. Elle prend la hauteur de son contenu (`WRAP_CONTENT`) : c'est la liseuse qui défile. Un mail
 * plus large que l'écran s'y réduit, et se zoome à deux doigts.
 */
@Composable
private fun MailFrame(html: MailHtml, onGone: () -> Unit, modifier: Modifier = Modifier) {
    val textZoom = (LocalDensity.current.fontScale * 100).roundToInt()
    AndroidView(
        factory = { ctx ->
            try {
                WebView(ctx).apply {
                    layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                    setBackgroundColor(AndroidColor.WHITE)
                    isVerticalScrollBarEnabled = false
                    settings.lockDown()
                    webViewClient = Outside(ctx, onGone)
                }
            } catch (_: RuntimeException) {
                // pas de WebView sur l'appareil (en cours de mise à jour, désactivée) : le texte, à la place — dit
                // après la composition, pas pendant
                View(ctx).also { it.post(onGone) }
            }
        },
        update = { view ->
            if (view !is WebView) return@AndroidView
            view.settings.textZoom = textZoom
            if (view.tag !== html) {
                view.tag = html
                view.settings.blockNetworkImage = !html.remote
                view.settings.blockNetworkLoads = !html.remote
                view.loadDataWithBaseURL(null, html.page, "text/html", "utf-8", null)
            }
        },
        onRelease = { view ->
            if (view is WebView) {
                view.stopLoading()
                view.destroy()
            }
        },
        modifier = modifier,
    )
}

/** Ce que la WebView permet : afficher, rien d'autre. */
private fun WebSettings.lockDown() {
    javaScriptEnabled = false
    javaScriptCanOpenWindowsAutomatically = false
    allowFileAccess = false
    allowContentAccess = false
    domStorageEnabled = false
    setGeolocationEnabled(false)
    setSupportMultipleWindows(false)
    mediaPlaybackRequiresUserGesture = true
    blockNetworkImage = true
    blockNetworkLoads = true
    loadsImagesAutomatically = true
    // la largeur de l'écran pour mise en page (son `<meta viewport>`), réduite si le mail est plus large
    useWideViewPort = true
    loadWithOverviewMode = true
    setSupportZoom(true)
    builtInZoomControls = true
    displayZoomControls = false
}

/** Un lien touché s'ouvre dehors, s'il est web ou `mailto:` ; la WebView, elle, ne navigue jamais. */
private class Outside(private val context: Context, private val onGone: () -> Unit) : WebViewClient() {
    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
        val url = request.url
        if (MailFramePage.opensOutside(url.toString())) {
            val intent = if (url.scheme.equals("mailto", ignoreCase = true)) {
                Intent(Intent.ACTION_SENDTO, url)
            } else {
                Intent(Intent.ACTION_VIEW, url).addCategory(Intent.CATEGORY_BROWSABLE)
            }
            try {
                context.startActivity(intent)
            } catch (_: ActivityNotFoundException) {
                // rien pour l'ouvrir : le lien reste où il est
            }
        }
        return true
    }

    /** Son renderer perdu ne fait pas tomber l'application : la liseuse rend le texte. */
    override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
        onGone()
        return true
    }
}
