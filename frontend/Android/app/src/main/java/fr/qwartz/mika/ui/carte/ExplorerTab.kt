package fr.qwartz.mika.ui.carte

import androidx.activity.compose.BackHandler
import androidx.annotation.DrawableRes
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.BottomSheetScaffold
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FilledTonalIconToggleButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.rememberBottomSheetScaffoldState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.layout
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.carte.Category
import fr.qwartz.mika.data.moi.carte.Place
import fr.qwartz.mika.data.moi.carte.Regard
import fr.qwartz.mika.data.moi.carte.Where
import fr.qwartz.mika.data.moi.carte.addressId
import fr.qwartz.mika.data.moi.carte.km
import fr.qwartz.mika.data.moi.carte.placeId
import fr.qwartz.mika.data.moi.carte.placeLine
import fr.qwartz.mika.data.moi.carte.placeWhat
import fr.qwartz.mika.data.moi.carte.plural
import fr.qwartz.mika.data.moi.carte.searchLegend
import fr.qwartz.mika.data.moi.carte.searchTitle
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.map.ScenePlan
import fr.qwartz.mika.ui.map.SceneMap
import fr.qwartz.mika.ui.map.rememberMapFond
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.shell.said
import fr.qwartz.mika.ui.theme.mika
import kotlin.math.roundToInt

/** La part de l'écran que la feuille des résultats prend d'abord (la maquette : un peu moins de la moitié). */
private const val SHEET_SHARE = 0.42f

/**
 * Explorer (la maquette, `vueExplorer`) : la carte prend l'écran, la recherche flotte dessus — « Autour de moi » dans le
 * champ, les catégories du serveur en puces —, les résultats dans une feuille qui monte du bas, la carte cadrée sur eux ;
 * la fiche d'un lieu remplace la liste (Itinéraire, Au voyage, En parler). Sur la vraie carte quand le fond est prêt,
 * sinon sur le plan dessiné de ce qu'elle montre, avec sa note. Ce que Mika a cherché ou montré (un regard) prend la
 * place des résultats, ses lieux en rose ; chercher autre chose le quitte (la route revient à Explorer seul).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ExplorerTab(graph: AppGraph, vm: ExplorerViewModel, links: CarteLinks, modifier: Modifier) {
    val sheet = rememberBottomSheetScaffoldState()
    val density = LocalDensity.current
    val fonds = rememberMapFond(graph)
    SideEffect { vm.fondZone = fonds.fond?.zone }
    // un lieu choisi : « retour » rend la liste
    BackHandler(enabled = vm.sel != null) { vm.select(null) }
    // son regard vient d'être lu, ou vient d'échouer (oublié ou en panne) : la carte le cadre une fois — ses lieux, ou
    // le fond de carte plutôt que le cadre d'avant ; tant qu'il se lit, elle attend
    val regardLoad = vm.regardLoad
    val framed = when (regardLoad) {
        is Load.Ready -> "lu"
        is Load.Failed -> "échec"
        else -> ""
    }
    LaunchedEffect(vm.look, framed) {
        if (vm.look != null && framed.isNotEmpty()) vm.control.fit(orBase = framed == "échec")
    }
    var searchPx by remember { mutableIntStateOf(0) }
    BoxWithConstraints(modifier) {
        val peek = (maxHeight * SHEET_SHARE).coerceIn(150.dp, 340.dp)
        val searchTop = with(density) { searchPx.toDp() }
        val title = stringResource(R.string.carte_map_title)
        BottomSheetScaffold(
            scaffoldState = sheet,
            sheetPeekHeight = peek,
            sheetContent = { ExplorerSheet(vm, links, Modifier.heightIn(min = peek)) },
            modifier = Modifier.fillMaxSize(),
        ) {
            Box(Modifier.fillMaxSize()) {
                val scene = vm.scene
                SceneMap(
                    graph,
                    scene,
                    title,
                    Modifier.fillMaxSize(),
                    control = vm.control,
                    insets = PaddingValues(top = searchTop, bottom = peek),
                    onPin = vm::pinTouched,
                    onMove = vm::mapMoved,
                    plan = { why ->
                        ScenePlan(scene, title, why, Modifier.fillMaxSize(), notePadding = Modifier.padding(bottom = peek))
                    },
                )
                SearchOverlay(vm, links, Modifier.align(Alignment.TopCenter).onSizeChanged { searchPx = it.height })
                val attribution = fonds.fond?.attribution?.ifBlank { null } ?: "© OpenStreetMap"
                if (vm.control.live) {
                    Text(
                        attribution,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        modifier = Modifier
                            .align(Alignment.TopStart)
                            .layout { measurable, constraints ->
                                // juste au-dessus de la feuille, qu'elle soit basse ou haute
                                val p = measurable.measure(constraints)
                                val top = runCatching { sheet.bottomSheetState.requireOffset() }.getOrNull()
                                    ?: (constraints.maxHeight - peek.roundToPx()).toFloat()
                                layout(p.width, p.height) {
                                    p.place(8.dp.roundToPx(), (top - p.height - 6.dp.toPx()).roundToInt().coerceAtLeast(0))
                                }
                            }
                            .clip(RoundedCornerShape(4.dp))
                            .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.8f))
                            .padding(horizontal = 5.dp, vertical = 1.dp),
                    )
                }
            }
        }
    }
}

/**
 * La recherche qui flotte sur la carte : le champ, « Autour de moi » au bout, puis les catégories en puces. Chercher
 * quitte le regard de Mika montré : la route revient à Explorer seul.
 */
