package fr.qwartz.mika.ui.carte

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
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.BottomSheetScaffold
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.DateRangePicker
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FilledTonalIconToggleButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.rememberBottomSheetScaffoldState
import androidx.compose.material3.rememberDateRangePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
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
import fr.qwartz.mika.data.moi.carte.DayRange
import fr.qwartz.mika.data.moi.carte.EVENTS_READ
import fr.qwartz.mika.data.moi.carte.EventItem
import fr.qwartz.mika.data.moi.carte.LinkText
import fr.qwartz.mika.data.moi.carte.WhenKind
import fr.qwartz.mika.data.moi.carte.Where
import fr.qwartz.mika.data.moi.carte.coverageLine
import fr.qwartz.mika.data.moi.carte.eventDays
import fr.qwartz.mika.data.moi.carte.eventLine
import fr.qwartz.mika.data.moi.carte.isoDay
import fr.qwartz.mika.data.moi.carte.km
import fr.qwartz.mika.data.moi.carte.listThumb
import fr.qwartz.mika.data.moi.carte.plural
import fr.qwartz.mika.data.moi.carte.priceWords
import fr.qwartz.mika.data.moi.carte.rangeWords
import fr.qwartz.mika.ui.map.ScenePlan
import fr.qwartz.mika.ui.map.SceneMap
import fr.qwartz.mika.ui.map.rememberMapFond
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.shell.said
import fr.qwartz.mika.ui.shell.toneColors
import fr.qwartz.mika.ui.theme.mika
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset

/** La part de l'écran que la feuille des événements prend d'abord (comme Explorer). */
private const val EVENTS_SHEET_SHARE = 0.46f

