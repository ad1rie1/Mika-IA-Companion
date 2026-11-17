package fr.qwartz.mika.ui.carte

import androidx.activity.compose.LocalActivity
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.files.ComposerDraft
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.carte.AlongState
import fr.qwartz.mika.data.moi.carte.CarteLimits
import fr.qwartz.mika.data.moi.carte.Category
import fr.qwartz.mika.data.moi.carte.Trip
import fr.qwartz.mika.data.moi.carte.TripDay
import fr.qwartz.mika.data.moi.carte.TripRoute
import fr.qwartz.mika.data.moi.carte.alongFacts
import fr.qwartz.mika.data.moi.carte.alongIndexOf
import fr.qwartz.mika.data.moi.carte.dayFacts
import fr.qwartz.mika.data.moi.carte.dayTitle
import fr.qwartz.mika.data.moi.carte.duration
import fr.qwartz.mika.data.moi.carte.hersCount
import fr.qwartz.mika.data.moi.carte.km
import fr.qwartz.mika.data.moi.carte.legWords
import fr.qwartz.mika.data.moi.carte.plural
import fr.qwartz.mika.data.moi.carte.stepMove
import fr.qwartz.mika.data.moi.carte.stopCount
import fr.qwartz.mika.data.moi.carte.tripHead
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.map.SceneMap
import fr.qwartz.mika.ui.map.rememberMapFond
import fr.qwartz.mika.ui.settings.ConfirmDialog
import fr.qwartz.mika.ui.shell.BarAction
import fr.qwartz.mika.ui.shell.BarMenu
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MenuEntry
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.shell.Notice
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.shell.said
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** La hauteur de la carte d'un voyage (la maquette : 230 dp sous la barre). */
private val MAP_HEIGHT = 230.dp

/*
 * Un voyage (`Route.Trip`, la maquette `vueVoyage`, ADR 0195) : la carte en haut — ses arrêts numérotés, les siens en
 * rose, le trajet de ses tronçons quand il se calcule (relu après le dernier geste), les lieux de « Sur la route » en
 * épingles secondaires —, puis l'éditeur jour par jour : la poignée (glisser, ou la toucher : monter, descendre), noter
 * en place, retirer, « Ajouter un arrêt », « Ajouter un jour ». Dans la barre : ✦ « Demander à Mika » et ⋮ (optimiser
 * l'ordre, le GPX, le voyage, « Sur la route », le supprimer), une fois le voyage lu.
 */

/** L'arrêt qu'on glisse, de combien il a bougé, et où il tomberait. */
private data class Drag(val stop: String, val dy: Float, val target: DropTarget?)

