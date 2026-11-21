package fr.qwartz.mika.ui.carte

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.files.ComposerDraft
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.carte.CarteApi
import fr.qwartz.mika.data.moi.carte.EventFiche
import fr.qwartz.mika.data.moi.carte.EventItem
import fr.qwartz.mika.data.moi.carte.LinkText
import fr.qwartz.mika.data.moi.carte.askAboutEvent
import fr.qwartz.mika.data.moi.carte.eventAsPlace
import fr.qwartz.mika.data.moi.carte.eventShown
import fr.qwartz.mika.data.moi.carte.eventSub
import fr.qwartz.mika.data.moi.carte.eventTags
import fr.qwartz.mika.data.moi.carte.eventTripDay
import fr.qwartz.mika.data.moi.carte.shownPhotos
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.BarAction
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.shell.Notice
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.shell.said
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/*
 * La fiche d'un événement (`Route.EventFiche`, ADR 0259 ; la maquette `vueEvenement` de `ecrans/carte-avis.js`) :
 * par-dessus la Carte, sa barre (son nom, ses thèmes, sa commune ; ✦ « Demander à Mika »), la bande du plan et des
 * photos, quand, combien, à quelle distance ; Itinéraire, Au voyage (au bon jour), En parler à Mika ; le programme, ses
 * dates, le pratique (le lieu nommé ouvre sa fiche, l'adresse, les tarifs, les contacts), et qui l'a écrite — l'office
 * de tourisme, sa date, la Licence Ouverte —, toujours.
 */

/** Une fiche d'événement lue se garde cinq minutes (comme le web). */
const val EVENT_TTL_MS = 5 * 60_000L

/** La fiche d'un événement, lue, relue au retour sur l'écran si elle a plus de cinq minutes. Un modèle par événement. */
class EventFicheViewModel(private val graph: AppGraph, val id: String) : ViewModel() {
    private val api = CarteApi(graph.moi)

    var load by mutableStateOf<Load<EventFiche>>(Load.Loading)
        private set
    private var readAt = 0L
    private var job: Job? = null

    fun resume() {
        if (load is Load.Ready && graph.clock.wallMs() - readAt < EVENT_TTL_MS) return
        read()
    }

    fun retry() {
        load = Load.Loading
        read()
    }

    private fun read() {
        if (job?.isActive == true) return
        job = viewModelScope.launch {
            when (val got = api.event(id)) {
                is MoiApi.Result.Ok -> {
                    load = Load.Ready(got.value)
                    readAt = graph.clock.wallMs()
                }
                is MoiApi.Result.Failed -> if (load !is Load.Ready || got.error.gone) load = Load.Failed(got.error)
            }
        }
    }
}

