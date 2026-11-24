package fr.qwartz.mika.ui.shell

import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.CorrectTurn
import fr.qwartz.mika.data.moi.CorrectWords
import fr.qwartz.mika.data.moi.Corrected
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.correctTurn
import fr.qwartz.mika.data.moi.correctedText
import fr.qwartz.mika.data.moi.undoCorrection
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

/*
 * « Corriger » (ADR 0307), dans le champ de Mail et de Teams — une petite forme qu'ils partagent : les fautes de ce que
 * tu écris, sans changer tes mots (ses règles pures : `data/moi/Correct.kt`). Porté de
 * `frontendv2/src/screens/mail/compose.ts` (`correctField`) : le texte corrigé remplace le tien aussitôt, et le message
 * offre « Annuler » ; rien n'est posé si tu as continué d'écrire. Sans modèle au rôle `correct`, le bouton reste
 * atténué et dit pourquoi quand on le touche (comme ✦ « Préremplir » dans Teams).
 */

/** Ce que « Corriger » dit de son issue ; [undo] : « Annuler », quand ton texte a été remplacé. */
class CorrectNotice(val text: String, val undo: (() -> Unit)? = null)

/**
 * « Corriger » pour les champs d'un écran (son modèle le tient, [scope] : le sien). Un appel à la fois par champ
 * ([busy] : son bouton s'éteint et dit « Correction… ») ; un champ que l'écran a quitté (une autre discussion, une
 * autre écriture) ne retient pas celui qui s'ouvre. Ce qu'il dit passe par [notices], une fois chacun.
 */
class FieldCorrector(private val scope: CoroutineScope, private val call: suspend (String) -> MoiApi.Result<Corrected>) {
    /** Les champs en cours de correction (leur clé : une discussion, une écriture). */
    private var running by mutableStateOf<Set<Any>>(emptySet())
    private val channel = Channel<CorrectNotice>(Channel.BUFFERED)

    /** Ce que « Corriger » dit, une fois chacun : l'écran le montre (« Annuler » quand il y en a un). */
    val notices: Flow<CorrectNotice> = channel.receiveAsFlow()

    /** Le champ [key] est en cours de correction. */
    fun busy(key: Any): Boolean = key in running

    /**
     * Corriger le champ [key]. [read] rend son texte tel qu'il est au moment de le lire — `null` : il n'est plus à
     * l'écran (une autre discussion, une autre écriture), rien ne s'y pose ; [write] le remplace. [on] : un modèle
     * corrige (`GET /api/moi` → `correct`) ; sinon, on dit pourquoi. Un champ vide ne part pas. La réponse venue, le
     * champ a changé (tu as continué d'écrire) : rien n'est posé ; rien à corriger (ou rien qui ne touchait pas aux
     * mots) : ton texte reste ; sinon le texte corrigé le remplace, et « Annuler » te le rend tant que le champ
     * contient encore le texte corrigé. Le message dit aussi ce qui a été écarté parce que ça touchait aux mots. Un
     * refus se dit tel que le serveur le donne.
     */
    fun correct(key: Any, on: Boolean, words: CorrectWords, read: () -> String?, write: (String) -> Unit) {
        if (key in running) return
        if (!on) return tell(words.off)
        val before = read() ?: return
        if (before.isBlank()) return tell(words.empty)
        running = running + key
        scope.launch {
            val got = try {
                call(before)
            } finally {
                running = running - key
            }
            when (got) {
                is MoiApi.Result.Failed -> tell(got.error.said)
                is MoiApi.Result.Ok -> {
                    val now = read() ?: return@launch
                    val c = got.value
                    when (correctTurn(before, now, c)) {
                        CorrectTurn.MOVED -> tell(words.moved)
                        CorrectTurn.NONE -> tell(correctedText(0, c.refused, words))
                        CorrectTurn.PUT -> {
                            val fixed = c.text
                            write(fixed)
                            tell(correctedText(c.changes, c.refused, words)) {
                                read()?.let { undoCorrection(it, fixed, before) }?.let(write)
                            }
                        }
                    }
                }
            }
        }
    }

    private fun tell(text: String, undo: (() -> Unit)? = null) {
        if (text.isNotBlank()) channel.trySend(CorrectNotice(text, undo))
    }
}

/** Les mots de « Corriger », tirés de `strings.xml` ; le nombre de fautes au pluriel de `correct_done` (ou de
 *  `correct_done_part`, suivi des changements écartés : `correct_dropped`). */
@Composable
fun rememberCorrectWords(): CorrectWords {
    val res = LocalResources.current
    val empty = stringResource(R.string.correct_empty)
    val none = stringResource(R.string.correct_none)
    val untouched = stringResource(R.string.correct_untouched)
    val moved = stringResource(R.string.correct_moved)
    val off = stringResource(R.string.correct_off)
    return remember(res, empty, none, untouched, moved, off) {
        CorrectWords(
            empty = empty,
            none = none,
            untouched = untouched,
            moved = moved,
            off = off,
            fixed = { n -> res.getQuantityString(R.plurals.correct_done, n, n) },
            fixedDropped = { n, r -> res.getQuantityString(R.plurals.correct_dropped, r, res.getQuantityString(R.plurals.correct_done_part, n, n), r) },
        )
    }
}

/** Ce que [corrector] dit, en message au bas de l'écran ; « Annuler » quand ton texte a été remplacé. */
@Composable
fun CorrectNotices(corrector: FieldCorrector) {
    val shell = LocalShell.current
    val undo = stringResource(R.string.correct_undo)
    LaunchedEffect(corrector, shell, undo) {
        corrector.notices.collect { n ->
            val then = n.undo
            if (then == null) shell.toast(n.text) else shell.offer(n.text, undo, then)
        }
    }
}

/**
 * « Corriger », un bouton à mots, discret comme sur le web (Mail, à côté de « Préremplir avec Mika ») : pendant l'appel,
 * éteint, il dit « Correction… » ; sans modèle ([on] faux), atténué, il dit pourquoi quand on le touche. [enabled] :
 * faux le temps d'un envoi.
 */
@Composable
fun CorrectButton(on: Boolean, busy: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) {
    TextButton(
        onClick = onClick,
        enabled = enabled && !busy,
        colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.onSurface),
        modifier = modifier.alpha(if (on) 1f else OFF_ALPHA),
    ) {
        MIcon(R.drawable.ic_m_check, null, size = 18.dp)
        Spacer(Modifier.width(6.dp))
        Text(stringResource(if (busy) R.string.correct_busy else R.string.correct), maxLines = 1)
    }
}

/**
 * « Corriger », en icône (le champ de Teams, à côté de ✦ « Préremplir ») : pendant l'appel, éteint, il tourne et se
 * dit « Correction… » ; sans modèle ([on] faux), atténué, il dit pourquoi quand on le touche.
 */
@Composable
fun CorrectIconButton(on: Boolean, busy: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier) {
    IconButton(onClick = onClick, enabled = !busy, modifier = modifier.alpha(if (on) 1f else OFF_ALPHA)) {
        if (busy) {
            val busyText = stringResource(R.string.correct_busy)
            CircularProgressIndicator(
                Modifier.size(18.dp).semantics { contentDescription = busyText },
                strokeWidth = 2.dp,
                color = mika.accent,
            )
        } else {
            MIcon(R.drawable.ic_m_check, stringResource(R.string.correct), tint = mika.accent)
        }
    }
}

/** Un bouton qui ne sert pas ici, mais dit pourquoi quand on le touche (✦ « Préremplir » dans Teams). */
private const val OFF_ALPHA = 0.45f