@Composable
fun TripScreen(graph: AppGraph, route: Route.Trip) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val store = rememberCarteStore(graph)
    val vm: TripViewModel = viewModel(key = "carte.trip|$session|${route.id}") { TripViewModel(TripDeps(graph, store), route.id) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(vm, lifecycle) { lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) { vm.resume() } }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    LaunchedEffect(vm) { vm.deleted.collect { shell.back() } }
    val trip = vm.shown
    val now = graph.clock.wallMs()
    var editing by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf(false) }
    var addDay by remember { mutableStateOf<Int?>(null) }
    // « Sur la route » est ouvert dans le modèle : quitter l'écran du voyage le referme (ses épingles, ses relectures),
    // une rotation le garde
    val activity = LocalActivity.current
    DisposableEffect(vm) {
        onDispose { if (activity?.isChangingConfigurations != true) vm.leave() }
    }
    val ask = {
        val text = vm.askText()
        graph.scope.launch { graph.shareInbox.deposit(ComposerDraft(text = text)) }
        shell.open(Route.Chat)
    }
    val toggleAlong = vm::toggleAlongPanel
    SectionScaffold(
        topBar = {
            MikaTopBar(
                title = trip?.title?.ifBlank { stringResource(R.string.carte_untitled) } ?: stringResource(R.string.carte_trip_title),
                nav = BarNav.BACK,
                subtitle = trip?.let { tripHead(it, now, short = true) },
                actions = {
                    // une fois le voyage lu : pendant sa lecture, ou introuvable, aucune ne mènerait à rien
                    if (trip != null) {
                        BarAction(R.drawable.ic_m_sparkle, stringResource(R.string.carte_trip_ask), ask, tint = mika.accent)
                        val entries = buildList {
                            add(MenuEntry(stringResource(R.string.carte_trip_optimize), R.drawable.ic_m_sort, vm::optimize))
                            add(MenuEntry(stringResource(R.string.carte_trip_gpx), R.drawable.ic_m_download, vm::gpx))
                            add(MenuEntry(stringResource(R.string.carte_trip_edit), R.drawable.ic_m_pen) { editing = true })
                            if (stopCount(trip) >= 2) add(MenuEntry(stringResource(R.string.carte_trip_along), R.drawable.ic_m_route, toggleAlong))
                            add(MenuEntry(stringResource(R.string.carte_trip_delete), R.drawable.ic_m_trash) { deleting = true })
                        }
                        BarMenu(entries)
                    }
                },
            )
        },
    ) { modifier ->
        val load = vm.load
        when {
            trip != null -> TripBody(graph, vm, trip, store.info.valueOrNull?.categories.orEmpty(), now, vm.alongOpen, toggleAlong, onAddStop = { addDay = it }, modifier = modifier)
            load is Load.Failed && load.error.gone -> Notice(
                stringResource(R.string.carte_trip_gone),
                modifier,
                action = stringResource(R.string.carte_trip_list),
                onAction = { shell.open(Route.Carte(CarteTabs.TRIPS)) },
            )
            load is Load.Failed -> Notice(load.error.said, modifier, action = stringResource(R.string.retry), onAction = vm::retry)
            else -> Box(modifier, contentAlignment = Alignment.Center) { androidx.compose.material3.CircularProgressIndicator() }
        }
    }
    if (editing && trip != null) {
        TripFormDialog(
            edit = trip,
            onDismiss = { editing = false },
            submit = { values, key, _ ->
                val (ok, error) = vm.changeAsync(values, key).await()
                // annulé (un geste d'avant refusé) : la situation a changé, le voyage se relit
                if (ok) null else error ?: MoiError.of(409, null)
            },
        )
    }
    if (deleting && trip != null) {
        ConfirmDialog(
            title = stringResource(R.string.carte_trip_delete_title),
            text = stringResource(R.string.carte_trip_delete_text, trip.title.ifBlank { stringResource(R.string.carte_untitled_lc) }),
            confirm = stringResource(R.string.carte_trip_delete_ok),
            onConfirm = {
                deleting = false
                vm.delete()
            },
            onDismiss = { deleting = false },
            danger = true,
        )
    }
    addDay?.let { day ->
        if (trip != null) AddStopSheet(store, vm, trip, day, onDismiss = { addDay = null })
    }
}