@Composable
fun EventFicheScreen(graph: AppGraph, route: Route.EventFiche) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val store = rememberCarteStore(graph)
    val vm: EventFicheViewModel = viewModel(key = "carte.evenement|$session|${route.id}") { EventFicheViewModel(graph, route.id) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(vm, lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            vm.resume()
            store.loadInfo()
            store.loadPosition()
        }
    }
    val fiche = vm.load.valueOrNull
    // la fiche ne sait pas d'où l'on vient : la distance de la ligne d'où elle s'est ouverte
    val event = fiche?.event?.let { e -> if (e.distanceM == null && route.hint?.distanceM != null) e.copy(distanceM = route.hint.distanceM) else e }
        ?: route.hint
    val themes = store.info.valueOrNull?.themes.orEmpty()
    var adding by remember { mutableStateOf(false) }
    var viewer by rememberSaveable { mutableStateOf<Int?>(null) }
    val outside = rememberOutside()
    val askMika = { text: String ->
        graph.scope.launch { graph.shareInbox.deposit(ComposerDraft(text = text)) }
        shell.open(Route.Chat)
    }
    SectionScaffold(
        topBar = {
            MikaTopBar(
                title = event?.name?.ifBlank { null } ?: stringResource(R.string.fiche_event_title),
                nav = BarNav.BACK,
                subtitle = event?.let { eventSub(it, fiche?.town.orEmpty(), themes) },
                actions = {
                    if (event != null) BarAction(R.drawable.ic_m_sparkle, stringResource(R.string.fiche_ask_mika), { askMika(askAboutEvent(event)) }, tint = mika.accent)
                },
            )
        },
    ) { modifier ->
        val load = vm.load
        when {
            event == null && load is Load.Failed && load.error.gone ->
                Notice(stringResource(R.string.fiche_event_gone), modifier, action = stringResource(R.string.fiche_back_to_map)) { shell.back() }
            event == null && load is Load.Failed ->
                Notice(load.error.said, modifier, action = stringResource(R.string.retry), onAction = vm::retry)
            event == null -> Box(modifier, contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            else -> EventFicheBody(
                graph = graph,
                vm = vm,
                event = event,
                fiche = fiche,
                hers = route.mika,
                here = store.here,
                outside = outside,
                onRoute = { shell.open(Route.Carte(CarteTabs.ROUTE, to = eventAsPlace(event))) },
                onTrip = { adding = true },
                onAsk = { askMika(askAboutEvent(event)) },
                onPhoto = { viewer = it },
                onVenue = { id -> shell.navigate(Route.PlaceFiche(id)) },
                modifier = modifier,
            )
        }
    }
    if (adding && event != null) {
        TripAdder(store, eventAsPlace(event), dayOf = { t -> eventTripDay(t.start, t.days, event) }) { adding = false }
    }
    val photos = fiche?.let { shownPhotos(it.photos) }.orEmpty()
    viewer?.let { start -> PhotoViewer(graph, photos, start, outside) { viewer = null } }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun EventFicheBody(
    graph: AppGraph,
    vm: EventFicheViewModel,
    event: EventItem,
    fiche: EventFiche?,
    hers: Boolean,
    here: Here?,
    outside: Outside,
    onRoute: () -> Unit,
    onTrip: () -> Unit,
    onAsk: () -> Unit,
    onPhoto: (Int) -> Unit,
    onVenue: (String) -> Unit,
    modifier: Modifier,
) {
    val scheme = MaterialTheme.colorScheme
    val shown = remember(fiche, event) { fiche?.let { eventShown(it.copy(event = event)) } }
    val photos = remember(fiche) { fiche?.let { shownPhotos(it.photos) }.orEmpty() }
    val located = event.at != null
    val load = vm.load
    LazyColumn(modifier, contentPadding = PaddingValues(bottom = 32.dp)) {
        item("band") {
            val title = stringResource(R.string.fiche_event_where, event.name.ifBlank { "cet événement" })
            PhotoBand(graph, ficheScene(event.lat, event.lon, here, hers), title, photos, outside, onPhoto)
        }
        item("head") {
            Column(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 12.dp)) {
                if (hers) {
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(bottom = 8.dp)) {
                        MIcon(R.drawable.ic_m_sparkle, null, size = 14.dp, tint = mika.accent)
                        Spacer(Modifier.width(4.dp))
                        Text(stringResource(R.string.events_found_for_you), style = MaterialTheme.typography.labelMedium, color = mika.accent)
                    }
                }
                if (event.place.isNotBlank()) {
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(bottom = 8.dp)) {
                        MIcon(R.drawable.ic_m_pin, null, size = 14.dp, tint = scheme.onSurfaceVariant)
                        Spacer(Modifier.width(4.dp))
                        Text(event.place.trim(), style = MaterialTheme.typography.bodyMedium)
                    }
                }
                FicheTags(shown?.tags ?: eventTags(event))
                FlowRow(
                    Modifier.fillMaxWidth().padding(top = 12.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    val small = PaddingValues(horizontal = 14.dp, vertical = 8.dp)
                    Button(onClick = onRoute, enabled = located, contentPadding = small) { ButtonLabel(R.drawable.ic_m_route, stringResource(R.string.carte_place_route)) }
                    FilledTonalButton(onClick = onTrip, enabled = located, contentPadding = small) { ButtonLabel(R.drawable.ic_m_plus, stringResource(R.string.carte_place_trip)) }
                    OutlinedButton(
                        onClick = onAsk,
                        contentPadding = small,
                        border = BorderStroke(1.dp, mika.line),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = mika.accent),
                    ) { ButtonLabel(R.drawable.ic_m_chat, stringResource(R.string.carte_place_ask_full)) }
                }
            }
        }
        if (fiche == null || shown == null) {
            item("reading") {
                when {
                    load is Load.Failed && load.error.gone -> NoteBox(stringResource(R.string.fiche_event_gone), R.drawable.ic_m_alert, Modifier.padding(16.dp), tone = Tone.WARN)
                    load is Load.Failed -> Column(Modifier.padding(16.dp)) {
                        NoteBox(load.error.said, R.drawable.ic_m_alert, tone = Tone.WARN)
                        TextButton(onClick = vm::retry) { Text(stringResource(R.string.retry)) }
                    }
                    else -> Column(Modifier.fillMaxWidth().padding(16.dp)) {
                        LinearProgressIndicator(Modifier.fillMaxWidth())
                        Text(stringResource(R.string.fiche_reading), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, modifier = Modifier.padding(top = 6.dp))
                    }
                }
            }
            return@LazyColumn
        }
        if (shown.paragraphs.isNotEmpty()) {
            item("programme") {
                Column(Modifier.fillMaxWidth()) {
                    FicheHead(stringResource(R.string.fiche_event_programme))
                    for (p in shown.paragraphs) {
                        Text(p, style = MaterialTheme.typography.bodyMedium.copy(lineHeight = 20.sp), color = scheme.onSurfaceVariant, modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 6.dp))
                    }
                }
            }
        }
        if (shown.dates.isNotEmpty()) {
            item("dates") {
                Column(Modifier.fillMaxWidth()) {
                    FicheHead(stringResource(R.string.fiche_event_dates), count = shown.dates.size)
                    for (d in shown.dates) {
                        Row(Modifier.padding(start = 16.dp, end = 16.dp, bottom = 4.dp)) {
                            MIcon(R.drawable.ic_m_calendar, null, size = 14.dp, tint = scheme.onSurfaceVariant, modifier = Modifier.padding(top = 3.dp))
                            Spacer(Modifier.width(8.dp))
                            Text(d, style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                    if (shown.moreDates.isNotEmpty()) {
                        Text(shown.moreDates, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 16.dp))
                    }
                }
            }
        }
        item("pratique") {
            Column(Modifier.fillMaxWidth()) {
                if (shown.venue.isNotEmpty() || shown.rows.isNotEmpty()) FicheHead(stringResource(R.string.fiche_event_practical))
                if (shown.venue.isNotEmpty()) {
                    val venueId = shown.venueId
                    Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, bottom = 6.dp)) {
                        Text(stringResource(R.string.fiche_event_venue), style = MaterialTheme.typography.bodyMedium, color = scheme.onSurfaceVariant, modifier = Modifier.width(104.dp).padding(end = 8.dp))
                        if (venueId != null) {
                            Text(
                                shown.venue,
                                style = MaterialTheme.typography.bodyMedium,
                                fontWeight = FontWeight.Medium,
                                color = scheme.primary,
                                modifier = Modifier.weight(1f).clickable(role = Role.Button) { onVenue(venueId) },
                            )
                        } else {
                            Text(shown.venue, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                        }
                    }
                }
                if (shown.rows.isNotEmpty()) FactRows(shown.rows, outside, Modifier.padding(horizontal = 16.dp))
                SourceLine(listOfNotNull(LinkText(shown.attribution), shown.licence, shown.fiche, LinkText(shown.merged)), outside, Modifier.padding(top = 8.dp))
            }
        }
    }
}