/**
 * Événements (ADR 0259 ; la maquette `vueEvenements` de `ecrans/carte-avis.js`) : la carte prend l'écran, la recherche
 * flotte dessus — un texte, « Autour de moi » au bout du champ, quand (aujourd'hui, ce week-end, cette semaine, des
 * dates) en puces —, puis dans la feuille qui monte du bas : quoi (les thèmes du serveur, « Gratuit »), ce que la base
 * sait de la zone, et la liste par jour ; leurs épingles sur la carte. Un événement touché, dans la liste ou sur la
 * carte, ouvre sa fiche par-dessus. Ce que Mika a trouvé prend la place de la liste, en rose.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun EventsTab(graph: AppGraph, vm: EventsViewModel, links: CarteLinks, modifier: Modifier) {
    val sheet = rememberBottomSheetScaffoldState()
    val density = LocalDensity.current
    val fonds = rememberMapFond(graph)
    SideEffect { vm.fondZone = fonds.fond?.zone }
    val store = rememberCarteStore(graph)
    val themes = store.info.valueOrNull?.themes.orEmpty()
    // ce qu'elle a trouvé vient d'être lu (ou d'échouer) : la carte le cadre une fois
    val framed = when (vm.regardLoad) {
        is Load.Ready -> "lu"
        is Load.Failed -> "échec"
        else -> ""
    }
    LaunchedEffect(vm.look, framed) {
        if (vm.look != null && framed.isNotEmpty()) vm.control.fit(orBase = framed == "échec")
    }
    var searchPx by remember { mutableIntStateOf(0) }
    var picking by remember { mutableStateOf(false) }
    val leave = { if (vm.look != null) links.leaveLook() }
    BoxWithConstraints(modifier) {
        val peek = (maxHeight * EVENTS_SHEET_SHARE).coerceIn(160.dp, 360.dp)
        val searchTop = with(density) { searchPx.toDp() }
        val title = stringResource(R.string.events_map_title)
        BottomSheetScaffold(
            scaffoldState = sheet,
            sheetPeekHeight = peek,
            sheetContent = { EventsSheet(graph, vm, themes, links, leave, onDates = { picking = true }, Modifier.heightIn(min = peek)) },
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
                    onPin = { id -> vm.eventOf(id)?.let { e -> links.openEvent(e, vm.look != null) } ?: vm.select(id) },
                    onMove = vm::mapMoved,
                    plan = { why ->
                        ScenePlan(scene, title, why, Modifier.fillMaxSize(), notePadding = Modifier.padding(bottom = peek))
                    },
                )
                EventsSearch(vm, leave, onDates = { picking = true }, Modifier.align(Alignment.TopCenter).onSizeChanged { searchPx = it.height })
            }
        }
    }
    if (picking) {
        DatesDialog(vm.dates, onDismiss = { picking = false }) { range ->
            picking = false
            leave()
            vm.chooseDates(range)
        }
    }
}

/** La recherche qui flotte sur la carte : le champ, « Autour de moi » au bout, puis quand, en puces. */
@Composable
private fun EventsSearch(vm: EventsViewModel, leave: () -> Unit, onDates: () -> Unit, modifier: Modifier) {
    val focus = LocalFocusManager.current
    val scheme = MaterialTheme.colorScheme
    val around = stringResource(R.string.carte_around_me)
    val state = stringResource(if (vm.where == Where.HERE) R.string.carte_around_me_on else R.string.carte_around_me_off)
    val now = LocalShell.current.graph.clock.wallMs()
    Column(modifier.fillMaxWidth().padding(top = 8.dp)) {
        Surface(
            shape = RoundedCornerShape(28.dp),
            color = scheme.surfaceContainerHigh,
            shadowElevation = 3.dp,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(start = 16.dp, end = 4.dp)) {
                MIcon(R.drawable.ic_m_search, null, size = 20.dp, tint = scheme.onSurfaceVariant)
                val label = stringResource(R.string.events_search_label)
                TextField(
                    value = vm.q,
                    onValueChange = { leave(); vm.type(it) },
                    placeholder = { Text(stringResource(R.string.events_search_hint), maxLines = 1, overflow = TextOverflow.Ellipsis) },
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
        LazyRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            contentPadding = PaddingValues(horizontal = 12.dp),
            modifier = Modifier.fillMaxWidth().padding(top = 6.dp, bottom = 4.dp),
        ) {
            items(WhenKind.entries, key = { it.id }) { k ->
                val on = vm.whenKind == k && vm.look == null
                val label = if (k == WhenKind.DATES && on) rangeWords(vm.dates, now).ifBlank { k.label } else k.label
                FilterChip(
                    selected = on,
                    onClick = {
                        leave()
                        if (k == WhenKind.DATES) onDates() else vm.chooseWhen(k)
                    },
                    label = { Text(label) },
                    leadingIcon = if (k == WhenKind.DATES) ({ MIcon(R.drawable.ic_m_calendar, null, size = 16.dp) }) else null,
                    colors = FilterChipDefaults.filterChipColors(containerColor = scheme.surfaceContainerHigh),
                    elevation = FilterChipDefaults.filterChipElevation(elevation = 2.dp),
                )
            }
        }
    }
}

/** « Des dates… » : un sélecteur de période ; ce qu'on choisit se remet dans l'ordre. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DatesDialog(current: DayRange, onDismiss: () -> Unit, onPick: (DayRange) -> Unit) {
    fun millisOf(iso: String): Long? = isoDay(iso)?.atStartOfDay(ZoneOffset.UTC)?.toInstant()?.toEpochMilli()
    fun isoOf(ms: Long?): String = ms?.let { Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate().toString() }.orEmpty()
    val state = rememberDateRangePickerState(
        initialSelectedStartDateMillis = millisOf(current.start) ?: millisOf(LocalDate.now().toString()),
        initialSelectedEndDateMillis = millisOf(current.end),
    )
    DatePickerDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(
                onClick = { onPick(DayRange(isoOf(state.selectedStartDateMillis), isoOf(state.selectedEndDateMillis))) },
                enabled = state.selectedStartDateMillis != null,
            ) { Text(stringResource(R.string.events_dates_ok)) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    ) {
        DateRangePicker(state = state, modifier = Modifier.weight(1f, fill = false))
    }
}

/**
 * La feuille des événements : quoi (les thèmes, « Gratuit »), ce que la base sait de la zone, la liste par jour, la
 * source ; ce que Mika a trouvé (en rose) à la place quand la route en montre un ; ou ce qui empêche de chercher.
 */
@Composable
private fun EventsSheet(
    graph: AppGraph,
    vm: EventsViewModel,
    themes: List<Category>,
    links: CarteLinks,
    leave: () -> Unit,
    onDates: () -> Unit,
    modifier: Modifier,
) {
    val scheme = MaterialTheme.colorScheme
    val now = graph.clock.wallMs()
    val hers = vm.look != null
    Column(modifier.fillMaxWidth()) {
        if (vm.loading && !hers) LinearProgressIndicator(Modifier.fillMaxWidth().padding(horizontal = 16.dp))
        LazyColumn(Modifier.fillMaxWidth(), contentPadding = PaddingValues(bottom = 24.dp)) {
            if (!hers) {
                item("what") {
                    LazyRow(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        contentPadding = PaddingValues(horizontal = 16.dp),
                        modifier = Modifier.fillMaxWidth().padding(top = 4.dp, bottom = 2.dp),
                    ) {
                        items(themes, key = { "t:" + it.id }) { t ->
                            FilterChip(selected = t.id in vm.themes, onClick = { leave(); vm.toggleTheme(t.id) }, label = { Text(t.label) })
                        }
                        item("free") {
                            FilterChip(selected = vm.free, onClick = { leave(); vm.toggleFree() }, label = { Text(stringResource(R.string.events_free)) })
                        }
                    }
                }
                if (vm.whenKind == WhenKind.DATES) {
                    item("dates") {
                        TextButton(onClick = onDates, modifier = Modifier.padding(horizontal = 8.dp)) {
                            MIcon(R.drawable.ic_m_calendar, null, size = 16.dp)
                            Spacer(Modifier.width(6.dp))
                            Text(stringResource(R.string.events_dates_change, rangeWords(vm.dates, now)), style = MaterialTheme.typography.labelLarge)
                        }
                    }
                }
            }
            val hint = when (vm.hint) {
                ExplorerHint.NO_POSITION -> R.string.carte_hint_no_position
                ExplorerHint.CHOOSE_WHERE -> R.string.events_hint_where
                ExplorerHint.NONE -> null
            }
            if (hint != null && !hers) {
                item("hint") {
                    Row(Modifier.padding(horizontal = 16.dp, vertical = 6.dp)) {
                        MIcon(R.drawable.ic_m_info, null, size = 16.dp, tint = scheme.onSurfaceVariant)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(hint), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
                    }
                }
            }
            if (hers) {
                regardItems(graph, vm, themes, links, now)
                return@LazyColumn
            }
            when {
                vm.error.isNotEmpty() -> item("error") {
                    Column(Modifier.padding(16.dp)) {
                        Text(stringResource(R.string.events_failed), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Medium)
                        Text(vm.error, style = MaterialTheme.typography.bodyMedium, color = scheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp))
                        TextButton(onClick = vm::retry) { Text(stringResource(R.string.retry)) }
                    }
                }
                !vm.searched -> item("empty") {
                    if (!vm.loading) {
                        EmptyLine(R.drawable.ic_m_calendar, stringResource(R.string.events_empty_title), stringResource(R.string.events_empty_text))
                    }
                }
                else -> {
                    item("head") {
                        EventsHead(
                            title = stringResource(R.string.events_title),
                            count = vm.events.size,
                            where = stringResource(if (vm.searchedNear) R.string.events_around_me else R.string.events_in_zone),
                            cover = coverageLine(vm.coverage, EVENTS_READ, now),
                        )
                    }
                    if (vm.events.isEmpty()) {
                        item("none") {
                            EmptyLine(
                                R.drawable.ic_m_calendar,
                                null,
                                stringResource(if (vm.searchedNear) R.string.events_nothing_here else R.string.events_nothing_zone),
                            )
                        }
                    }
                    for (day in eventDays(vm.events, now)) {
                        item("d:" + day.day) {
                            Text(
                                day.title,
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.Medium,
                                color = scheme.primary,
                                modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 14.dp, bottom = 4.dp),
                            )
                        }
                        items(day.events, key = { "e:" + day.day + it.id }) { e ->
                            EventRow(graph, e, themes, inDay = day.day.isNotEmpty(), hers = false, selected = vm.sel == e.id) { links.openEvent(e, false) }
                        }
                    }
                    if (vm.events.isNotEmpty()) {
                        item("source") { SourceLine(listOf(LinkText(stringResource(R.string.events_source))), rememberOutside(), Modifier.padding(top = 8.dp)) }
                    }
                }
            }
        }
    }
}

