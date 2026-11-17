package fr.qwartz.mika.ui.carte

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.width
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.files.ComposerDraft
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.carte.Place
import fr.qwartz.mika.data.moi.carte.askAboutPlace
import fr.qwartz.mika.data.moi.carte.refOf
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.rememberSessionKey
import kotlinx.coroutines.launch

/*
 * Carte (ADR 0193 à 0196, 0235 ; la maquette `ecrans/carte.js`, variante tiroir) : trois onglets sous la barre du haut,
 * qui se remplacent sans s'empiler. Explorer : la carte prend l'écran, la recherche flotte dessus, les lieux montent du
 * bas. Itinéraire : ses points et son résultat montent du bas. Voyages : la liste en cartes, « Nouveau voyage » en bouton
 * flottant ; un voyage s'ouvre par-dessus (`Route.Trip`, [TripScreen]). Ce que Mika a cherché ou montré
 * (`Route.Carte.look`) s'ouvre dans Explorer (ses lieux) ou Itinéraire (son trajet).
 */

/** Les onglets de la Carte ; une adresse inconnue retombe sur Explorer. */
internal object CarteTabs {
    const val EXPLORER = "explorer"
    const val ROUTE = "itineraire"
    const val TRIPS = "voyages"

    fun of(tab: String): String = if (tab == ROUTE || tab == TRIPS) tab else EXPLORER
}

/**
 * Ce que les onglets demandent ailleurs : [routeTo] ouvre Itinéraire avec le lieu en arrivée (`Route.Carte(tab =
 * "itineraire", to = lieu)`, que l'onglet prend une fois) ; [addToTrip] ouvre la feuille « Ajouter au voyage » ; [ask]
 * et [say] posent une phrase dans le champ du chat et l'ouvrent ; [leaveLook] quitte le regard de Mika montré (la route
 * revient à Explorer seul) ; [open] ouvre un autre onglet sur un regard (sans s'empiler) ou un voyage (par-dessus).
 */
internal class CarteLinks(
    val routeTo: (Place) -> Unit,
    val addToTrip: (Place) -> Unit,
    val ask: (Place) -> Unit,
    val say: (String) -> Unit,
    val leaveLook: () -> Unit,
    val open: (Route) -> Unit,
)

/** « Nouveau voyage » demandé : de rien (Voyages), ou d'un lieu, son premier arrêt (« Ajouter au voyage »). */
private data class NewTrip(val first: Place?)

/**
 * La Carte, la rubrique du tiroir (`Route.Carte(tab)`) ; [nav] : le tiroir depuis le tiroir, la flèche quand un autre
 * écran y mène. Chaque onglet se relit à chaque retour sur l'écran (ce qui est branché, ta position, tes voyages), sans
 * minuterie.
 */
@Composable
fun CarteScreen(graph: AppGraph, route: Route.Carte, nav: BarNav) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val store = rememberCarteStore(graph)
    val explorer: ExplorerViewModel = viewModel(key = "carte.explorer|$session") { ExplorerViewModel(graph, store) }
    val itinerary: ItineraryViewModel = viewModel(key = "carte.itineraire|$session") { ItineraryViewModel(graph, store) }
    val tab = CarteTabs.of(route.tab)
    val look = refOf(route.look)
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(explorer, itinerary, lifecycle, tab) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            when (tab) {
                CarteTabs.EXPLORER -> explorer.resume()
                CarteTabs.ROUTE -> itinerary.resume()
                else -> {
                    store.loadInfo()
                    store.loadList()
                }
            }
        }
    }
    // ce que la route ouvre : un regard de Mika (ses lieux dans Explorer, son trajet dans Itinéraire)
    LaunchedEffect(tab, look) {
        when (tab) {
            CarteTabs.EXPLORER -> explorer.applyLook(look)
            CarteTabs.ROUTE -> itinerary.applyLook(look)
        }
    }
    // « Itinéraire jusqu'ici » : le lieu en arrivée, pris une fois ; la route redevient celle de l'onglet
    LaunchedEffect(tab, route.to) {
        val to = route.to
        if (tab == CarteTabs.ROUTE && to != null) {
            itinerary.routeTo(to)
            shell.replace(Route.Carte(CarteTabs.ROUTE))
        }
    }
    var addTo by remember { mutableStateOf<Place?>(null) }
    var newTrip by remember { mutableStateOf<NewTrip?>(null) }
    val askMika = { text: String ->
        graph.scope.launch { graph.shareInbox.deposit(ComposerDraft(text = text)) }
        shell.open(Route.Chat)
    }
    val links = CarteLinks(
        routeTo = { p -> shell.replace(Route.Carte(CarteTabs.ROUTE, to = p)) },
        addToTrip = { p -> addTo = p },
        ask = { p -> askMika(askAboutPlace(p)) },
        say = { text -> askMika(text) },
        leaveLook = { shell.replace(Route.Carte(CarteTabs.EXPLORER)) },
        open = { r -> if (r is Route.Carte) shell.replace(r) else shell.navigate(r) },
    )
    SectionScaffold(
        topBar = { CarteTopBar(tab, nav) },
        floatingActionButton = {
            if (tab == CarteTabs.TRIPS) {
                ExtendedFloatingActionButton(onClick = { newTrip = NewTrip(null) }) {
                    MIcon(R.drawable.ic_m_plus, null)
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.carte_trip_new))
                }
            }
        },
    ) { modifier ->
        when (tab) {
            CarteTabs.ROUTE -> ItineraryTab(graph, itinerary, links, modifier)
            CarteTabs.TRIPS -> TripsTab(graph, store, modifier)
            else -> ExplorerTab(graph, explorer, links, modifier)
        }
    }
    addTo?.let { p ->
        AddToTripSheet(store, p, onDismiss = { addTo = null }, onNew = {
            addTo = null
            newTrip = NewTrip(p)
        })
    }
    newTrip?.let { ask ->
        val made = stringResource(R.string.carte_trip_made)
        TripFormDialog(
            edit = null,
            first = ask.first,
            onDismiss = { newTrip = null },
            submit = { values, key, firstKey ->
                when (val got = store.createTripAsync(values, key, ask.first, firstKey).await()) {
                    is MoiApi.Result.Ok -> {
                        shell.toast(made)
                        // le voyage s'ouvre par-dessus la liste
                        if (tab != CarteTabs.TRIPS) shell.replace(Route.Carte(CarteTabs.TRIPS))
                        if (got.value.id.isNotEmpty()) shell.navigate(Route.Trip(got.value.id))
                        null
                    }
                    is MoiApi.Result.Failed -> got.error
                }
            },
        )
    }
}

/** La barre de la Carte : son titre, puis les trois onglets, qui se remplacent l'un l'autre sans s'empiler. */
@Composable
private fun CarteTopBar(tab: String, nav: BarNav) {
    val shell = LocalShell.current
    Column {
        MikaTopBar(title = stringResource(R.string.nav_map), nav = nav)
        val tabs = listOf(
            CarteTabs.EXPLORER to R.string.carte_tab_explorer,
            CarteTabs.ROUTE to R.string.carte_tab_route,
            CarteTabs.TRIPS to R.string.carte_tab_trips,
        )
        PrimaryTabRow(selectedTabIndex = tabs.indexOfFirst { it.first == tab }.coerceAtLeast(0)) {
            for ((id, label) in tabs) {
                Tab(
                    selected = id == tab,
                    onClick = { if (id != tab) shell.replace(Route.Carte(id)) },
                    text = { Text(stringResource(label)) },
                )
            }
        }
    }
}
