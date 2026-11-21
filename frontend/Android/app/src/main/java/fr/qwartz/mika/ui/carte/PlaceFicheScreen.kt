package fr.qwartz.mika.ui.carte

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedCard
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
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
import fr.qwartz.mika.data.moi.carte.EventItem
import fr.qwartz.mika.data.moi.carte.GoogleShown
import fr.qwartz.mika.data.moi.carte.LinkText
import fr.qwartz.mika.data.moi.carte.Photo
import fr.qwartz.mika.data.moi.carte.Place
import fr.qwartz.mika.data.moi.carte.PlaceFiche
import fr.qwartz.mika.data.moi.carte.PlaceRefreshed
import fr.qwartz.mika.data.moi.carte.ReviewShown
import fr.qwartz.mika.data.moi.carte.Scene
import fr.qwartz.mika.data.moi.carte.SceneHere
import fr.qwartz.mika.data.moi.carte.ScenePin
import fr.qwartz.mika.data.moi.carte.TripSummary
import fr.qwartz.mika.data.moi.carte.askAboutPlace
import fr.qwartz.mika.data.moi.carte.ficheSub
import fr.qwartz.mika.data.moi.carte.googleShown
import fr.qwartz.mika.data.moi.carte.nearEventLine
import fr.qwartz.mika.data.moi.carte.osmShown
import fr.qwartz.mika.data.moi.carte.placeContacts
import fr.qwartz.mika.data.moi.carte.placeTags
import fr.qwartz.mika.data.moi.carte.ratingWords
import fr.qwartz.mika.data.moi.carte.shownPhotos
import fr.qwartz.mika.data.moi.carte.siteLabel
import fr.qwartz.mika.data.moi.carte.tourismShown
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
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.shell.said
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.launch

/*
 * La fiche d'un lieu (`Route.PlaceFiche`, ADR 0259 ; la maquette `vueFiche` de `ecrans/carte-avis.js`, avec Google Maps
 * à la place de Tripadvisor) : par-dessus la Carte, sa barre (le nom, ce qu'il est, où, à quelle distance ; ✦ « Demander
 * à Mika »), la bande du plan et des photos, ses étiquettes, Itinéraire · Au voyage · Appeler · Site · En parler à Mika,
 * le bloc Google Maps (la note, les avis avec leur auteur et leur date, « Voir sur Google Maps », la date du cache,
 * « Actualiser »), les infos pratiques d'OpenStreetMap, ce qu'en dit l'office de tourisme, les événements tout près.
 * Chaque source se nomme là où elle parle. Un lieu sans Google le dit.
 */

/** Une fiche lue se garde un moment : 60 fiches par minute et par compte, ne pas la relire à chaque retour. */
const val FICHE_TTL_MS = 2 * 60_000L

/** Ce dont la fiche d'un lieu a besoin : la lire, l'actualiser, l'heure, et ce qu'on dit d'un « Actualiser » muet. */
class FicheDeps(
    val read: suspend (String) -> MoiApi.Result<PlaceFiche>,
    val refresh: suspend (String) -> MoiApi.Result<PlaceRefreshed>,
    val now: () -> Long,
    val refreshedWord: String,
) {
    companion object {
        fun of(graph: AppGraph): FicheDeps {
            val api = CarteApi(graph.moi)
            return FicheDeps({ api.place(it) }, { api.refresh(it) }, graph.clock::wallMs, graph.context.getString(R.string.fiche_refreshed))
        }
    }
}

/**
 * Une fiche de lieu, lue (et relue après deux minutes, au retour sur l'écran), et « Actualiser » : ce qui n'a pas pu se
 * relire se dit sous le bloc ([refreshNote]), et la fiche se relit (ce qui l'a pu est gardé) — sauf un 429, qui n'a rien
 * tenté ; réussi, ou relu après un 503, le lieu passe à la liste d'Explorer ([refreshedPlace], R2-A06, R3-03). Ce qui
 * n'a pas pu se relire ne se dit plus quand la fiche se relit à une visite suivante (R2-A07). Un modèle par lieu et par
 * session : rouvrir la fiche la montre de suite.
 */