@Composable
private fun TripBody(
    graph: AppGraph,
    vm: TripViewModel,
    trip: Trip,
    categories: List<Category>,
    now: Long,
    alongOpen: Boolean,
    toggleAlong: () -> Unit,
    onAddStop: (Int) -> Unit,
    modifier: Modifier,
) {
    val scheme = MaterialTheme.colorScheme
    val fonds = rememberMapFond(graph)
    val list = rememberLazyListState()
    val scope = rememberCoroutineScope()
    val shown = vm.routeOf(trip)
    val route = shown.route
    val rows = editorRows(trip, route, vm.along, alongOpen)
    var flash by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(flash) {
        if (flash != null) {
            delay(1_200)
            flash = null
        }
    }
    // une épingle touchée : sa ligne (un arrêt, un lieu de « Sur la route »), amenée à l'écran et mise en évidence
    val onPin: (String) -> Unit = { id ->
        val key = if (alongIndexOf(id) != null) id else "stop:$id"
        val at = rows.indexOfFirst { it.key == key }
        if (at >= 0) {
            flash = key
            scope.launch { list.animateScrollToItem(at) }
        }
    }
    Column(modifier) {
        Box(Modifier.fillMaxWidth().height(MAP_HEIGHT)) {
            SceneMap(graph, vm.scene(trip), trip.title.ifBlank { stringResource(R.string.carte_trip_title) }, Modifier.fillMaxSize(), control = vm.control, onPin = onPin)
            if (vm.control.live) Attribution(fonds.fond?.attribution, Modifier.align(Alignment.BottomStart).padding(6.dp))
        }
        // ce que le voyage fait, et « Sur la route »
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            if (route != null && route.distanceM > 0) Tag(km(route.distanceM), Tone.NEUTRAL)
            if (route != null && route.durationS > 0) Tag(stringResource(R.string.carte_trip_driving, duration(route.durationS)), Tone.NEUTRAL)
            if (route == null || route.distanceM <= 0) Tag(plural(trip.days.size.toLong(), "jour"), Tone.NEUTRAL)
            val hers = hersCount(trip)
            if (hers > 0) Tag(plural(hers.toLong(), "arrêt de Mika", "arrêts de Mika"), Tone.MIKA)
            else if (trip.mika) Tag(stringResource(R.string.carte_trip_with_mika), Tone.MIKA)
            Spacer(Modifier.weight(1f))
            if (stopCount(trip) >= 2) {
                FilledTonalButton(onClick = {
                    toggleAlong()
                    if (!alongOpen) scope.launch { list.animateScrollToItem(0) }
                }, contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp)) {
                    MIcon(R.drawable.ic_m_route, null, size = 16.dp)
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.carte_trip_along))
                }
            }
        }
        // le trajet : son refus (et réessayer), ou qu'il se calcule
        val error = shown.error
        if (error != null && !error.gone) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                NoteBox(error.said, R.drawable.ic_m_alert, Modifier.weight(1f), tone = Tone.WARN)
                TextButton(onClick = vm::retry) { Text(stringResource(R.string.retry)) }
            }
        } else if (shown.pending) {
            Hint(stringResource(R.string.carte_trip_route_pending))
        }
        HorizontalDivider()
        TripEditor(vm, trip, route, categories, now, rows, list, flash, onAddStop)
        // ce qu'un lecteur d'écran annonce (un arrêt monté, descendu)
        Box(Modifier.size(1.dp).clearAndSetSemantics {
            contentDescription = vm.announce
            liveRegion = LiveRegionMode.Polite
        })
    }
}