/** Ce que Mika a trouvé : en lecture, oublié (404), en panne (réessayer), ou ses événements en rose, par jour. */
private fun LazyListScope.regardItems(graph: AppGraph, vm: EventsViewModel, themes: List<Category>, links: CarteLinks, now: Long) {
    when (val load = vm.regardLoad) {
        null, Load.Loading -> item("r-loading") { EmptyLine(R.drawable.ic_m_sparkle, null, stringResource(R.string.events_regard_loading)) }
        is Load.Failed -> item("r-failed") {
            if (load.error.gone) {
                EmptyLine(R.drawable.ic_m_calendar, stringResource(R.string.events_regard_gone_title), stringResource(R.string.carte_regard_gone_text))
            } else {
                Column(Modifier.fillMaxWidth().padding(16.dp)) {
                    Text(stringResource(R.string.events_regard_failed), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Medium)
                    Text(load.error.said, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp))
                    TextButton(onClick = vm::retryLook) { Text(stringResource(R.string.retry)) }
                }
            }
        }
        is Load.Ready -> {
            val shown = vm.regardEvents.orEmpty()
            item("r-head") {
                Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, top = 10.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                    MIcon(R.drawable.ic_m_sparkle, null, size = 16.dp, tint = mika.accent)
                    Spacer(Modifier.width(6.dp))
                    Column(Modifier.weight(1f)) {
                        Text(
                            load.value.title.ifBlank { stringResource(R.string.events_regard_title) },
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.SemiBold,
                            color = mika.accent,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                        )
                        Text(
                            "${plural(shown.size.toLong(), "événement")} · ${stringResource(R.string.events_regard_lc)}",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    TextButton(onClick = links.leaveLook) { Text(stringResource(R.string.events_all)) }
                }
            }
            if (shown.isEmpty()) item("r-none") { EmptyLine(R.drawable.ic_m_calendar, null, stringResource(R.string.events_regard_empty)) }
            for (day in eventDays(shown, now)) {
                item("rd:" + day.day) {
                    Text(
                        day.title,
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.Medium,
                        color = mika.accent,
                        modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 14.dp, bottom = 4.dp),
                    )
                }
                items(day.events, key = { "re:" + day.day + it.id }) { e ->
                    EventRow(graph, e, themes, inDay = day.day.isNotEmpty(), hers = true, selected = vm.sel == e.id) { links.openEvent(e, true) }
                }
            }
        }
    }
}