class PlaceFicheViewModel(private val deps: FicheDeps, val id: String) : ViewModel() {
    constructor(graph: AppGraph, id: String) : this(FicheDeps.of(graph), id)

    var load by mutableStateOf<Load<PlaceFiche>>(Load.Loading)
        private set
    var refreshing by mutableStateOf(false)
        private set
    /** Ce qui n'a pas pu se relire (« Actualiser »), en mots ; vide : rien. */
    var refreshNote by mutableStateOf("")
        private set
    /** Ce qu'il faut dire en passant (« Fiche relue. »). */
    val said = MutableSharedFlow<String>(extraBufferCapacity = 4)
    /** Le lieu qu'« Actualiser » vient de relire : sa ligne d'Explorer le suit. */
    val refreshedPlace = MutableSharedFlow<Place>(extraBufferCapacity = 4)

    private var readAt = 0L
    private var job: Job? = null

    private fun now() = deps.now()

    /**
     * L'écran revient : la fiche se lit, ou se relit si elle a plus de deux minutes — et ce qui n'avait pas pu se relire
     * à la visite d'avant ne se dit plus (un quota qui revient à 14:05, lu à 16:00).
     */
    fun resume() {
        if (load is Load.Ready && now() - readAt < FICHE_TTL_MS) return
        if (load is Load.Ready) refreshNote = ""
        read()
    }

    fun retry() {
        load = Load.Loading
        read()
    }

    /**
     * La fiche lue ; [afterRefresh] : relue après un « Actualiser » refusé en partie (un 503) — une lecture partie avant
     * cède la place, et ce qui a pu se relire passe aussi à la ligne d'Explorer, comme sur le web (R3-03).
     */
    private fun read(afterRefresh: Boolean = false) {
        if (afterRefresh) job?.cancel() else if (job?.isActive == true) return
        job = viewModelScope.launch {
            when (val got = deps.read(id)) {
                is MoiApi.Result.Ok -> {
                    load = Load.Ready(got.value)
                    readAt = now()
                    if (afterRefresh) refreshedPlace.tryEmit(got.value.place)
                }
                // une relecture qui échoue garde ce qu'on avait, sauf un lieu qui n'est plus là
                is MoiApi.Result.Failed -> if (load !is Load.Ready || got.error.gone) load = Load.Failed(got.error)
            }
        }
    }

    fun refresh() {
        if (refreshing) return
        refreshing = true
        refreshNote = ""
        viewModelScope.launch {
            when (val got = deps.refresh(id)) {
                is MoiApi.Result.Ok -> {
                    job?.cancel()
                    load = Load.Ready(got.value.fiche)
                    readAt = now()
                    said.tryEmit(got.value.message.ifBlank { deps.refreshedWord })
                    refreshedPlace.tryEmit(got.value.place)
                }
                is MoiApi.Result.Failed -> {
                    refreshNote = got.error.said
                    // ce qui a pu se relire est gardé : la fiche se relit, et sa ligne d'Explorer avec (un 429 n'a
                    // rien tenté)
                    if (got.error.code != 429) read(afterRefresh = true)
                }
            }
            refreshing = false
        }
    }
}

/** Le plan d'une fiche : le lieu (choisi, rose s'il vient d'elle), et toi si on sait où tu es. */
internal fun ficheScene(lat: Double?, lon: Double?, here: Here?, mika: Boolean): Scene {
    if (lat == null || lon == null) return Scene.EMPTY
    return Scene(
        pins = listOf(ScenePin("fiche", lat, lon, mika = mika, selected = true)),
        here = here?.let { SceneHere(it.lat, it.lon) },
    )
}

