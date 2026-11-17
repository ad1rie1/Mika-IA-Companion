package fr.qwartz.mika.ui.carte

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.carte.MiniData
import fr.qwartz.mika.data.moi.carte.MiniOpen
import fr.qwartz.mika.data.moi.carte.MiniRef
import fr.qwartz.mika.data.moi.carte.TripSummary
import fr.qwartz.mika.data.moi.carte.plural
import fr.qwartz.mika.data.moi.carte.tripDates
import fr.qwartz.mika.data.moi.carte.tripPast
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.map.MiniMap
import fr.qwartz.mika.ui.map.MiniSlots
import fr.qwartz.mika.ui.map.rememberMini
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.Notice
import fr.qwartz.mika.ui.shell.Tag

/** La hauteur de la miniature d'un voyage dans la liste (la maquette : 130 dp). */
private val CARD_MAP = 130.dp

/**
 * Voyages (la maquette, `vueVoyages`) : tes voyages en cartes, le plus récemment changé d'abord — leur miniature (ses
 * arrêts reliés ; la vraie carte quand une des quatre places est libre, sinon le plan), leur titre, leurs dates, leurs
 * jours et arrêts, « préparé avec Mika », « passé » ; « Nouveau voyage » en bouton flottant (posé par l'écran). Une
 * miniature se relit quand la liste dit son voyage changé depuis (par elle dans le chat, ailleurs).
 */
@Composable
internal fun TripsTab(graph: AppGraph, store: CarteStore, modifier: Modifier) {
    val shell = LocalShell.current
    val slots = remember { MiniSlots() }
    val now = graph.clock.wallMs()
    LoadBox(store.list, onRetry = store::retryList, modifier = modifier) { trips ->
        if (trips.isEmpty()) {
            Notice(stringResource(R.string.carte_trips_empty), modifier)
        } else {
            LazyColumn(
                Modifier.fillMaxWidth(),
                contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 96.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                items(trips, key = { it.id }) { t -> TripCard(graph, store, slots, t, now) { shell.navigate(Route.Trip(t.id)) } }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun TripCard(graph: AppGraph, store: CarteStore, slots: MiniSlots, t: TripSummary, now: Long, onOpen: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    val past = tripPast(t.start, t.days, now)
    val fallback = MiniData(t.title, "", MiniOpen(trip = t.id))
    val data = rememberMini(store.minis, MiniRef.trip(t.id), fallback, version = t.updated)
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = scheme.surfaceContainerLow,
        modifier = Modifier.fillMaxWidth().alpha(if (past) 0.75f else 1f),
    ) {
        Column {
            Box(Modifier.fillMaxWidth().height(CARD_MAP).clip(RoundedCornerShape(topStart = 16.dp, topEnd = 16.dp))) {
                if (t.stops == 0) MiniBlank(Modifier.matchParentSize())
                else MiniMap(graph, slots, "voyages|trip:${t.id}", data, Modifier.matchParentSize())
                // la carte ne répond pas au doigt : un toucher sur elle ouvre le voyage
                Box(Modifier.matchParentSize().clickable(role = Role.Button, onClick = onOpen))
            }
            Column(Modifier.fillMaxWidth().clickable(role = Role.Button, onClick = onOpen).padding(horizontal = 14.dp, vertical = 10.dp)) {
                Text(t.title.ifBlank { stringResource(R.string.carte_untitled) }, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                val dates = tripDates(t.start, t.days, now).removeSuffix(" · passé").ifBlank { stringResource(R.string.carte_no_date) }
                Text(
                    listOf(dates, plural(t.days.toLong(), "jour"), plural(t.stops.toLong(), "arrêt")).joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall,
                    color = scheme.onSurfaceVariant,
                )
                if (t.mika || past) {
                    FlowRow(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        if (t.mika) Tag(stringResource(R.string.carte_trip_with_mika), Tone.MIKA, R.drawable.ic_m_sparkle)
                        if (past) Tag(stringResource(R.string.carte_trip_past), Tone.NEUTRAL)
                    }
                }
            }
        }
    }
}