/** La tête de la liste : « Événements · 12 · autour de toi », puis ce que la base sait de la zone, en petit. */
@Composable
private fun EventsHead(title: String, count: Int, where: String, cover: String) {
    val scheme = MaterialTheme.colorScheme
    Column(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 10.dp, bottom = 2.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.width(6.dp))
            Text(count.toString(), style = MaterialTheme.typography.labelMedium, color = scheme.onSurfaceVariant)
            Spacer(Modifier.weight(1f))
            Text(where, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
        }
        if (cover.isNotEmpty()) {
            Row(Modifier.padding(top = 4.dp)) {
                MIcon(R.drawable.ic_m_info, null, size = 13.dp, tint = scheme.onSurfaceVariant, modifier = Modifier.padding(top = 2.dp))
                Spacer(Modifier.width(6.dp))
                Text(cover, style = MaterialTheme.typography.labelSmall, color = scheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun EmptyLine(icon: Int, title: String?, text: String) {
    val scheme = MaterialTheme.colorScheme
    Column(Modifier.fillMaxWidth().padding(horizontal = 32.dp, vertical = 20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        MIcon(icon, null, size = 28.dp, tint = scheme.onSurfaceVariant)
        if (title != null) Text(title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 8.dp))
        Text(text, style = MaterialTheme.typography.bodyMedium, color = scheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp))
    }
}

/**
 * Un événement de la liste (`ligne` de la maquette) : sa vignette (sa photo, quand on sait son auteur — cité sous la
 * ligne avec sa licence, R2-A01 —, sinon l'agenda), son nom ; son thème, son quand (sans le jour que dit déjà sa tête)
 * et son lieu ; son prix (vert s'il est gratuit), « repéré par Mika » en rose ; sa distance.
 */
@Composable
internal fun EventRow(
    graph: AppGraph,
    e: EventItem,
    themes: List<Category>,
    inDay: Boolean,
    hers: Boolean,
    selected: Boolean = false,
    onClick: () -> Unit,
) {
    val scheme = MaterialTheme.colorScheme
    val thumb = listThumb(e)
    Row(
        Modifier.fillMaxWidth().heightIn(min = 64.dp)
            .background(if (selected) scheme.secondaryContainer.copy(alpha = 0.5f) else Color.Transparent)
            .clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (thumb != null) {
            Box(Modifier.size(48.dp).clip(RoundedCornerShape(12.dp))) { PhotoImage(graph, thumb.ref, null, Modifier.size(48.dp)) }
        } else {
            Box(
                Modifier.size(40.dp).clip(RoundedCornerShape(12.dp)).background(if (hers) mika.container else scheme.secondaryContainer),
                contentAlignment = Alignment.Center,
            ) {
                MIcon(R.drawable.ic_m_calendar, null, size = 20.dp, tint = if (hers) mika.onContainer else scheme.onSecondaryContainer)
            }
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(e.name.ifBlank { "—" }, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            val line = eventLine(e, themes, inDay)
            if (line.isNotEmpty()) Text(line, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            val price = priceWords(e)
            if (price.isNotEmpty() || hers) {
                Row {
                    if (price.isNotEmpty()) {
                        val color = if (e.free == true) toneColors(Tone.OK).second else scheme.onSurfaceVariant
                        Text(price, style = MaterialTheme.typography.bodySmall, color = color, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                    }
                    if (hers) {
                        Text(
                            (if (price.isNotEmpty()) " · " else "") + stringResource(R.string.events_found_by_mika),
                            style = MaterialTheme.typography.bodySmall,
                            fontWeight = FontWeight.Medium,
                            color = mika.accent,
                            maxLines = 1,
                        )
                    }
                }
            }
            if (thumb != null) ThumbCredit(thumb, Modifier.padding(top = 2.dp))
        }
        val dist = km(e.distanceM)
        if (dist.isNotEmpty()) {
            Spacer(Modifier.width(8.dp))
            Text(dist, style = MaterialTheme.typography.labelMedium, color = scheme.onSurfaceVariant)
        }
    }
}