@Composable
fun PlaceFicheScreen(graph: AppGraph, route: Route.PlaceFiche) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val store = rememberCarteStore(graph)
    val vm: PlaceFicheViewModel = viewModel(key = "carte.lieu|$session|${route.id}") { PlaceFicheViewModel(graph, route.id) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(vm, lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            vm.resume()
            store.loadPosition()
        }
    }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    // « Actualiser » a relu le lieu : sa ligne d'Explorer montre la nouvelle note (R2-A06)
    LaunchedEffect(vm, store) { vm.refreshedPlace.collect { store.placeRefreshed(vm.id, it) } }
    val fiche = vm.load.valueOrNull
    // la fiche n'a pas de distance (elle ne sait pas d'où l'on vient) : celle de la liste d'où elle s'est ouverte
    val place = fiche?.place?.let { p -> if (p.distanceM == null && route.hint?.distanceM != null) p.copy(distanceM = route.hint.distanceM) else p }
        ?: route.hint
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
                title = place?.name?.ifBlank { null } ?: stringResource(R.string.fiche_place_title),
                nav = BarNav.BACK,
                subtitle = place?.let { ficheSub(it) },
                actions = {
                    if (place != null) BarAction(R.drawable.ic_m_sparkle, stringResource(R.string.fiche_ask_mika), { askMika(askAboutPlace(place)) }, tint = mika.accent)
                },
            )
        },
    ) { modifier ->
        val load = vm.load
        when {
            place == null && load is Load.Failed && load.error.gone ->
                Notice(stringResource(R.string.fiche_place_gone), modifier, action = stringResource(R.string.fiche_back_to_map)) { shell.back() }
            place == null && load is Load.Failed ->
                Notice(load.error.said, modifier, action = stringResource(R.string.retry), onAction = vm::retry)
            place == null -> Box(modifier, contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            else -> PlaceFicheBody(
                graph = graph,
                vm = vm,
                place = place,
                fiche = fiche,
                hers = route.mika,
                here = store.here,
                outside = outside,
                onRoute = { shell.open(Route.Carte(CarteTabs.ROUTE, to = place)) },
                onTrip = { adding = true },
                onAsk = { askMika(askAboutPlace(place)) },
                onPhoto = { viewer = it },
                onEvent = { e -> shell.navigate(Route.EventFiche(e.id, hint = e)) },
                modifier = modifier,
            )
        }
    }
    if (adding && place != null) TripAdder(store, place, dayOf = null) { adding = false }
    val photos = fiche?.let { shownPhotos(it.tourism?.photos, it.reviews?.photos) }.orEmpty()
    viewer?.let { start -> PhotoViewer(graph, photos, start, outside) { viewer = null } }
}

/**
 * « Au voyage » d'une fiche : la feuille de tes voyages ([dayOf] : le jour où poser un événement), puis « Nouveau
 * voyage… » — la fenêtre, le lieu pour premier arrêt ; créé, le voyage s'ouvre.
 */