@Composable
private fun TripEditor(
    vm: TripViewModel,
    trip: Trip,
    route: TripRoute?,
    categories: List<Category>,
    now: Long,
    rows: List<EditorRow>,
    list: LazyListState,
    flash: String?,
    onAddStop: (Int) -> Unit,
) {
    var drag by remember { mutableStateOf<Drag?>(null) }
    val target = drag?.target
    // le geste d'une poignée vit tant que sa ligne : il lit la liste du moment (des tronçons arrivés, « Sur la route »
    // ouvert, un autre ordre), jamais celle de quand sa ligne est apparue
    val current by rememberUpdatedState(rows)
    LazyColumn(state = list, contentPadding = PaddingValues(bottom = 32.dp)) {
        items(rows, key = { it.key }) { row ->
            when (row) {
                EditorRow.AlongHead -> AlongHead(vm, categories)
                is EditorRow.AlongPlace -> AlongPlaceRow(vm, trip, route, row.i, flash == row.key)
                EditorRow.AlongEnd -> AlongEnd(vm.along)
                is EditorRow.DayHead -> DayHead(row.day, route, now)
                is EditorRow.Leg -> Text(
                    legWords(row.leg),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(start = 82.dp, top = 2.dp, bottom = 2.dp),
                )
                is EditorRow.Stop -> {
                    val dragging = drag?.stop == row.stop.id
                    DisposableEffect(row.stop.id) {
                        // la ligne glissée quitte la liste (le voyage relu sans elle) : le geste s'arrête
                        onDispose { if (drag?.stop == row.stop.id) drag = null }
                    }
                    StopRow(
                        vm = vm,
                        trip = trip,
                        row = row,
                        flash = flash == row.key,
                        dropHere = target != null && target.before == row.stop.id && !dragging,
                        modifier = if (dragging) {
                            Modifier.zIndex(1f).graphicsLayer {
                                translationY = drag?.dy ?: 0f
                                shadowElevation = 12f
                            }
                        } else {
                            Modifier
                        },
                        grip = Modifier.pointerInput(row.stop.id) {
                            detectDragGestures(
                                onDragStart = { drag = Drag(row.stop.id, 0f, null) },
                                onDragEnd = {
                                    val d = drag
                                    drag = null
                                    val t = d?.target
                                    if (d != null && t != null) vm.drop(d.stop, t.day, t.before)
                                },
                                onDragCancel = { drag = null },
                                onDrag = { change, amount ->
                                    change.consume()
                                    val d = drag ?: return@detectDragGestures
                                    val dy = d.dy + amount.y
                                    val boxes = list.layoutInfo.visibleItemsInfo.map { RowBox(it.key, it.offset, it.size) }
                                    drag = d.copy(dy = dy, target = dropTarget(boxes, current, d.stop, dy))
                                },
                            )
                        },
                    )
                }
                is EditorRow.Empty -> Text(
                    stringResource(R.string.carte_trip_day_empty),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.dropLine(target?.day == row.day && target.before == null).padding(start = 56.dp, top = 6.dp, bottom = 6.dp),
                )
                is EditorRow.AddStop -> {
                    val empty = trip.days.firstOrNull { it.n == row.day }?.stops.isNullOrEmpty()
                    TextButton(
                        onClick = { onAddStop(row.day) },
                        modifier = Modifier.dropLine(!empty && target?.day == row.day && target.before == null).padding(start = 48.dp),
                    ) {
                        MIcon(R.drawable.ic_m_plus, null, size = 16.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.carte_trip_add_stop))
                    }
                }
                is EditorRow.AddDay -> TextButton(
                    onClick = { onAddStop(row.day) },
                    enabled = row.day <= CarteLimits.DAYS,
                    modifier = Modifier.padding(start = 8.dp, top = 8.dp),
                ) {
                    MIcon(R.drawable.ic_m_calendar, null, size = 16.dp)
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.carte_trip_add_day))
                }
            }
        }
    }
}

/** Le trait où tomberait l'arrêt glissé, en haut de cette ligne. */
private fun Modifier.dropLine(on: Boolean): Modifier = if (!on) this else drawBehind {
    drawLine(DROP, Offset(40.dp.toPx(), 1.dp.toPx()), Offset(size.width - 12.dp.toPx(), 1.dp.toPx()), strokeWidth = 3.dp.toPx())
}

private val DROP = androidx.compose.ui.graphics.Color(0xFF4F5BD5)

