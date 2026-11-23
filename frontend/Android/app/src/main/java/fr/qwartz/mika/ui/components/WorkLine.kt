package fr.qwartz.mika.ui.components

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.data.moi.Work
import fr.qwartz.mika.data.moi.elapsed
import fr.qwartz.mika.data.moi.workText
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.delay

/**
 * Où elle en est (ADR 0306), sur une seule ligne au-dessus de la saisie : [lead] (son visage dans Teams ; dans Mail, ce
 * qui précédait déjà la ligne), l'étape — coupée d'une ellipse quand son libellé est long —, puis son chrono, atténué,
 * en chiffres tabulaires, toujours visible. Le chrono court seul, chaque seconde, depuis le début de l'étape : seule sa
 * case se redessine, jamais ce qui l'entoure (le champ et ce qu'on y tape). TalkBack dit l'étape quand elle change (une
 * région « live » polie), jamais le chrono.
 */
@Composable
fun WorkLine(work: Work, modifier: Modifier = Modifier, lead: (@Composable () -> Unit)? = null) {
    Row(modifier, verticalAlignment = Alignment.CenterVertically) {
        if (lead != null) {
            lead()
            Spacer(Modifier.width(8.dp))
        }
        Text(
            workText(work),
            style = MaterialTheme.typography.bodySmall,
            color = mika.accent,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f, fill = false).semantics { liveRegion = LiveRegionMode.Polite },
        )
        Spacer(Modifier.width(8.dp))
        WorkClock(work.since)
    }
}

/** Le chrono de l'étape, depuis [since] : il se redessine seul à chaque seconde, et TalkBack ne le lit pas. */
@Composable
private fun WorkClock(since: Long) {
    val now = rememberTick(since)
    Text(
        elapsed(now - since),
        style = MaterialTheme.typography.bodySmall.copy(fontFeatureSettings = "tnum"),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        maxLines = 1,
        softWrap = false,
        modifier = Modifier.clearAndSetSemantics { },
    )
}

/** L'heure, relue à chaque seconde entière du chrono parti de [since] (« 0:07 » passe à « 0:08 » à l'heure dite). */
@Composable
private fun rememberTick(since: Long): Long {
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(since) {
        while (true) {
            now = System.currentTimeMillis()
            delay(1_000L - Math.floorMod(now - since, 1_000L))
        }
    }
    return now
}