@Composable
internal fun TripAdder(store: CarteStore, place: Place, dayOf: ((TripSummary) -> Int)?, onClose: () -> Unit) {
    val shell = LocalShell.current
    var asking by remember { mutableStateOf(false) }
    if (!asking) {
        AddToTripSheet(store, place, onDismiss = onClose, onNew = { asking = true }, dayOf = dayOf)
        return
    }
    val made = stringResource(R.string.carte_trip_made)
    TripFormDialog(
        edit = null,
        first = place,
        onDismiss = onClose,
        submit = { values, key, firstKey ->
            when (val got = store.createTripAsync(values, key, place, firstKey).await()) {
                is MoiApi.Result.Ok -> {
                    shell.toast(made)
                    if (got.value.id.isNotEmpty()) shell.navigate(Route.Trip(got.value.id))
                    null
                }
                is MoiApi.Result.Failed -> got.error
            }
        },
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun PlaceFicheBody(
    graph: AppGraph,
    vm: PlaceFicheViewModel,
    place: Place,
    fiche: PlaceFiche?,
    hers: Boolean,
    here: Here?,
    outside: Outside,
    onRoute: () -> Unit,
    onTrip: () -> Unit,
    onAsk: () -> Unit,
    onPhoto: (Int) -> Unit,
    onEvent: (EventItem) -> Unit,
    modifier: Modifier,
) {
    val scheme = MaterialTheme.colorScheme
    val now = graph.clock.wallMs()
    val photos = remember(fiche) { fiche?.let { shownPhotos(it.tourism?.photos, it.reviews?.photos) }.orEmpty() }
    val contacts = remember(fiche) { placeContacts(fiche) }
    val load = vm.load
    LazyColumn(modifier, contentPadding = PaddingValues(bottom = 32.dp)) {
        item("band") {
            val title = stringResource(R.string.fiche_where_is, place.name.ifBlank { "ce lieu" })
            PhotoBand(graph, ficheScene(place.lat, place.lon, here, hers), title, photos, outside, onPhoto)
        }
        item("head") {
            Column(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 12.dp)) {
                if (hers) {
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(bottom = 8.dp)) {
                        MIcon(R.drawable.ic_m_sparkle, null, size = 14.dp, tint = mika.accent)
                        Spacer(Modifier.width(4.dp))
                        Text(stringResource(R.string.carte_regard_proposed), style = MaterialTheme.typography.labelMedium, color = mika.accent)
                    }
                }
                FicheTags(placeTags(place, fiche?.reviews))
                FlowRow(
                    Modifier.fillMaxWidth().padding(top = 12.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    val small = PaddingValues(horizontal = 14.dp, vertical = 8.dp)
                    Button(onClick = onRoute, contentPadding = small) { ButtonLabel(R.drawable.ic_m_route, stringResource(R.string.carte_place_route)) }
                    FilledTonalButton(onClick = onTrip, contentPadding = small) { ButtonLabel(R.drawable.ic_m_plus, stringResource(R.string.carte_place_trip)) }
                    if (contacts.tel != null) {
                        OutlinedButton(onClick = { outside.dial(contacts.tel) }, contentPadding = small) {
                            ButtonLabel(R.drawable.ic_m_phone, stringResource(R.string.fiche_call))
                        }
                    }
                    if (contacts.site != null) {
                        val siteLabel = stringResource(R.string.fiche_site_full, siteLabel(contacts.site))
                        OutlinedButton(onClick = { outside.open(contacts.site) }, contentPadding = small, modifier = Modifier.semantics { contentDescription = siteLabel }) {
                            ButtonLabel(R.drawable.ic_m_globe, stringResource(R.string.fiche_site))
                        }
                    }
                    OutlinedButton(
                        onClick = onAsk,
                        contentPadding = small,
                        border = BorderStroke(1.dp, mika.line),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = mika.accent),
                    ) { ButtonLabel(R.drawable.ic_m_chat, stringResource(R.string.carte_place_ask_full)) }
                }
            }
        }
        if (fiche == null) {
            item("reading") {
                when {
                    load is Load.Failed && load.error.gone -> NoteBox(stringResource(R.string.fiche_place_gone), R.drawable.ic_m_alert, Modifier.padding(16.dp), tone = Tone.WARN)
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
        item("google") {
            val reviews = fiche.reviews
            if (reviews != null) {
                GoogleBlock(googleShown(reviews, now), vm.refreshing, vm.refreshNote, outside, vm::refresh, Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp))
            } else {
                NoteBox(stringResource(R.string.fiche_no_google), R.drawable.ic_m_info, Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp))
            }
        }
        osmShown(fiche.osm, now)?.let { o ->
            item("osm") {
                Column(Modifier.fillMaxWidth()) {
                    FicheHead(stringResource(R.string.fiche_osm))
                    FactRows(o.rows, outside, Modifier.padding(horizontal = 16.dp))
                    SourceLine(listOfNotNull(o.attribution, LinkText(o.extract), o.fix), outside, Modifier.padding(top = 4.dp))
                }
            }
        }
        tourismShown(fiche.tourism)?.let { t ->
            item("tourism") {
                Column(Modifier.fillMaxWidth()) {
                    FicheHead(stringResource(R.string.fiche_tourism))
                    for (p in t.paragraphs) {
                        Text(p, style = MaterialTheme.typography.bodyMedium.copy(lineHeight = 20.sp), color = scheme.onSurfaceVariant, modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 6.dp))
                    }
                    if (t.labels.isNotEmpty()) {
                        FlowRow(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            for (l in t.labels) Tag(l, Tone.OK, R.drawable.ic_m_shield_check)
                        }
                    }
                    if (t.rows.isNotEmpty()) FactRows(t.rows, outside, Modifier.padding(start = 16.dp, end = 16.dp, top = 8.dp))
                    SourceLine(listOfNotNull(LinkText(t.attribution), t.licence, t.fiche), outside, Modifier.padding(top = 4.dp))
                }
            }
        }
        if (fiche.events.isNotEmpty()) {
            item("events-head") { FicheHead(stringResource(R.string.fiche_events_near), count = fiche.events.size) }
            for (e in fiche.events) {
                item("ev:" + e.id) { NearEventRow(e) { onEvent(e) } }
            }
        }
        // sans bloc Google, « Actualiser » relit tout de même l'office de tourisme
        if (fiche.reviews == null) {
            item("refresh") {
                Column(Modifier.fillMaxWidth().padding(16.dp)) {
                    RefreshButton(vm.refreshing, stringResource(R.string.fiche_refresh_all), vm::refresh)
                    if (vm.refreshNote.isNotEmpty()) NoteBox(vm.refreshNote, R.drawable.ic_m_alert, Modifier.padding(top = 8.dp), tone = Tone.WARN)
                }
            }
        }
    }
}

