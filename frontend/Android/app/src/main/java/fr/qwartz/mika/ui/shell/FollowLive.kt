package fr.qwartz.mika.ui.shell

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import fr.qwartz.mika.data.moi.Live
import fr.qwartz.mika.data.moi.LiveSignal

/**
 * Un écran face au direct (ADR 0308, `protocole-moi.md` § 2 bis) : tant qu'il est montré — en haut de la pile, l'app
 * au premier plan —, il suit [topics] ; chaque signal qui les touche passe à [onSignal], un à la fois (ce qui arrive
 * pendant une lecture se réunit pour la suivante : [onSignal] attend la fin de ce qu'il relit). Chaque fois qu'il le
 * redevient, [onShown] relit ce qu'il montre — rien de ce qui a changé pendant son absence ne se perd : un écran au
 * second plan ne suit rien, il se relit à son retour. [onShown] reçoit `true` la première fois dans cette composition
 * (l'écran qui lit déjà à son ouverture n'a alors rien à faire) — sauf si la connexion s'est ouverte entre sa
 * composition (sa première lecture) et cet abonnement : il n'a pas reçu la relecture de cette ouverture (ADR 0308,
 * [Live.opens]), il relit comme à un retour (`false`).
 *
 * Abonné avant de relire : ce qui change à partir de la relecture ne lui échappe pas. [keys] : ce qui fait repartir le
 * suivi (le modèle, ce qui est ouvert).
 */
@Composable
fun FollowLive(
    live: Live,
    topics: Set<String>,
    vararg keys: Any?,
    onShown: (first: Boolean) -> Unit = {},
    onSignal: suspend (LiveSignal) -> Unit,
) {
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val shown by rememberUpdatedState(onShown)
    val signal by rememberUpdatedState(onSignal)
    // les ouvertures de la connexion quand l'écran (et sa première lecture) est composé
    val composedAt = remember(live, *keys) { live.opens }
    LaunchedEffect(live, lifecycle, topics, *keys) {
        var first = true
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            live.follow(topics, ready = {
                shown(firstShown(first, composedAt, live.opens))
                first = false
            }) { signal(it) }
        }
    }
}

/**
 * Le premier abonnement d'un écran est-il « la première fois » ([FollowLive], `onShown`) ? Oui, sauf si la connexion
 * s'est ouverte depuis sa composition : sa première lecture a précédé cette ouverture, dont la relecture
 * ([LiveSignal.RESYNC]) ne l'a pas trouvé abonné — il relit comme à un retour. Pur.
 */
internal fun firstShown(first: Boolean, composedAt: Long, opensNow: Long): Boolean = first && opensNow == composedAt