@Composable
private fun SearchOverlay(vm: ExplorerViewModel, links: CarteLinks, modifier: Modifier) {
    val leave = { if (vm.look != null) links.leaveLook() }
    val focus = LocalFocusManager.current
    val scheme = MaterialTheme.colorScheme
    val around = stringResource(R.string.carte_around_me)
    val state = stringResource(if (vm.where == Where.HERE) R.string.carte_around_me_on else R.string.carte_around_me_off)
    Column(modifier.fillMaxWidth().padding(top = 8.dp)) {
        Surface(
            shape = RoundedCornerShape(28.dp),
            color = scheme.surfaceContainerHigh,
            shadowElevation = 3.dp,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(start = 16.dp, end = 4.dp)) {
                MIcon(R.drawable.ic_m_search, null, size = 20.dp, tint = scheme.onSurfaceVariant)
                val label = stringResource(R.string.carte_search_label)
                TextField(
                    value = vm.q,
                    onValueChange = { leave(); vm.type(it) },
                    placeholder = { Text(stringResource(R.string.carte_search_hint), maxLines = 1, overflow = TextOverflow.Ellipsis) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                    keyboardActions = KeyboardActions(onSearch = { focus.clearFocus() }),
                    colors = TextFieldDefaults.colors(
                        focusedContainerColor = Color.Transparent,
                        unfocusedContainerColor = Color.Transparent,
                        focusedIndicatorColor = Color.Transparent,
                        unfocusedIndicatorColor = Color.Transparent,
                    ),
                    modifier = Modifier.weight(1f).semantics { contentDescription = label },
                )
                if (vm.q.isNotEmpty()) {
                    IconButton(onClick = { leave(); vm.type("") }) {
                        MIcon(R.drawable.ic_m_x, stringResource(R.string.carte_search_clear), size = 20.dp)
                    }
                }
                FilledTonalIconToggleButton(
                    checked = vm.where == Where.HERE,
                    onCheckedChange = { on -> leave(); vm.chooseWhere(if (on) Where.HERE else Where.ZONE) },
                    modifier = Modifier.semantics {
                        contentDescription = around
                        stateDescription = state
                    },
                ) {
                    MIcon(R.drawable.ic_m_locate, null, size = 20.dp)
                }
            }
        }
        val categories = (vm.info as? Load.Ready)?.value?.categories.orEmpty()
        if (categories.isNotEmpty()) {
            LazyRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                contentPadding = PaddingValues(horizontal = 12.dp),
                modifier = Modifier.fillMaxWidth().padding(top = 6.dp, bottom = 4.dp),
            ) {
                items(categories, key = { it.id }) { c -> CategoryChip(c, c.id == vm.cat && vm.look == null) { leave(); vm.chooseCategory(c.id) } }
            }
        }
    }
}

@Composable
private fun CategoryChip(c: Category, on: Boolean, onClick: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    FilterChip(
        selected = on,
        onClick = onClick,
        label = { Text(c.label) },
        leadingIcon = { MIcon(categoryIcon(c.id), null, size = 16.dp) },
        colors = FilterChipDefaults.filterChipColors(containerColor = scheme.surfaceContainerHigh),
        elevation = FilterChipDefaults.filterChipElevation(elevation = 2.dp),
    )
}