@Composable
internal fun ButtonLabel(icon: Int, text: String) {
    MIcon(icon, null, size = 18.dp)
    Spacer(Modifier.width(6.dp))
    Text(text, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.labelLarge)
}

@Composable
private fun RefreshButton(refreshing: Boolean, label: String, onClick: () -> Unit) {
    FilledTonalButton(onClick = onClick, enabled = !refreshing, contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp)) {
        if (refreshing) {
            CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
            Spacer(Modifier.width(6.dp))
            Text(stringResource(R.string.fiche_refreshing), style = MaterialTheme.typography.labelLarge)
        } else {
            ButtonLabel(R.drawable.ic_m_refresh, label)
        }
    }
}

/**
 * Le bloc « Google Maps » (`.fiche-ta` de la maquette, refait pour Google) : son nom et « Voir sur Google Maps » ; la note
 * en grand, ses étoiles, le nombre d'avis, le prix et sa fourchette ; le résumé ; ce que Google ajoute ; les avis les
 * plus récents, chacun avec son auteur (lié à sa page), sa date en mots, son texte (un long se replie) ; sa note ; en
 * pied, quand ce serveur l'a lu et « Actualiser », puis ce qui n'a pas pu se relire. Google sans rien de ce lieu : sa
 * note seule (rien trouvé sous ce nom, ou pourquoi on n'a pas pu chercher).
 */
@Composable
private fun GoogleBlock(
    g: GoogleShown,
    refreshing: Boolean,
    refreshNote: String,
    outside: Outside,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val scheme = MaterialTheme.colorScheme
    OutlinedCard(modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp)) {
        Column(Modifier.fillMaxWidth().padding(start = 14.dp, end = 8.dp, top = 12.dp, bottom = 10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    g.label,
                    style = MaterialTheme.typography.labelLarge,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.clip(RoundedCornerShape(6.dp)).border(1.dp, scheme.outline, RoundedCornerShape(6.dp)).padding(horizontal = 8.dp, vertical = 2.dp),
                )
                Spacer(Modifier.weight(1f))
                if (g.link != null) {
                    TextButton(onClick = { outside.open(g.link) }) {
                        Text(stringResource(R.string.fiche_google_open), style = MaterialTheme.typography.labelLarge)
                        Spacer(Modifier.width(4.dp))
                        MIcon(R.drawable.ic_m_external, null, size = 16.dp)
                    }
                }
            }
            if (!g.found) {
                Text(g.note, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 8.dp, end = 6.dp))
            } else {
                if (g.rating != null || g.price.isNotEmpty()) {
                    Row(Modifier.padding(top = 8.dp, end = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        if (g.rating != null) {
                            Text(ratingWords(g.rating), style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Medium)
                            Spacer(Modifier.width(8.dp))
                            Stars(g.rating, size = 18.dp)
                            Spacer(Modifier.width(8.dp))
                            if (g.count.isNotEmpty()) Text(g.count, style = MaterialTheme.typography.bodyMedium, color = scheme.onSurfaceVariant)
                        }
                    }
                    if (g.price.isNotEmpty()) Box(Modifier.padding(top = 6.dp)) { Tag(g.price, Tone.NEUTRAL) }
                }
                if (g.summary.isNotEmpty()) {
                    Text(g.summary, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 8.dp, end = 6.dp))
                }
                if (g.facts.isNotEmpty()) FactRows(g.facts, outside, Modifier.padding(top = 10.dp, end = 6.dp))
                if (g.reviews.isNotEmpty()) {
                    Row(Modifier.padding(top = 14.dp, bottom = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(stringResource(R.string.fiche_reviews_recent), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Medium, color = scheme.primary)
                        Spacer(Modifier.width(6.dp))
                        Text(g.reviews.size.toString(), style = MaterialTheme.typography.labelMedium, color = scheme.onSurfaceVariant)
                    }
                    for (r in g.reviews) ReviewRow(r, outside)
                }
                if (g.note.isNotEmpty()) {
                    Text(g.note, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, modifier = Modifier.padding(top = 8.dp, end = 6.dp))
                }
            }
            HorizontalDivider(Modifier.padding(top = 10.dp, bottom = 8.dp, end = 6.dp), color = scheme.outlineVariant)
            Row(verticalAlignment = Alignment.CenterVertically) {
                // quand ce serveur l'a lu (rien à dire : seulement « Actualiser »)
                if (g.cached.isNotEmpty()) {
                    MIcon(R.drawable.ic_m_history, null, size = 14.dp, tint = scheme.onSurfaceVariant)
                    Spacer(Modifier.width(6.dp))
                }
                Text(g.cached, style = MaterialTheme.typography.labelSmall, color = scheme.onSurfaceVariant, modifier = Modifier.weight(1f))
                RefreshButton(refreshing, stringResource(R.string.fiche_refresh), onRefresh)
            }
            if (refreshNote.isNotEmpty()) {
                NoteBox(refreshNote, R.drawable.ic_m_alert, Modifier.padding(top = 8.dp, end = 6.dp), tone = Tone.WARN)
            }
        }
    }
}