/** La tête d'un jour : son numéro, « Lille → Dijon » (sinon « Jour 2 »), sa date et ce que son trajet dit. */
@Composable
private fun DayHead(day: TripDay, route: TripRoute?, now: Long) {
    val scheme = MaterialTheme.colorScheme
    Row(Modifier.fillMaxWidth().padding(start = 12.dp, end = 12.dp, top = 14.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(28.dp).clip(CircleShape).background(scheme.secondaryContainer), contentAlignment = Alignment.Center) {
            Text("${day.n}", style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Bold, color = scheme.onSecondaryContainer)
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            val title = dayTitle(day.stops)
            Text(
                if (title.isNotBlank()) stringResource(R.string.carte_trip_day_titled, day.n, title) else stringResource(R.string.carte_trip_day, day.n),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            val facts = dayFacts(day, route, now)
            if (facts.isNotBlank()) Text(facts, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
        }
    }
}

/**
 * Un arrêt : la poignée (la glisser ; la toucher : monter, descendre — ses actions aussi pour un lecteur d'écran), son
 * numéro (rose : elle l'a ajouté), son nom, sa sorte, « ajouté par Mika », sa note à part (de qui qu'il soit : la note
 * n'est pas sa phrase, tu as pu l'écrire ou la corriger) ; noter (le champ en place), retirer.
 */
@Composable
private fun StopRow(
    vm: TripViewModel,
    trip: Trip,
    row: EditorRow.Stop,
    flash: Boolean,
    dropHere: Boolean,
    modifier: Modifier,
    grip: Modifier,
) {
    val scheme = MaterialTheme.colorScheme
    val s = row.stop
    val name = s.name.ifBlank { "—" }
    val editing = vm.noting?.stop == s.id
    var menu by remember { mutableStateOf(false) }
    val up = stepMove(trip, s.id, -1) != null
    val down = stepMove(trip, s.id, 1) != null
    val upLabel = stringResource(R.string.carte_stop_up)
    val downLabel = stringResource(R.string.carte_stop_down)
    val moveLabel = stringResource(R.string.carte_stop_move, name)
    Row(
        modifier
            .fillMaxWidth()
            .background(if (flash) scheme.primaryContainer.copy(alpha = 0.5f) else scheme.surface)
            .dropLine(dropHere)
            .padding(end = 4.dp, top = 4.dp, bottom = 4.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Box {
            Box(
                grip
                    .size(44.dp)
                    .clickable { menu = true }
                    .semantics {
                        contentDescription = moveLabel
                        customActions = buildList {
                            if (up) add(CustomAccessibilityAction(upLabel) { vm.step(s.id, -1); true })
                            if (down) add(CustomAccessibilityAction(downLabel) { vm.step(s.id, 1); true })
                        }
                    },
                contentAlignment = Alignment.Center,
            ) {
                MIcon(R.drawable.ic_m_grip, null, size = 20.dp, tint = scheme.onSurfaceVariant)
            }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                DropdownMenuItem(
                    text = { Text(upLabel) },
                    leadingIcon = { MIcon(R.drawable.ic_m_chev_up, null, size = 20.dp) },
                    enabled = up,
                    onClick = {
                        menu = false
                        vm.step(s.id, -1)
                    },
                )
                DropdownMenuItem(
                    text = { Text(downLabel) },
                    leadingIcon = { MIcon(R.drawable.ic_m_chev_down, null, size = 20.dp) },
                    enabled = down,
                    onClick = {
                        menu = false
                        vm.step(s.id, 1)
                    },
                )
            }
        }
        Box(
            Modifier.padding(top = 10.dp).size(24.dp).clip(CircleShape).background(if (s.hers) mika.fill else scheme.primary),
            contentAlignment = Alignment.Center,
        ) {
            Text("${row.n}", style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold, color = if (s.hers) mika.onFill else scheme.onPrimary)
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f).padding(top = 10.dp)) {
            Text(name, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium, maxLines = 2, overflow = TextOverflow.Ellipsis)
            if (s.kind.isNotBlank()) Text(s.kind, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (s.hers) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    MIcon(R.drawable.ic_m_sparkle, null, size = 12.dp, tint = mika.accent)
                    Spacer(Modifier.width(4.dp))
                    Text(stringResource(R.string.carte_stop_hers), style = MaterialTheme.typography.labelMedium, color = mika.accent)
                }
            }
            if (editing) {
                NoteEditor(vm, name)
            } else if (s.note.isNotBlank()) {
                Text(s.note, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 2.dp))
            }
        }
        IconButton(onClick = { vm.openNote(s.id) }) {
            MIcon(R.drawable.ic_m_pen, stringResource(if (s.note.isNotBlank()) R.string.carte_stop_note_fix else R.string.carte_stop_note, name), size = 18.dp)
        }
        IconButton(onClick = { vm.remove(s.id) }) {
            MIcon(R.drawable.ic_m_x, stringResource(R.string.carte_stop_remove, name), size = 18.dp)
        }
    }
}