/** La feuille du bas : la fiche du lieu choisi, sinon les résultats (ou ce qui empêche de chercher). */
@Composable
private fun ExplorerSheet(vm: ExplorerViewModel, links: CarteLinks, modifier: Modifier) {
    val chosen = vm.chosen
    Column(modifier.fillMaxWidth()) {
        if (vm.loading) LinearProgressIndicator(Modifier.fillMaxWidth().padding(horizontal = 16.dp))
        if (chosen != null) {
            PlaceCard(chosen, vm.where ?: Where.ZONE, links, hers = vm.look != null, onClose = { vm.select(null) })
        } else if (vm.look != null) {
            RegardResults(vm, links)
        } else {
            Results(vm)
        }
    }
}

/** Les résultats (`resultsMarkup` du web) : la phrase de plus, les adresses, les lieux de l'index, ou pourquoi rien. */
@Composable
private fun Results(vm: ExplorerViewModel) {
    val scheme = MaterialTheme.colorScheme
    val info = vm.info
    LazyColumn(Modifier.fillMaxWidth(), contentPadding = PaddingValues(bottom = 24.dp)) {
        if (info is Load.Failed) {
            item("info") {
                Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                    NoteBox(stringResource(R.string.carte_info_failed, info.error.said), R.drawable.ic_m_alert, tone = Tone.WARN)
                    TextButton(onClick = vm::retryInfo) { Text(stringResource(R.string.retry)) }
                }
            }
        }
        val hint = when (vm.hint) {
            ExplorerHint.NO_POSITION -> R.string.carte_hint_no_position
            ExplorerHint.CHOOSE_WHERE -> R.string.carte_hint_where
            ExplorerHint.NONE -> null
        }
        if (hint != null) {
            item("hint") {
                Row(Modifier.padding(horizontal = 16.dp, vertical = 6.dp)) {
                    MIcon(R.drawable.ic_m_info, null, size = 16.dp, tint = scheme.onSurfaceVariant)
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(hint), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
                }
            }
        }
        if (vm.addresses.isNotEmpty() || vm.addrError.isNotEmpty()) {
            item("addr-head") {
                GroupHead(stringResource(R.string.carte_addresses), stringResource(R.string.carte_addresses_note))
            }
            if (vm.addrError.isNotEmpty()) {
                item("addr-error") {
                    NoteBox(vm.addrError, R.drawable.ic_m_alert, Modifier.padding(horizontal = 16.dp, vertical = 4.dp), tone = Tone.WARN)
                }
            }
            itemsIndexed(vm.addresses, key = { i, _ -> addressId(i) }) { i, p -> PlaceRow(p) { vm.select(addressId(i)) } }
        }
        when {
            vm.error.isNotEmpty() -> item("error") {
                Column(Modifier.padding(16.dp)) {
                    Text(stringResource(R.string.carte_places_failed), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Medium)
                    Text(vm.error, style = MaterialTheme.typography.bodyMedium, color = scheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp))
                }
            }
            !vm.searched -> if (!vm.loading) item("empty") { Empty(R.drawable.ic_m_search, stringResource(R.string.carte_empty_title), stringResource(R.string.carte_empty_text)) }
            else -> {
                item("head") {
                    val title = searchTitle((info as? Load.Ready)?.value, vm.q, vm.cat)
                    GroupHead(title, "${searchLegend(vm.searchedNear, vm.places)} · ${stringResource(R.string.carte_index_note)}")
                }
                if (vm.places.isEmpty()) {
                    item("none") {
                        val text = if (vm.loading) R.string.carte_searching
                        else if (vm.where == Where.HERE) R.string.carte_nothing_here else R.string.carte_nothing_zone
                        Empty(R.drawable.ic_m_search, null, stringResource(text))
                    }
                }
                itemsIndexed(vm.places, key = { i, p -> "l:" + placeId(p, i) }) { i, p -> PlaceRow(p) { vm.select(placeId(p, i)) } }
            }
        }
    }
}