/** Un avis : sa note, son auteur (lié à sa page chez Google), sa date en mots, son texte ; un long avis se replie. */
@Composable
private fun ReviewRow(r: ReviewShown, outside: Outside) {
    val scheme = MaterialTheme.colorScheme
    var open by rememberSaveable(r) { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().padding(top = 10.dp, end = 6.dp)) {
        HorizontalDivider(Modifier.padding(bottom = 8.dp), color = scheme.outlineVariant)
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (r.rating != null) {
                Stars(r.rating, size = 12.dp)
                Spacer(Modifier.width(6.dp))
            }
            LinkedText(
                r.author,
                outside,
                MaterialTheme.typography.labelLarge.copy(fontWeight = FontWeight.SemiBold),
                color = scheme.onSurface,
                linkColor = scheme.primary,
                maxLines = 1,
                modifier = Modifier.weight(1f, fill = false),
            )
            if (r.relative.isNotEmpty()) {
                Text(" · ${r.relative}", style = MaterialTheme.typography.labelMedium, color = scheme.onSurfaceVariant, maxLines = 1)
            }
        }
        val text = r.paragraphs.joinToString("\n")
        Text(
            text,
            style = MaterialTheme.typography.bodyMedium.copy(lineHeight = 19.sp),
            color = scheme.onSurfaceVariant,
            maxLines = if (r.long && !open) 5 else Int.MAX_VALUE,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(top = 4.dp),
        )
        if (r.long) {
            TextButton(onClick = { open = !open }, contentPadding = PaddingValues(horizontal = 0.dp, vertical = 0.dp), modifier = Modifier.heightIn(min = 36.dp)) {
                Text(stringResource(if (open) R.string.fiche_review_less else R.string.fiche_review_more), style = MaterialTheme.typography.labelLarge)
            }
        }
    }
}

/** Un événement tout près (« Bientôt, tout près ») : il ouvre sa fiche. */
@Composable
internal fun NearEventRow(e: EventItem, onClick: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    Row(
        Modifier.fillMaxWidth().heightIn(min = 56.dp).clickable(role = Role.Button, onClick = onClick).padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(40.dp).clip(RoundedCornerShape(12.dp)).background(scheme.secondaryContainer), contentAlignment = Alignment.Center) {
            MIcon(R.drawable.ic_m_calendar, null, size = 20.dp, tint = scheme.onSecondaryContainer)
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(e.name.ifBlank { "—" }, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            val line = nearEventLine(e)
            if (line.isNotEmpty()) Text(line, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
    }
}