/** La note d'un arrêt, en place : prérempli, bornée, Enregistrer et Annuler ; vidée, elle s'efface. */
@Composable
private fun NoteEditor(vm: TripViewModel, name: String) {
    val n = vm.noting ?: return
    val label = stringResource(R.string.carte_stop_note_label, name)
    Column(Modifier.padding(top = 6.dp)) {
        OutlinedTextField(
            value = n.draft,
            onValueChange = vm::typeNote,
            placeholder = { Text(stringResource(R.string.carte_stop_note_hint), maxLines = 1) },
            singleLine = false,
            maxLines = 4,
            modifier = Modifier.fillMaxWidth().semantics { contentDescription = label },
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = vm::saveNote) { Text(stringResource(R.string.carte_stop_note_save)) }
            TextButton(onClick = vm::closeNote) { Text(stringResource(R.string.cancel)) }
        }
        Text(stringResource(R.string.carte_stop_note_help), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

// ── « Sur la route » ────────────────────────────────────────────────────

/** Son titre, et les catégories du serveur en puces (la même : la liste se ferme). */
@Composable
private fun AlongHead(vm: TripViewModel, categories: List<Category>) {
    val scheme = MaterialTheme.colorScheme
    Column(Modifier.fillMaxWidth().background(scheme.surfaceContainerLow).padding(top = 10.dp, bottom = 6.dp)) {
        Text(stringResource(R.string.carte_trip_along), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(horizontal = 16.dp))
        Text(stringResource(R.string.carte_along_note), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 16.dp))
        LazyRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            contentPadding = PaddingValues(horizontal = 16.dp),
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        ) {
            items(categories, key = { it.id }) { c ->
                FilterChip(
                    selected = vm.along.cat == c.id,
                    onClick = { vm.toggleAlong(c.id) },
                    label = { Text(c.label) },
                    leadingIcon = { MIcon(categoryIcon(c.id), null, size = 16.dp) },
                )
            }
        }
    }
}

/** Un lieu le long du trajet : « jour N » d'abord, ce qu'il est, sa distance à la route ; « Ajouter » au bon jour. */
@Composable
private fun AlongPlaceRow(vm: TripViewModel, trip: Trip, route: TripRoute?, i: Int, flash: Boolean) {
    val scheme = MaterialTheme.colorScheme
    val p = vm.along.places.getOrNull(i) ?: return
    Row(
        Modifier
            .fillMaxWidth()
            .background(if (flash) scheme.primaryContainer.copy(alpha = 0.5f) else scheme.surfaceContainerLow)
            .heightIn(min = 56.dp)
            .padding(horizontal = 16.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        MIcon(categoryIcon(p.category), null, size = 18.dp, tint = scheme.onSurfaceVariant)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(p.name.ifBlank { "—" }, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(alongFacts(trip, route, p), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        Spacer(Modifier.width(8.dp))
        FilledTonalButton(
            onClick = { vm.addAlong(i) },
            enabled = vm.along.sending != i,
            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
        ) {
            Text(stringResource(R.string.carte_along_add))
        }
    }
}

/** Ce que la liste dit d'elle : son refus, sa recherche, de quoi choisir, rien de tel, « à vol d'oiseau ». */
@Composable
private fun AlongEnd(along: AlongState) {
    val scheme = MaterialTheme.colorScheme
    val text = when {
        along.error.isNotEmpty() -> stringResource(R.string.carte_along_failed, along.error)
        along.loading -> stringResource(R.string.carte_along_loading)
        along.cat.isEmpty() -> stringResource(R.string.carte_along_choose)
        along.places.isEmpty() -> stringResource(R.string.carte_along_none)
        !along.routed -> stringResource(R.string.carte_along_straight)
        else -> ""
    }
    Column(Modifier.fillMaxWidth().background(scheme.surfaceContainerLow).padding(horizontal = 16.dp, vertical = 8.dp)) {
        if (text.isNotEmpty()) {
            Text(text, style = MaterialTheme.typography.bodySmall, color = if (along.error.isNotEmpty()) scheme.error else scheme.onSurfaceVariant)
        }
    }
    HorizontalDivider()
}