/** Le titre d'un groupe de la feuille, et ce qu'il dit de plus. */
@Composable
private fun GroupHead(title: String, more: String) {
    Column(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 10.dp, bottom = 4.dp)) {
        Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
        if (more.isNotBlank()) Text(more, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun Empty(@DrawableRes icon: Int, title: String?, text: String) {
    val scheme = MaterialTheme.colorScheme
    Column(
        Modifier.fillMaxWidth().padding(horizontal = 32.dp, vertical = 20.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        MIcon(icon, null, size = 28.dp, tint = scheme.onSurfaceVariant)
        if (title != null) Text(title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 8.dp))
        Text(text, style = MaterialTheme.typography.bodyMedium, color = scheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp))
    }
}

/**
 * Ce que Mika a cherché ou montré (`placeItem` du web, `by-mika`) : ses lieux en rose, « Mika te l'a proposé », où
 * l'ouvrir aussi (son trajet dans Itinéraire, son voyage) ; oublié (404) : pourquoi ; une autre panne se réessaie.
 */
@Composable
private fun RegardResults(vm: ExplorerViewModel, links: CarteLinks) {
    val scheme = MaterialTheme.colorScheme
    val seq = vm.look ?: return
    when (val load = vm.regardLoad) {
        null, Load.Loading -> Empty(R.drawable.ic_m_sparkle, null, stringResource(R.string.carte_regard_loading))
        is Load.Failed -> if (load.error.gone) {
            Empty(R.drawable.ic_m_map, stringResource(R.string.carte_regard_gone_title), stringResource(R.string.carte_regard_gone_text))
        } else {
            Column(Modifier.fillMaxWidth().padding(16.dp)) {
                Text(stringResource(R.string.carte_regard_failed), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Medium)
                Text(load.error.said, style = MaterialTheme.typography.bodyMedium, color = scheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp))
                TextButton(onClick = vm::retryLook) { Text(stringResource(R.string.retry)) }
            }
        }
        is Load.Ready -> {
            val r: Regard = load.value
            val shown = r.what == Regard.WHAT_ROUTE || r.kind == Regard.KIND_MAP
            LazyColumn(Modifier.fillMaxWidth(), contentPadding = PaddingValues(bottom = 24.dp)) {
                item("regard-head") {
                    Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 10.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                        MIcon(R.drawable.ic_m_sparkle, null, size = 16.dp, tint = mika.accent)
                        Spacer(Modifier.width(6.dp))
                        Column(Modifier.weight(1f)) {
                            Text(
                                r.title.ifBlank { stringResource(if (shown) R.string.carte_regard_shown else R.string.carte_regard_looked) },
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.SemiBold,
                                color = mika.accent,
                                maxLines = 2,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Text(
                                "${plural(r.places.size.toLong(), "lieu", "lieux")} · ${stringResource(if (shown) R.string.carte_regard_shown_lc else R.string.carte_regard_looked_lc)}",
                                style = MaterialTheme.typography.bodySmall,
                                color = scheme.onSurfaceVariant,
                            )
                        }
                    }
                }
                if (r.isRoute || r.trip.isNotBlank()) {
                    item("regard-links") {
                        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            if (r.isRoute) {
                                FilledTonalButton(onClick = { links.open(Route.Carte(CarteTabs.ROUTE, look = seq)) }) {
                                    ButtonContent(R.drawable.ic_m_route, stringResource(R.string.carte_regard_open_route))
                                }
                            }
                            if (r.trip.isNotBlank()) {
                                FilledTonalButton(onClick = { links.open(Route.Trip(r.trip)) }) {
                                    ButtonContent(R.drawable.ic_m_flag, stringResource(R.string.carte_regard_open_trip))
                                }
                            }
                        }
                    }
                }
                if (r.places.isEmpty()) {
                    item("regard-none") { Empty(R.drawable.ic_m_map, null, stringResource(R.string.carte_regard_empty)) }
                }
                itemsIndexed(r.places, key = { i, p -> "r:" + placeId(p, i) }) { i, p -> PlaceRow(p, hers = true) { vm.select(placeId(p, i)) } }
            }
        }
    }
}

