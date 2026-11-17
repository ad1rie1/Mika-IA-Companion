package fr.qwartz.mika.ui.carte

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.carte.MiniData
import fr.qwartz.mika.data.moi.carte.MiniOpen
import fr.qwartz.mika.data.moi.carte.MiniRef
import fr.qwartz.mika.data.moi.carte.pendingMini
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.map.MiniMap
import fr.qwartz.mika.ui.map.MiniSlots
import fr.qwartz.mika.ui.map.rememberMini
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon

/*
 * Les cartes miniatures de la Carte (ADR 0196) et ce qu'elles ouvrent : la liste des voyages s'en sert ; le chat (lot 7)
 * posera [MapNoteCard] sous ses bulles, une par note de carte (`look`, `map`, `trip` : `protocole-chat.md` § 4), avec
 * les places de [MiniSlots] de son fil — ce qu'elles montrent se lit une fois pour la session ([CarteStore.minis]) :
 * un voyage changé dans la Carte se relit dans le chat quand sa miniature reparaît.
 */

/** La route qu'ouvre une miniature : le voyage, ou l'onglet de la Carte sur ce regard. */
fun MiniOpen.route(): Route = if (trip.isNotEmpty()) Route.Trip(trip) else Route.Carte(tab, look = look)

/** La hauteur d'une miniature sous une bulle (celle de `.msg-map .mm-map` du web). */
val MINI_HEIGHT: Dp = 150.dp

/**
 * La carte d'une note de carte d'un de ses messages ([kind] `look`, `map` ou `trip` ; [ref] : le `seq` du regard ou
 * l'identifiant du voyage ; [text] : le texte de la note, montré tant qu'elle se lit) : sa miniature (le plan, que la
 * vraie carte remplace quand une place est libre), son titre, ce qu'elle est ; un toucher ouvre la Carte (son voyage,
 * Itinéraire sur son trajet, ou Explorer sur ses lieux). [owner] : ce qui la porte (le message), pour que deux messages
 * qui montrent le même voyage aient chacun leur place. Plus là (oublié, supprimé) : elle le dit, estompée.
 */
@Composable
fun MapNoteCard(
    graph: AppGraph,
    slots: MiniSlots,
    owner: String,
    kind: String,
    ref: String,
    text: String,
    modifier: Modifier = Modifier,
) {
    val shell = LocalShell.current
    val store = rememberCarteStore(graph)
    val note = MiniRef(kind, ref)
    val data = rememberMini(store.minis, note, pendingMini(note, text))
    MiniCard(graph, slots, "$owner|${note.id}", data, modifier) { shell.navigate(data.opens.route()) }
}

/** Une miniature et ce qu'elle dit dessous (`miniCard` du web) ; [onOpen] : ce qu'un toucher ouvre. */
@Composable
internal fun MiniCard(graph: AppGraph, slots: MiniSlots, key: String, data: MiniData, modifier: Modifier = Modifier, onOpen: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = scheme.surfaceContainerLow,
        modifier = modifier.fillMaxWidth().alpha(if (data.gone) 0.6f else 1f),
    ) {
        Column {
            Box(Modifier.fillMaxWidth().height(MINI_HEIGHT).clip(RoundedCornerShape(topStart = 16.dp, topEnd = 16.dp))) {
                MiniMap(graph, slots, key, data, Modifier.matchParentSize())
                // la carte ne répond pas au doigt : un toucher sur elle ouvre ce qu'elle montre
                Box(Modifier.matchParentSize().clickable(role = Role.Button, onClick = onOpen))
            }
            Row(
                Modifier.fillMaxWidth().clickable(role = Role.Button, onClick = onOpen).padding(horizontal = 12.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                MIcon(R.drawable.ic_m_map, null, size = 18.dp, tint = scheme.onSurfaceVariant)
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(data.title, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    if (data.sub.isNotBlank()) Text(data.sub, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
                MIcon(R.drawable.ic_m_chev_right, null, size = 18.dp, tint = scheme.onSurfaceVariant)
            }
        }
    }
}

/** Le fond d'une miniature sans rien à montrer (un voyage sans arrêt) : l'icône de la carte, au milieu. */
@Composable
internal fun MiniBlank(modifier: Modifier) {
    Box(modifier.background(MaterialTheme.colorScheme.surfaceContainer), contentAlignment = Alignment.Center) {
        MIcon(R.drawable.ic_m_map, null, size = 28.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