/** Un lieu de la liste : sa catégorie, son nom, ce qu'il est et où, sa distance ; [hers] : un lieu qu'elle t'a proposé, en rose. */
@Composable
private fun PlaceRow(p: Place, hers: Boolean = false, onClick: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    Row(
        Modifier.fillMaxWidth().heightIn(min = 56.dp).clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(40.dp).clip(RoundedCornerShape(12.dp)).background(if (hers) mika.container else scheme.secondaryContainer),
            contentAlignment = Alignment.Center,
        ) {
            MIcon(categoryIcon(p.category), null, size = 20.dp, tint = if (hers) mika.onContainer else scheme.onSecondaryContainer)
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(p.name.ifBlank { "—" }, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            val what = placeWhat(p)
            if (what.isNotBlank()) Text(what, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (hers) {
                Text(
                    stringResource(R.string.carte_regard_proposed),
                    style = MaterialTheme.typography.labelMedium,
                    color = mika.accent,
                    maxLines = 1,
                )
            }
        }
        val dist = km(p.distanceM)
        if (dist.isNotEmpty()) {
            Spacer(Modifier.width(8.dp))
            Text(dist, style = MaterialTheme.typography.labelMedium, color = scheme.onSurfaceVariant)
        }
    }
}

/**
 * La fiche d'un lieu (`place-card`) : son nom, ce qu'il est, où et à quelle distance ; Itinéraire, Au voyage, En parler.
 * [hers] : un lieu de son regard (`by-mika`), « Mika te l'a proposé ».
 */
@Composable
private fun PlaceCard(p: Place, where: Where, links: CarteLinks, hers: Boolean, onClose: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    Column(Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, top = 4.dp, bottom = 16.dp)) {
        Row(verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f).padding(top = 8.dp)) {
                if (hers) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        MIcon(R.drawable.ic_m_sparkle, null, size = 14.dp, tint = mika.accent)
                        Spacer(Modifier.width(4.dp))
                        Text(stringResource(R.string.carte_regard_proposed), style = MaterialTheme.typography.labelMedium, color = mika.accent)
                    }
                }
                Text(p.name.ifBlank { "—" }, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                val line = placeLine(p, where)
                if (line.isNotBlank()) Text(line, style = MaterialTheme.typography.bodyMedium, color = scheme.onSurfaceVariant, modifier = Modifier.padding(top = 2.dp))
            }
            IconButton(onClick = onClose) { MIcon(R.drawable.ic_m_x, stringResource(R.string.carte_place_close)) }
        }
        Row(Modifier.fillMaxWidth().padding(top = 14.dp, end = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            val small = PaddingValues(horizontal = 10.dp, vertical = 8.dp)
            val routeLabel = stringResource(R.string.carte_place_route_full)
            Button(onClick = { links.routeTo(p) }, contentPadding = small, modifier = Modifier.weight(1f).semantics { contentDescription = routeLabel }) {
                ButtonContent(R.drawable.ic_m_route, stringResource(R.string.carte_place_route))
            }
            val tripLabel = stringResource(R.string.carte_place_trip_full)
            FilledTonalButton(onClick = { links.addToTrip(p) }, contentPadding = small, modifier = Modifier.weight(1f).semantics { contentDescription = tripLabel }) {
                ButtonContent(R.drawable.ic_m_plus, stringResource(R.string.carte_place_trip))
            }
            val askLabel = stringResource(R.string.carte_place_ask_full)
            OutlinedButton(
                onClick = { links.ask(p) },
                contentPadding = small,
                border = BorderStroke(1.dp, mika.line),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = mika.accent),
                modifier = Modifier.weight(1f).semantics { contentDescription = askLabel },
            ) {
                ButtonContent(R.drawable.ic_m_chat, stringResource(R.string.carte_place_ask))
            }
        }
    }
}

@Composable
private fun ButtonContent(@DrawableRes icon: Int, text: String) {
    MIcon(icon, null, size = 16.dp)
    Spacer(Modifier.width(6.dp))
    Text(text, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.labelLarge)
}

/** L'icône d'une catégorie de l'index (`categoryIcon` du web, dans le jeu de la maquette ; « courses » n'y a pas la sienne). */
@DrawableRes
internal fun categoryIcon(category: String): Int = when (category) {
    "manger" -> R.drawable.ic_m_smile
    "dormir" -> R.drawable.ic_m_moon
    "voir" -> R.drawable.ic_m_eye
    "nature" -> R.drawable.ic_m_sun
    "route" -> R.drawable.ic_m_bolt
    "sante" -> R.drawable.ic_m_heart
    "sortir" -> R.drawable.ic_m_star
    "services" -> R.drawable.ic_m_info
    else -> R.drawable.ic_m_pin
}
